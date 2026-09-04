"""Test muat_kb_gabungan (F3) — penggabungan KB global dan per-tenant.

Memastikan:
- Aturan merge: tenant menang saat konflik (glossary, catatan_kolom, nilai_map)
- Filtering tabel skema untuk text global "Table X columns: ..."
- contoh_tanya: tenant di depan, global di belakang
- tabel_dilarang, tabel_diizinkan, kolom_dikecualikan HANYA dari tenant
- Graceful degradation saat query global_knowledge_base gagal/tabel tidak ada.
"""
import asyncio
import pytest

from app.services.knowledge_base import muat_kb_gabungan


def _run(coro):
    return asyncio.run(coro)


class _StubPool:
    def __init__(self, rows=None, raise_exc=None):
        self.rows = rows or []
        self.raise_exc = raise_exc

    async def fetch(self, sql, *args):
        if self.raise_exc:
            raise self.raise_exc
        return self.rows


class TestKbMerger:
    def test_merge_glossary_tenant_menang_jika_konflik(self):
        global_rows = [
            {"kind": "text", "content": "omzet maps to total seluruh penjualan", "question": None, "sql_example": None},
            {"kind": "text", "content": "diskon maps to potongan harga global", "question": None, "sql_example": None},
        ]
        tenant_kb = {
            "glossary": [
                {"istilah": "omzet", "arti": "SUM(penjualan.harga_deal)"}
            ]
        }
        pool = _StubPool(rows=global_rows)
        merged = _run(muat_kb_gabungan(pool, tenant_kb, {"penjualan"}))

        # omzet dari tenant menang, diskon dari global masuk
        glossary_map = {item["istilah"]: item["arti"] for item in merged["glossary"]}
        assert glossary_map["omzet"] == "SUM(penjualan.harga_deal)"
        assert "potongan harga global" in glossary_map["diskon"]

    def test_filter_tabel_global_sesuai_skema(self):
        global_rows = [
            {"kind": "text", "content": "Table glbm_customer columns: id, name, phone", "question": None, "sql_example": None},
            {"kind": "text", "content": "Table untt_pembelian columns: id, no_invoice, total", "question": None, "sql_example": None},
        ]
        tenant_kb = {
            "catatan_kolom": {
                "penjualan.harga_deal": "Harga deal"
            }
        }
        pool = _StubPool(rows=global_rows)
        # Hanya glbm_customer yang ada di skema tenant
        merged = _run(muat_kb_gabungan(pool, tenant_kb, {"glbm_customer", "penjualan"}))

        assert "glbm_customer" in merged["catatan_kolom"]
        assert "untt_pembelian" not in merged["catatan_kolom"]
        assert merged["catatan_kolom"]["penjualan.harga_deal"] == "Harga deal"

    def test_contoh_tanya_gabungan_tenant_di_depan(self):
        global_rows = [
            {"kind": "example", "content": "sales data", "question": "sales data for 3 month", "sql_example": "SELECT * FROM untt_penjualan"},
        ]
        tenant_kb = {
            "contoh_tanya": [
                {"tanya": "omzet bulan ini", "agg": "SUM(harga_deal)"}
            ]
        }
        pool = _StubPool(rows=global_rows)
        merged = _run(muat_kb_gabungan(pool, tenant_kb, set()))

        assert len(merged["contoh_tanya"]) == 2
        assert merged["contoh_tanya"][0]["tanya"] == "omzet bulan ini"
        assert merged["contoh_tanya"][1]["tanya"] == "sales data for 3 month"

    def test_tabel_kontrol_akses_hanya_dari_tenant(self):
        global_rows = [
            {"kind": "text", "content": "dummy text", "question": None, "sql_example": None},
        ]
        tenant_kb = {
            "tabel_dilarang": ["log_audit"],
            "tabel_diizinkan": ["penjualan"],
            "kolom_dikecualikan": ["users.password_hash"]
        }
        pool = _StubPool(rows=global_rows)
        merged = _run(muat_kb_gabungan(pool, tenant_kb, {"penjualan"}))

        assert merged["tabel_dilarang"] == ["log_audit"]
        assert merged["tabel_diizinkan"] == ["penjualan"]
        assert merged["kolom_dikecualikan"] == ["users.password_hash"]

    def test_fallback_saat_global_kb_error(self):
        pool = _StubPool(raise_exc=Exception("Table global_knowledge_base does not exist"))
        tenant_kb = {
            "glossary": [{"istilah": "omzet", "arti": "SUM(penjualan.harga_deal)"}]
        }
        merged = _run(muat_kb_gabungan(pool, tenant_kb, {"penjualan"}))

        assert len(merged["glossary"]) == 1
        assert merged["glossary"][0]["istilah"] == "omzet"
