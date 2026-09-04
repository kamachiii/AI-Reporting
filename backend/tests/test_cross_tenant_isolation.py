"""Test Cross-Tenant Isolation & Security Hardening (F3.1).

Memastikan isolasi mutlak antar-tenant:
1. User hanya bisa query cabang yang ada di allowed_branches (403).
2. User tidak bisa confirm/reject memory ID milik tenant lain (404 - tidak membocorkan eksistensi data).
3. User tidak bisa membaca conversation history cabang lain (403).
4. Operator normalization menjaga integritas komparasi (tidak ada collision > vs <).
5. Schema-aware fewshot filter mencegah halusinasi tabel asing dari global KB.
6. Penegakan daily_token_quota (429 saat habis, tapi memory HIT tetap jalan).
"""
import asyncio
import json
import pytest
from fastapi.testclient import TestClient

from app.core.security import encrypt_credential, require_user_role
from app.main import app
from app.services.chat_pipeline import (
    KuotaTokenHabis,
    normalisasi_pertanyaan,
    _cek_kuota_token,
)
from app.services.fewshot_provider import (
    _sql_relevan_dengan_skema,
    ambil_fewshot_global,
)
from test_chat_api import (
    FakeCorePool,
    FakeTenantConn,
    FakeTenantPoolManager,
    RENCANA,
    SCHEMA_CONFIG_DEALER,
)


def _run(coro):
    return asyncio.run(coro)


class TestOperatorNormalization:
    def test_operator_komparasi_dan_aritmatika_tidak_collision(self):
        norm_gt = normalisasi_pertanyaan("omzet > 100jt")
        norm_lt = normalisasi_pertanyaan("omzet < 100jt")
        norm_gte = normalisasi_pertanyaan("omzet >= 100jt")
        norm_lte = normalisasi_pertanyaan("omzet <= 100jt")
        norm_eq = normalisasi_pertanyaan("omzet = 100jt")
        norm_neq = normalisasi_pertanyaan("omzet != 100jt")

        # Semua bentuk harus unik dan tidak boleh tabrakan satu sama lain
        semua = [norm_gt, norm_lt, norm_gte, norm_lte, norm_eq, norm_neq]
        assert len(set(semua)) == 6
        assert "_gt_" in norm_gt
        assert "_lt_" in norm_lt
        assert "_gte_" in norm_gte
        assert "_lte_" in norm_lte
        assert "_eq_" in norm_eq
        assert "_neq_" in norm_neq

    def test_operator_aritmatika_plus_minus_persen(self):
        norm_plus = normalisasi_pertanyaan("margin + diskon")
        norm_pct = normalisasi_pertanyaan("pertumbuhan 10%")
        assert "_plus_" in norm_plus
        assert "_pct_" in norm_pct


class TestSchemaAwareFewshotFilter:
    def test_sql_relevan_dengan_skema(self):
        skema_dealer = {"penjualan", "kendaraan", "pelanggan"}
        sql_cocok = "SELECT * FROM penjualan JOIN kendaraan ON penjualan.k_id = kendaraan.id"
        sql_asing = "SELECT * FROM untt_pembelian WHERE total > 100"

        assert _sql_relevan_dengan_skema(sql_cocok, skema_dealer) is True
        assert _sql_relevan_dengan_skema(sql_asing, skema_dealer) is False

    def test_ambil_fewshot_global_menyaring_tabel_asing(self):
        class _StubPool:
            async def fetch(self, sql, *args):
                return [
                    {
                        "question": "pembelian part",
                        "sql_example": "SELECT * FROM untt_pembelian WHERE part_id = 1"
                    },
                    {
                        "question": "penjualan unit",
                        "sql_example": "SELECT * FROM penjualan WHERE harga_deal > 0"
                    }
                ]

        pool = _StubPool()
        # Tenant hanya memiliki tabel 'penjualan'
        res = _run(ambil_fewshot_global(pool, limit=2, schema_tables={"penjualan"}))
        assert len(res) == 1
        assert res[0]["pertanyaan"] == "penjualan unit"


