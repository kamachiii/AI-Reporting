"""Test Presenter F2.5 (bagian 1) — number check, buat_ringkasan, integrasi
pipeline (ringkasan tier1 + replay cache/self-heal) tanpa DB nyata & LLM nyata.

Strategi:
- Number check & buat_ringkasan diuji langsung (fungsi murni + fake
  llm_call_fn yang mencatat prompt).
- Pipeline memakai pola test_chat_api.py (fixture `lingkungan`: pool core
  in-memory + fake pool tenant + plan_query di-patch); `buat_ringkasan` pada
  modul chat_pipeline di-patch untuk membuktikan jalur cache (0 panggilan),
  self-heal (UPDATE kolom), dan fail-open saat presenter melempar exception.
"""
import asyncio
import copy
import json
from collections import defaultdict, deque
from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.security import require_user_role
from app.services.presenter import (
    angka_lolos, angka_melanggar, buat_ringkasan, ekstrak_angka,
    kumpulkan_angka_diizinkan)
from app.services.sql_composer import compose_sql
from conftest import SCHEMA_CONFIG_DEALER
from test_chat_api import (
    FakeCorePool, FakeTenantConn, FakeTenantPoolManager, NOW_TETAP,
    PAYLOAD_USER, RENCANA)
from test_chat_api import normalisasi_pertanyaan  # re-export helper pipeline

AI_CFG = {"api_type": "openai", "model": "m", "api_key": "sk-x",
         "temperature": 0.1}
# 2 baris data -> diizinkan {850000000, 70000000, row_count=2}
DATA = {"columns": ["omzet"], "rows": [[850000000.0], [70000000.0]],
        "row_count": 2}
JSON_VALID = json.dumps({
    "ringkasan": "Omzet bulan ini Rp850.000.000 dari 2 baris data.",
    "saran": ["omzet bulan lalu?", "omzet per sales?"]})


def _run(coro):
    return asyncio.run(coro)


def _fake_llm(outputs, catatan):
    """llm_call_fn palsu: outputs dipakai berurutan (terakhir berulang);
    setiap panggilan dicatat {system, user} untuk audit prompt."""
    async def llm(system, user, ai_config):
        catatan.append({"system": system, "user": user})
        return outputs[min(len(catatan) - 1, len(outputs) - 1)]
    return llm


# ===========================================================================
# Number check — ekstraksi angka id-ID + keanggotaan himpunan diizinkan
# ===========================================================================
class TestEkstrakAngka:
    @pytest.mark.parametrize("teks,diharapkan", [
        ("Omzet Rp73.708", [73708.0]),          # titik ribuan
        ("1.234.567 unit", [1234567.0]),        # ribuan berlapis
        ("naik 3,5 persen", [3.5]),             # koma desimal
        ("rasio 3.14", [3.14]),                 # "3.14" tetap desimal
        ("1.234,56 liter", [1234.56]),          # ribuan + desimal koma
        ("margin 12%", [12.0]),                 # persen
        ("margin 12,5%", [12.5]),               # persen desimal koma
        ("total 7 unit", [7.0]),                # integer polos
        ("tanpa angka", []),                    # tidak ada angka
        ("", []),                               # teks kosong
    ])
    def test_ekstraksi_id_id(self, teks, diharapkan):
        assert ekstrak_angka(teks) == diharapkan


