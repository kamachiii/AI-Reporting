"""Test query_planner (F3) — LLM panggilan #1 tanpa jaringan nyata.

`llm_call_fn` di-inject (fake) untuk semua skenario; resolusi ai_config diuji
lewat fake core pool. pytest-asyncio tidak tersedia — asyncio.run.
"""
import asyncio
import json

import pytest

try:
    from app.core.security import encrypt_credential
    from app.services.query_planner import (
        AIConfigError, PlanningError, build_user_prompt, plan_query,
        resolve_ai_config, _buang_pembungkus)
    HAS_PLANNER = True
except ImportError:
    HAS_PLANNER = False

from conftest import SCHEMA_CONFIG_DEALER

RENCANA_VALID = {
    "tables": ["penjualan"],
    "columns": [{"agg": "SUM", "column": "penjualan.harga_deal",
                 "alias": "omzet"}],
    "time_range": {"field": "penjualan.tanggal", "preset": "this_month"},
}


def _run(coro):
    return asyncio.run(coro)


def _fake_llm(respon_iter):
    """Fake llm_call_fn: keluarkan respons berurutan; catat panggilan."""
    panggilan = []

    async def llm(system, user, ai_config):
        panggilan.append({"system": system, "user": user, "cfg": ai_config})
        return respon_iter.pop(0)
    return llm, panggilan


KB_MIN = {"glossary": [{"istilah": "omzet", "arti": "SUM(penjualan.harga_deal)"}],
          "catatan_kolom": {}, "nilai_map": {}, "contoh_tanya": [],
          "tabel_dilarang": []}


@pytest.mark.skipif(not HAS_PLANNER, reason="query_planner belum ada")
class TestPlanQuery:
    def test_sukses_menghasilkan_clean_plan(self):
        llm, panggilan = _fake_llm([json.dumps(RENCANA_VALID)])
        plan = _run(plan_query("omzet bulan ini", SCHEMA_CONFIG_DEALER, KB_MIN,
                               {"model": "m"}, llm_call_fn=llm))
        assert plan["tables"] == ["penjualan"]
        assert plan["columns"][0]["agg"] == "SUM"
        assert len(panggilan) == 1
        # prompt memuat skema + KB + pertanyaan
        assert "penjualan" in panggilan[0]["user"]
        assert "omzet" in panggilan[0]["user"]
        assert "omzet bulan ini" in panggilan[0]["user"]

    def test_json_rusak_retry_lalu_sukses(self):
        llm, panggilan = _fake_llm(["ini bukan json {", json.dumps(RENCANA_VALID)])
        plan = _run(plan_query("omzet", SCHEMA_CONFIG_DEALER, KB_MIN,
                               {"model": "m"}, llm_call_fn=llm))
        assert plan["tables"] == ["penjualan"]
        assert len(panggilan) == 2  # 1x retry
        # feedback error dimasukkan ke prompt kedua
        assert "DITOLAK VALIDATOR" in panggilan[1]["user"]

    def test_json_rusak_dua_kali_planning_error(self):
        llm, panggilan = _fake_llm(["salah", "tetap salah"])
        with pytest.raises(PlanningError):
            _run(plan_query("omzet", SCHEMA_CONFIG_DEALER, KB_MIN,
                            {"model": "m"}, llm_call_fn=llm))
        assert len(panggilan) == 2  # tidak lebih dari 1x retry

    def test_plan_tidak_valid_dua_kali_planning_error(self):
        # JSON sah tapi melanggar kontrak (tabel asing) dua kali
        jahat = json.dumps({"tables": ["stok_gudang"], "columns": ["a.b"]})
        llm, _ = _fake_llm([jahat, jahat])
        with pytest.raises(PlanningError) as exc:
            _run(plan_query("omzet", SCHEMA_CONFIG_DEALER, KB_MIN,
                            {"model": "m"}, llm_call_fn=llm))
        assert "tidak valid" in str(exc.value)

    def test_retry_pesan_feedback_berisi_alasan_validator(self):
        llm, panggilan = _fake_llm(
            [json.dumps({"tables": ["tabel_asing"], "columns": ["x.y"]}),
             json.dumps(RENCANA_VALID)])
        _run(plan_query("omzet", SCHEMA_CONFIG_DEALER, KB_MIN,
                        {"model": "m"}, llm_call_fn=llm))
        assert "tabel_asing" in panggilan[1]["user"]

    def test_pembungkus_code_fence_dibuang(self):
        teks = "```json\n" + json.dumps(RENCANA_VALID) + "\n```"
        assert _buang_pembungkus(teks).startswith("{")
        llm, _ = _fake_llm([teks])
        plan = _run(plan_query("omzet", SCHEMA_CONFIG_DEALER, KB_MIN,
                               {"model": "m"}, llm_call_fn=llm))
        assert plan["tables"] == ["penjualan"]

    def test_pembungkus_prose_dipotong(self):
        teks = "Berikut rencananya ya: {" + '"tables": ["penjualan"], ' \
               '"columns": ["penjualan.tanggal"]' + "} semoga membantu"
        plan = _run(plan_query("omzet", SCHEMA_CONFIG_DEALER, KB_MIN,
                               {"model": "m"}, llm_call_fn=_fake_llm([teks])[0]))
        assert plan["tables"] == ["penjualan"]

    def test_llm_gagal_jaringan_planning_error(self):
        async def llm_gagal(system, user, ai_config):
            raise ConnectionError("gateway down")
        # exception arbitrer dari llm_call_fn dibiarkan naik (bukan plan_query
        # yang bertanggung jawab); default llm memetakannya ke PlanningError
        with pytest.raises(ConnectionError):
            _run(plan_query("omzet", SCHEMA_CONFIG_DEALER, KB_MIN,
                            {"model": "m"}, llm_call_fn=llm_gagal))