class TestCrossTenantApiGuards:
    @pytest.fixture
    def lingkungan(self, monkeypatch):
        fake_core = FakeCorePool()
        fake_core.seed_tenant()  # tenant_id: 3, branch_code: "JKT_01"
        fake_conn = FakeTenantConn(hasil=[{"omzet": 850000000}])
        fake_mgr = FakeTenantPoolManager(fake_conn)

        from app.routers import chat as chat_router
        async def _pool():
            return fake_core
        monkeypatch.setattr(chat_router, "get_core_pool", _pool)
        monkeypatch.setattr(chat_router, "get_tenant_pool_manager", lambda: fake_mgr)

        # User hanya ditugaskan di cabang JKT_01
        app.dependency_overrides[require_user_role] = lambda: {
            "user_id": 7, "username": "user_jkt", "role": "user",
            "allowed_branches": ["JKT_01"]
        }
        client = TestClient(app)

        class Env:
            pass
        e = Env()
        e.core = fake_core
        e.client = client
        yield e
        app.dependency_overrides.clear()

    def test_user_query_cabang_lain_ditolak_403(self, lingkungan):
        resp = lingkungan.client.post("/chat/query", json={
            "question": "berapa omzet?",
            "branch_code": "BDG_01"  # Bukan anggota allowed_branches ["JKT_01"]
        })
        assert resp.status_code == 403
        assert "bukan penugasan Anda" in resp.json()["detail"]

    def test_user_history_cabang_lain_ditolak_403(self, lingkungan):
        resp = lingkungan.client.get("/chat/history?branch_code=BDG_01")
        assert resp.status_code == 403
        assert "bukan penugasan Anda" in resp.json()["detail"]

    def test_user_confirm_memory_milik_tenant_lain_ditolak_404(self, lingkungan):
        # Seed memory untuk tenant_id 99 (bukan tenant_id 3 JKT_01)
        foreign_id = 999
        lingkungan.core.sql_memory.append({
            "id": foreign_id,
            "tenant_id": 99,
            "pertanyaan_ternormalisasi": "omzet",
            "sql": "SELECT 1",
            "plan_json": None,
            "status": "pending",
            "sumber": "tier1",
            "times_used": 0,
            "last_used": None,
            "fingerprint_tabel": "penjualan",
            "ringkasan": None,
            "saran": None
        })

        resp = lingkungan.client.post("/chat/confirm-memory", json={
            "branch_code": "JKT_01",
            "memory_id": foreign_id
        })
        # Wajib 404 agar tidak membocorkan bahwa entri #999 ada di sistem
        assert resp.status_code == 404

    def test_user_reject_memory_milik_tenant_lain_ditolak_404(self, lingkungan):
        foreign_id = 888
        lingkungan.core.sql_memory.append({
            "id": foreign_id,
            "tenant_id": 99,
            "pertanyaan_ternormalisasi": "omzet",
            "sql": "SELECT 1",
            "plan_json": None,
            "status": "pending",
            "sumber": "tier1",
            "times_used": 0,
            "last_used": None,
            "fingerprint_tabel": "penjualan",
            "ringkasan": None,
            "saran": None
        })

        resp = lingkungan.client.post("/chat/reject-memory", json={
            "branch_code": "JKT_01",
            "memory_id": foreign_id
        })
        assert resp.status_code == 404


class TestTokenQuotaEnforcement:
    def test_kuota_token_habis_raise_error(self):
        class _StubPool:
            async def fetchval(self, sql, *args):
                return 100  # 100 query * 500 = 50,000 token

        pool = _StubPool()
        with pytest.raises(KuotaTokenHabis) as exc:
            _run(_cek_kuota_token(pool, "JKT_01", kuota_harian=50000))
        assert "telah mencapai batas" in str(exc.value)

    def test_kuota_token_masih_cukup_tidak_error(self):
        class _StubPool:
            async def fetchval(self, sql, *args):
                return 10  # 10 query * 500 = 5,000 token

        pool = _StubPool()
        # Kuota 50,000 token -> lolos tanpa exception
        _run(_cek_kuota_token(pool, "JKT_01", kuota_harian=50000))