class TestAngkaLolos:
    def test_int_cocok(self):
        assert angka_lolos("ada 7 unit", [7]) is True
        assert angka_lolos("ada 8 unit", [7]) is False

    def test_desimal_koma_vs_nilai_data(self):
        # ringkasan "3,5" == 3.5 pada data
        assert angka_lolos("kenaikan 3,5", [3.5]) is True
        assert angka_lolos("kenaikan 3,5", [3.4]) is False

    def test_ribuan_titik_diterima_untuk_nilai_int(self):
        # bukti utama: "73.708" pada teks == 73708 pada data
        assert angka_lolos("Omzet Rp73.708", [73708]) is True
        assert angka_melanggar("Omzet Rp73.708", [73708]) == []

    def test_persen_dari_data(self):
        assert angka_lolos("margin 12%", [12]) is True
        assert angka_lolos("margin 12,5%", [12.5]) is True

    def test_angka_dari_pertanyaan_diizinkan(self):
        diizinkan = kumpulkan_angka_diizinkan(
            "omzet tahun 2026?", [[850000000.0]], 1)
        assert angka_lolos("omzet tahun 2026 mencapai Rp850.000.000",
                           diizinkan) is True
        # tanpa pertanyaan, 2026 adalah karangan -> ditolak
        diizinkan_tanpa = kumpulkan_angka_diizinkan(
            "omzet?", [[850000000.0]], 1)
        assert angka_lolos("omzet tahun 2026 mencapai Rp850.000.000",
                           diizinkan_tanpa) is False

    def test_angka_karangan_ditolak(self):
        diizinkan = kumpulkan_angka_diizinkan(
            "omzet bulan ini?", [[73708.0]], 1)
        assert angka_lolos("Omzet Rp75.000", diizinkan) is False
        assert angka_melanggar("Omzet Rp75.000", diizinkan) == [75000.0]

    def test_juta_tidak_diekspansi_ditolak(self):
        # "1,5 juta" -> 1.5; data 1.500.000 -> 1.5 TIDAK diizinkan
        diizinkan = kumpulkan_angka_diizinkan(
            "omzet bulan ini?", [[1500000.0]], 1)
        assert angka_lolos("omzet 1,5 juta", diizinkan) is False
        # penulisan lengkap yang benar lolos
        assert angka_lolos("omzet Rp1.500.000", diizinkan) is True

    def test_3_14_tetap_desimal(self):
        # 3.14 diekstrak 3.14 (bukan 314 ribuan) -> cocok data 3.14
        assert ekstrak_angka("rasio 3.14") == [3.14]
        assert angka_lolos("rasio 3.14", [3.14]) is True
        assert angka_lolos("rasio 3.14", [314]) is False

    def test_row_count_dan_semua_nilai_rows_diizinkan(self):
        diizinkan = kumpulkan_angka_diizinkan(
            "berapa?", [[1.0, 2.0], [3.5]], 2)
        assert angka_lolos("2 baris, nilai 1, 2, dan 3,5", diizinkan) is True

    def test_diizinkan_tak_valid_diabaikan(self):
        # elemen non-numerik pada himpunan diizinkan tidak memicu error
        assert angka_lolos("ada 7 unit", [None, "abc", 7]) is True