@pytest.mark.skipif(not HAS_PLANNER, reason="query_planner belum ada")
class TestResolveAIConfig:
    class FakePool:
        def __init__(self, baris):
            self.baris = baris  # list of (scope, target_id, dict row)

        async def fetchrow(self, sql, scope, target):
            for s, t, row in self.baris:
                if s == scope and t == target:
                    return dict(row)
            return None

    def _row(self, scope, target, key="raiserkunci"):
        return (scope, target, {
            "id": 1, "scope": scope, "target_id": target, "provider": "p",
            "model": "model-x", "api_key": encrypt_credential(key),
            "temperature": 0.1, "api_type": "openai", "base_url": ""})

    def test_user_prioritas_tinggi(self):
        pool = self.FakePool([
            self._row("global", ""),
            self._row("tenant", "JKT_01", key="k-tenant"),
            self._row("user", "user_jkt", key="k-user"),
        ])
        cfg = _run(resolve_ai_config(pool, "user_jkt", "JKT_01"))
        assert cfg["api_key"] == "k-user"  # didekripsi

    def test_fallback_tenant_lalu_global(self):
        pool = self.FakePool([self._row("global", "", key="k-global"),
                              self._row("tenant", "JKT_01", key="k-tenant")])
        assert _run(resolve_ai_config(pool, "user_jkt", "JKT_01"))["api_key"] == "k-tenant"
        pool2 = self.FakePool([self._row("global", "", key="k-global")])
        assert _run(resolve_ai_config(pool2, "user_jkt", "JKT_01"))["api_key"] == "k-global"

    def test_kosong_ada_error(self):
        pool = self.FakePool([])
        with pytest.raises(AIConfigError) as exc:
            _run(resolve_ai_config(pool, "user_jkt", "JKT_01"))
        assert "belum dikonfigurasi" in str(exc.value)

    def test_api_key_rusak_error_jelas(self):
        baris = ("user", "user_jkt", {
            "id": 1, "scope": "user", "target_id": "user_jkt",
            "provider": "p", "model": "m", "api_key": "bukan-fernet",
            "temperature": 0.1, "api_type": "openai", "base_url": ""})
        with pytest.raises(AIConfigError) as exc:
            _run(resolve_ai_config(self.FakePool([baris]), "user_jkt", "JKT_01"))
        assert "FERNET_KEY" in str(exc.value)

    def test_api_key_kosong_error(self):
        baris = ("global", "", {
            "id": 1, "scope": "global", "target_id": "", "provider": "p",
            "model": "m", "api_key": None, "temperature": 0.1,
            "api_type": "openai", "base_url": ""})
        with pytest.raises(AIConfigError):
            _run(resolve_ai_config(self.FakePool([baris]), "user_jkt", "JKT_01"))


@pytest.mark.skipif(not HAS_PLANNER, reason="query_planner belum ada")
class TestUserPrompt:
    def test_kb_dan_fk_masuk_prompt(self):
        prompt = build_user_prompt("berapa omzet?", SCHEMA_CONFIG_DEALER, KB_MIN)
        assert "foreign_keys" in prompt
        assert "glossary" in prompt
        assert "SUM(penjualan.harga_deal)" in prompt
        assert "berapa omzet?" in prompt

    def test_tipe_kolom_masuk_prompt(self):
        # format padat: "nama:tipe" dalam satu string (tipe umum disingkat)
        prompt = build_user_prompt("x", SCHEMA_CONFIG_DEALER, KB_MIN)
        assert "harga_deal:int8" in prompt  # 'bigint' disingkat
        assert "nomor_rangka:varchar" in prompt  # 'character varying' disingkat

    def test_fk_format_padat(self):
        prompt = build_user_prompt("x", SCHEMA_CONFIG_DEALER, KB_MIN)
        assert "pelanggan_id -> pelanggan.id" in prompt
        assert "kendaraan_id -> kendaraan.id" in prompt

    def test_format_padat_bukan_array_of_objects(self):
        # columns = satu string per tabel, BUKAN array {"name","type"}
        prompt = build_user_prompt("x", SCHEMA_CONFIG_DEALER, KB_MIN)
        assert '"columns": "id:int4, nomor_rangka:varchar' in prompt
        assert '"name"' not in prompt  # bentuk lama tidak ada lagi

    def test_sample_rows_tidak_masuk_prompt(self):
        # sample_rows/primary_key/nullable dari introspeksi TIDAK diteruskan
        skema = json.loads(json.dumps(SCHEMA_CONFIG_DEALER))
        skema["tables"]["penjualan"]["sample_rows"] = [
            {"id": 1, "harga_deal": 250000000}]
        prompt = build_user_prompt("x", skema, KB_MIN)
        assert "sample_rows" not in prompt
        assert "250000000" not in prompt
        assert "primary_key" not in prompt
        assert "nullable" not in prompt