# ===========================================================================
# buat_ringkasan — fake LLM (retry, number check, fail-open)
# ===========================================================================
class TestBuatRingkasan:
    def _panggil(self, outputs, catatan_llm=None, *, question="omzet bulan ini?",
                 data=None, ai_config=AI_CFG, error=None):
        catatan = catatan_llm if catatan_llm is not None else []

        async def llm(system, user, ai_cfg):
            if error is not None:
                raise error
            catatan.append({"system": system, "user": user})
            return outputs[min(len(catatan) - 1, len(outputs) - 1)]

        d = data or DATA
        return _run(buat_ringkasan(
            question, d["columns"], d["rows"], d["row_count"], ai_config,
            llm_call_fn=llm))

    def test_valid_metode_llm(self):
        catatan = []
        hasil = self._panggil([JSON_VALID], catatan)
        assert hasil == {"ringkasan": "Omzet bulan ini Rp850.000.000 dari 2 "
                                     "baris data.",
                         "saran": ["omzet bulan lalu?", "omzet per sales?"],
                         "metode": "llm"}
        assert len(catatan) == 1  # tanpa retry
        # prompt memuat pertanyaan, kolom, data, dan row_count
        assert "omzet bulan ini?" in catatan[0]["user"]
        assert "omzet" in catatan[0]["user"] and "TOTAL BARIS: 2" \
            in catatan[0]["user"]
        assert "850000000.0" in catatan[0]["user"]
        # system prompt: batas kalimat + larangan menyingkat angka
        assert "MAKSIMAL 2 kalimat" in catatan[0]["system"]
        assert "WAJIB PERSIS" in catatan[0]["system"]

    def test_json_rusak_retry_sukses(self):
        catatan = []
        hasil = self._panggil(["ini bukan json {{{", JSON_VALID], catatan)
        assert hasil["metode"] == "llm"
        assert hasil["ringkasan"].startswith("Omzet bulan ini")
        assert len(catatan) == 2  # 1 panggilan + 1 retry
        # retry membawa umpan balik error validator
        assert "PERCOBAAN SEBELUMNYA DITOLAK" in catatan[1]["user"]

    def test_angka_karangan_retry_dan_tetap_gagal_template(self):
        json_jahat = json.dumps({
            "ringkasan": "Omzet bulan ini Rp75.000.000.", "saran": ["s1"]})
        catatan = []
        hasil = self._panggil([json_jahat, json_jahat], catatan)
        # ringkasan yang gagal number check TIDAK pernah dikembalikan
        assert hasil == {"ringkasan": None, "saran": [], "metode": "template"}
        assert len(catatan) == 2  # tepat 1 retry
        # umpan balik retry MENYEBUT angka pelanggar
        assert "TIDAK berasal dari data" in catatan[1]["user"]
        assert "75000000" in catatan[1]["user"]

    def test_angka_karangan_retry_lalu_lolos(self):
        json_jahat = json.dumps({
            "ringkasan": "Omzet bulan ini Rp75.000.000.", "saran": []})
        catatan = []
        hasil = self._panggil([json_jahat, JSON_VALID], catatan)
        assert hasil["metode"] == "llm"
        assert hasil["ringkasan"] == "Omzet bulan ini Rp850.000.000 dari 2 " \
                                     "baris data."

    def test_rows_kosong_skip_tanpa_llm(self):
        catatan = []
        hasil = self._panggil([JSON_VALID], catatan,
                              data={"columns": ["omzet"], "rows": [],
                                    "row_count": 0})
        assert hasil == {"ringkasan": None, "saran": [], "metode": "template"}
        assert catatan == []  # LLM tidak dipanggil sama sekali

    def test_1x1_numerik_template_tanpa_llm(self):
        catatan = []
        hasil = self._panggil(
            [JSON_VALID], catatan,
            data={"columns": ["omzet"], "rows": [[850000000.0]],
                  "row_count": 1})
        assert hasil == {"ringkasan": "Hasil: 850000000.", "saran": [],
                         "metode": "template"}
        assert catatan == []
        # Decimal tampil apa adanya (persis dari data, tanpa konversi float)
        hasil_d = self._panggil(
            [JSON_VALID], [],
            data={"columns": ["omzet"], "rows": [[Decimal("73.708")]],
                  "row_count": 1})
        assert hasil_d["ringkasan"] == "Hasil: 73.708."

    def test_1x1_non_numerik_dengan_ai_config_none_tanpa_llm(self):
        # nilai teks bukan kasus trivial; ai_config None -> tanpa LLM -> None
        catatan = []
        hasil = self._panggil(
            [JSON_VALID], catatan, ai_config=None,
            data={"columns": ["status"], "rows": [["lunas"]],
                  "row_count": 1})
        assert hasil == {"ringkasan": None, "saran": [], "metode": "template"}
        assert catatan == []

    def test_saran_lebih_dari_3_dipotong_dan_kosong_dibuang(self):
        json_banyak = json.dumps({
            "ringkasan": "Omzet bulan ini Rp850.000.000 dari 2 baris data.",
            "saran": ["a", "  ", "", "b", "c", "d", None, 5]})
        hasil = self._panggil([json_banyak])
        assert hasil["saran"] == ["a", "b", "c"]  # maks 3, kosong dibuang

    def test_llm_exception_fail_open_template(self):
        from app.services.query_planner import PlanningError
        catatan = []
        hasil = self._panggil([], catatan, error=PlanningError("gateway down"))
        assert hasil == {"ringkasan": None, "saran": [], "metode": "template"}
        assert catatan == []  # exception sebelum pencatatan output

    def test_parse_gagal_dua_kali_template(self):
        catatan = []
        hasil = self._panggil(["aaa", "bbb"], catatan)
        assert hasil == {"ringkasan": None, "saran": [], "metode": "template"}
        assert len(catatan) == 2

    def test_prompt_maks_20_baris_pertama(self):
        rows = [[float(i)] for i in range(25)]  # 0..24
        # ringkasan memakai angka dari data (25 = row_count, 24 = nilai)
        json_data = json.dumps({
            "ringkasan": "Ada 25 baris data, nilai teratas 24.",
            "saran": ["lihat baris lain?"]})
        catatan = []
        hasil = self._panggil([json_data], catatan,
                              data={"columns": ["id"], "rows": rows,
                                    "row_count": 25})
        assert hasil["metode"] == "llm"
        # hanya 20 baris pertama di prompt: "[19.0]" ada, "[20.0]" tidak
        assert "[19.0]" in catatan[0]["user"]
        assert "[20.0]" not in catatan[0]["user"]
        assert "25 baris total" in catatan[0]["user"]
        assert "TOTAL BARIS: 25" in catatan[0]["user"]


# ===========================================================================
# Pipeline — pola test_chat_api.py (ringkasan pada tier1 & replay)
# ===========================================================================
def _post(client, question="omzet bulan ini", branch="JKT_01"):
    return client.post("/chat/query", json={"question": question,
                                            "branch_code": branch})


@pytest.fixture
def lingkungan(monkeypatch):
    from app.main import app
    from app.routers import chat as chat_router
    from app.services import chat_pipeline

    fake_core = FakeCorePool()
    fake_core.seed_tenant()
    conn = FakeTenantConn(hasil=[(Decimal("850000000"),)])
    fake_tpm = FakeTenantPoolManager(conn)
    planner_catatan = []

    async def _pool():
        return fake_core

    async def fake_plan_query(question, schema_config, kb, ai_config,
                              llm_call_fn=None):
        planner_catatan.append({"question": question})
        return copy.deepcopy(RENCANA)

    monkeypatch.setattr(chat_router, "get_core_pool", _pool)
    monkeypatch.setattr(chat_router, "get_tenant_pool_manager",
                        lambda: fake_tpm)
    monkeypatch.setattr(chat_router, "_chat_calls", defaultdict(deque))
    monkeypatch.setattr(chat_pipeline, "plan_query", fake_plan_query)

    app.dependency_overrides[require_user_role] = lambda: dict(PAYLOAD_USER)
    client = TestClient(app)

    class Lingkungan:
        pass
    env = Lingkungan()
    env.mp = monkeypatch  # dipakai test mem-patch buat_ringkasan
    env.client = client
    env.core = fake_core
    env.conn = conn
    env.tpm = fake_tpm
    env.planner_catatan = planner_catatan
    env.chat_pipeline = chat_pipeline
    yield env
    app.dependency_overrides.clear()


def _pasang_presenter(lingkungan, hasil=None, error=None):
    """Patch chat_pipeline.buat_ringkasan; kembalikan catatan pemanggilan."""
    catatan = []

    async def fake_presenter(question, columns, rows, row_count, ai_config,
                             llm_call_fn=None):
        catatan.append({"question": question, "rows": rows,
                        "ai_config": ai_config})
        if error is not None:
            raise error
        return dict(hasil)

    lingkungan.mp.setattr(lingkungan.chat_pipeline, "buat_ringkasan",
                          fake_presenter)
    return catatan


def _seed_memory(lingkungan, **kwargs):
    """Seed entri memory approved; kembalikan baris memory-nya."""
    composed = compose_sql(RENCANA, SCHEMA_CONFIG_DEALER, now=NOW_TETAP)
    lingkungan.core.seed_memory(
        q_norm=normalisasi_pertanyaan("omzet bulan ini"),
        sql=composed["sql"], plan_json=json.dumps(RENCANA), **kwargs)
    return lingkungan.core.sql_memory[-1]


class TestPipelineRingkasan:
    def test_tier1_response_memuat_ringkasan_saran_tersimpan_memory(
            self, lingkungan):
        lingkungan.core.seed_config_global()
        catatan = _pasang_presenter(lingkungan, hasil={
            "ringkasan": "Omzet Rp850.000.000.", "saran": ["a", "b"],
            "metode": "llm"})
        resp = _post(lingkungan.client)
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "tier1"
        assert data["ringkasan"] == "Omzet Rp850.000.000."
        assert data["saran"] == ["a", "b"]
        assert data["metode"] == "llm"
        # presenter menerima ai_config ter-resolve (api_key terdekripsi)
        assert catatan[0]["ai_config"]["api_key"] == "sk-test"
        # upsert sql_memory menyertakan ringkasan + saran
        mem = lingkungan.core.sql_memory
        assert mem[0]["ringkasan"] == "Omzet Rp850.000.000."
        assert json.loads(mem[0]["saran"]) == ["a", "b"]
        # pesan assistant (conversation + history) memuat field F2.5
        asisten = [m for m in lingkungan.core.messages
                   if m["role"] == "assistant"][0]
        pesan = json.loads(asisten["content"])
        assert pesan["ringkasan"] == "Omzet Rp850.000.000."
        assert pesan["saran"] == ["a", "b"]

    def test_tier1_rows_1x1_template_asli_tanpa_llm(self, lingkungan):
        # rows 1x1 numerik -> presenter ASLI memberi template tanpa LLM
        lingkungan.core.seed_config_global()
        resp = _post(lingkungan.client)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ringkasan"] == "Hasil: 850000000."  # float integral
        assert data["metode"] == "template"
        assert lingkungan.core.sql_memory[0]["ringkasan"] == \
            "Hasil: 850000000."

    def test_replay_dengan_ringkasan_tersimpan_metode_cache_tanpa_llm(
            self, lingkungan):
        _seed_memory(
            lingkungan, ringkasan="Omzet bulan ini Rp850.000.000.",
            saran=json.dumps(["omzet minggu ini?", "omzet bulan lalu?"]))
        # presenter di-patch agar MENYALA bila dipanggil — bukti cache 0 LLM
        catatan = _pasang_presenter(lingkungan, hasil={
            "ringkasan": "X", "saran": [], "metode": "llm"})
        resp = _post(lingkungan.client, question="OMZET BULAN INI!!!")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "memory" and data["confidence"] == "A"
        assert data["metode"] == "cache"
        assert data["ringkasan"] == "Omzet bulan ini Rp850.000.000."
        assert data["saran"] == ["omzet minggu ini?", "omzet bulan lalu?"]
        assert catatan == []            # presenter tidak pernah dipanggil
        assert lingkungan.planner_catatan == []  # dan planner juga tidak
        assert lingkungan.core.sql_memory[0]["times_used"] == 1

    def test_replay_tanpa_ringkasan_self_heal_update(self, lingkungan):
        entri = _seed_memory(lingkungan)  # ringkasan NULL
        assert entri["ringkasan"] is None
        lingkungan.core.seed_config_global()  # self-heal butuh ai_config
        _pasang_presenter(lingkungan, hasil={
            "ringkasan": "Omzet bulan ini Rp850.000.000.",
            "saran": ["s1", "s2"], "metode": "template"})
        resp = _post(lingkungan.client)
        assert resp.status_code == 200
        data = resp.json()
        assert data["metode"] == "template"  # metode dari presenter
        assert data["ringkasan"] == "Omzet bulan ini Rp850.000.000."
        # kolom di baris memory itu ter-UPDATE (replay berikutnya = cache)
        assert entri["ringkasan"] == "Omzet bulan ini Rp850.000.000."
        assert json.loads(entri["saran"]) == ["s1", "s2"]

    def test_replay_self_heal_tanpa_ai_config_tetap_200(self, lingkungan):
        # ringkasan NULL + tidak ada config AI -> tanpa LLM; rows 1x1 tetap
        # dapat template asli dari presenter
        _seed_memory(lingkungan)
        resp = _post(lingkungan.client)
        assert resp.status_code == 200
        data = resp.json()
        assert data["metode"] == "template"
        assert data["ringkasan"] == "Hasil: 850000000."
        assert lingkungan.core.sql_memory[0]["ringkasan"] == \
            "Hasil: 850000000."

    def test_presenter_throw_tier1_200_tanpa_ringkasan(self, lingkungan):
        lingkungan.core.seed_config_global()
        _pasang_presenter(lingkungan, error=RuntimeError("LLM meledak"))
        resp = _post(lingkungan.client)
        assert resp.status_code == 200  # jawaban tetap sukses
        data = resp.json()
        assert data["ringkasan"] is None
        assert data["saran"] == []
        assert data["rows"] == [[850000000.0]]  # jawaban data utuh
        assert lingkungan.core.sql_memory[0]["ringkasan"] is None

    def test_presenter_throw_replay_200_tanpa_ringkasan(self, lingkungan):
        _seed_memory(lingkungan)
        lingkungan.core.seed_config_global()
        _pasang_presenter(lingkungan, error=RuntimeError("LLM meledak"))
        resp = _post(lingkungan.client)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ringkasan"] is None and data["saran"] == []
        assert data["source"] == "memory"
