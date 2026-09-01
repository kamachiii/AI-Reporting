"""F3 — Query Planner (LLM panggilan #1, docs v2 §1 jalur Tier 1).

Satu panggilan LLM yang mengubah pertanyaan bahasa Indonesia menjadi SATU
rencana JSON sesuai kontrak composer (PROGRES §3c). TIDAK pernah menghasilkan
SQL — SQL dibuat deterministik oleh sql_composer. Fokus LLM hanyalah memetakan
pertanyaan -> (tables, columns, filters, time_range, group_by, order_by,
limit).

Kontrak pemanggil (chat_pipeline):
- `plan_query(...)` selalu mengembalikan clean plan yang SUDAH lolos
  `sql_composer.validate_plan` (compose_sql memvalidasi ulang — murah).
- Kegagalan bentuk apa pun -> `PlanningError` (HTTP 502 di router).
- Konfigurasi AI tidak ada / rusak -> `AIConfigError` (HTTP 503 di router).

Resolusi ai_config (`resolve_ai_config`): scope user > tenant > global
(seperti halaman admin AI Configs; user scope menunjuk username, tenant scope
menunjuk branch_code, global target_id = ""). api_key didekripsi Fernet di
sini — config yang keluar dari fungsi ini siap dipakai panggil LLM.

`llm_call_fn` injectable: `async (system: str, user: str, ai_config: dict)
-> str`. Default-nya memanggil gateway OpenAI-compatible / Anthropic lewat
`build_chat_url` (pola ai_orchestrator) dengan `response_format json_object`
untuk openai. Test memakai fake tanpa jaringan.
"""
import json
import logging
import re

import httpx
from fastapi import HTTPException

from app.core.security import decrypt_credential
from app.services.ai_orchestrator import build_chat_url
from app.services.sql_composer import (
    AGGREGASI_DIIZINKAN, OPERATOR_DIIZINKAN, PRESET_WAKTU, validate_plan)

logger = logging.getLogger(__name__)

# Coba 1x (call pertama) + 1x retry dengan feedback error validator.
MAX_ATTEMPT = 2

_LLM_TIMEOUT_SECONDS = 60.0
_MAX_TOKENS_ANTHROPIC = 4096
# Ambil maksimal 800 char output LLM saat dimasukkan ke prompt feedback
# (jaga token & hindari prompt injection berulit dari output lama).
_MAX_FEEDBACK_OUTPUT = 800

_FENCE_RE = re.compile(r"```[a-zA-Z]*\s*(.*?)\s*```", re.DOTALL)


class PlanningError(Exception):
    """Rencana tidak dapat dihasilkan (output LLM rusak / gateway gagal)."""


class AIConfigError(Exception):
    """Config AI tidak tersedia (user>tenant>global) atau API key rusak."""


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
def _system_prompt() -> str:
    """ATURAN keras: HANYA rencana JSON kontrak §3c, kolom qualified."""
    ops = ", ".join(sorted(OPERATOR_DIIZINKAN))
    aggs = ", ".join(sorted(AGGREGASI_DIIZINKAN))
    presets = ", ".join(sorted(PRESET_WAKTU))
    return (
        "Anda adalah perencana query (planner) untuk laporan database dealer "
        "mobil. Tugas Anda: mengubah SATU pertanyaan bahasa Indonesia menjadi "
        "SATU rencana JSON untuk SQL composer.\n\n"
        "ATURAN MUTLAK:\n"
        "1. HANYA kembalikan objek JSON rencana. Tanpa penjelasan, tanpa "
        "markdown, tanpa teks lain.\n"
        "2. Semua referensi kolom WAJIB qualified 'tabel.kolom' (mis. "
        "'penjualan.harga_deal'); tabel harus ada di skema yang diberikan.\n"
        "3. JANGAN pernah menulis SQL, nilai literal di dalam SQL, atau "
        "komentar. Nilai filter/time_range masuk field rencana.\n"
        "4. Agregasi yang boleh: " + aggs + " (ditulis pada field 'agg', "
        "kolom agregat ditulis {\"agg\": ..., \"column\": ..., \"alias\": ...}).\n"
        "5. Operator filter yang boleh: " + ops + ".\n"
        "6. preset time_range yang boleh: " + presets + " — ATAU pakai "
        "'from'/'to' tanggal ISO format YYYY-MM-DD.\n"
        "7. alias (jika ada) hanya huruf kecil/underscore: [a-z_][a-z0-9_]*.\n"
        "8. limit bilangan bulat 1..500 (jika user tidak menyebut, biarkan "
        "default).\n"
        "9. 'group_by'/'order_by' hanya berisi kolom skema atau alias SELECT; "
        "'order_by[].dir' hanya ASC/DESC.\n\n"
        "Bentuk rencana (kontrak):\n"
        "{\n"
        '  "tables": ["penjualan", "kendaraan"],\n'
        '  "columns": ["penjualan.tanggal", {"agg": "SUM", "column": '
        '"penjualan.harga_deal", "alias": "omzet"}],\n'
        '  "filters": [{"column": "penjualan.metode_pembayaran", "op": "eq", '
        '"value": "tunai"}],\n'
        '  "time_range": {"field": "penjualan.tanggal", "preset": "this_month"},\n'
        '  "group_by": ["kendaraan.merek"],\n'
        '  "order_by": [{"by": "omzet", "dir": "DESC"}],\n'
        '  "limit": 50\n'
        "}\n"
        "Field yang tidak relevan dengan pertanyaan boleh dihilangkan "
        "(tables dan columns wajib)."
    )


# Singkatan tipe umum Postgres — HANYA untuk tampilan prompt (planner tidak
# pernah menulis tipe di rencana; validator composer/verifier tetap memakai
# schema_config penuh, bukan bentuk ringkas ini). Tipe di luar peta dilewatkan
# apa adanya.
_TIPE_SINGKAT = {
    "integer": "int4",
    "bigint": "int8",
    "smallint": "int2",
    "character varying": "varchar",
    "character": "char",
    "timestamp without time zone": "timestamp",
    "timestamp with time zone": "timestamptz",
    "time without time zone": "time",
    "double precision": "float8",
    "real": "float4",
    "boolean": "bool",
}


def _skema_ringkas(schema_config: dict) -> dict:
    """Skema tenant -> bentuk padat untuk prompt (hemat token, TPM 8000).

    Semua tabel dirender seragam (satu code path):
    - "columns"      : SATU string "nama:tipe" dipisah koma — bukan array of
                       objects; hemat ~60-70% karakter pada skema lebar
                       (763 kolom tenant nyata), planner tetap melihat SEMUA
                       nama kolom untuk bisa memilih.
    - "foreign_keys" : array string "kolom -> tabel.kolom".
    Sample rows / primary_key / nullable TIDAK disertakan — tidak dibutuhkan
    planner (nilai_map & glossary cukup untuk semantik).
    """
    ringkas: dict = {}
    for nama, tabel in (schema_config or {}).get("tables", {}).items():
        kolom = ", ".join(
            f"{c.get('name')}:{_TIPE_SINGKAT.get(c.get('type'), c.get('type'))}"
            for c in tabel.get("columns") or [])
        fk = [
            f"{fk.get('column')} -> {fk.get('references_table')}."
            f"{fk.get('references_column')}"
            for fk in tabel.get("foreign_keys") or []
        ]
        ringkas[nama] = {"columns": kolom, "foreign_keys": fk}
    return ringkas


def build_user_prompt(question: str, schema_config: dict, kb: dict) -> str:
    """Prompt user: skema tenant + KB (glossary/catatan/nilai/contoh) + tanya.

    KB dibatasi ukurannya secara alami oleh validasi admin (KB disimpan
    terkurasi), jadi disertakan utuh — glossary & contoh_tanya adalah alat
    utama mencegah salah semantik (docs v2 §4). Skema memakai bentuk padat
    `_skema_ringkas`; keterangan formatnya ditulis di header agar LLM tidak
    salah baca.
    """
    kb_bagian = {
        "glossary": kb.get("glossary", []),
        "catatan_kolom": kb.get("catatan_kolom", {}),
        "nilai_map": kb.get("nilai_map", {}),
        "contoh_tanya": kb.get("contoh_tanya", []),
    }
    return (
        "SKEMA DATABASE (JSON padat): per tabel, 'columns' = SATU string "
        "\"nama:tipe\" dipisah koma; 'foreign_keys' = \"kolom -> "
        "tabel.kolom\".\n"
        + json.dumps(_skema_ringkas(schema_config), ensure_ascii=False)
        + "\n\n"
        "KNOWLEDGE BASE TENANT (makna istilah & contoh pertanyaan):\n"
        + json.dumps(kb_bagian, ensure_ascii=False) + "\n\n"
        "PERTANYAAN USER:\n" + question.strip()
    )


# ---------------------------------------------------------------------------
# Parsing & validasi output LLM
# ---------------------------------------------------------------------------
def _buang_pembungkus(raw: str) -> str:
    """Lepas pembungkus non-JSON yang sering menyertai output LLM.

    Urutan: buang code fence ```json ...``` -> kalau masih gagal, potong dari
    '{' pertama sampai '}' terakhir (LLM kadang menambah satu kalimat pembuka).
    """
    if raw is None:
        return ""
    teks = raw.strip()
    cocok = _FENCE_RE.search(teks)
    if cocok:
        teks = cocok.group(1).strip()
    awal, akhir = teks.find("{"), teks.rfind("}")
    if awal != -1 and akhir != -1 and akhir > awal:
        teks = teks[awal:akhir + 1]
    return teks


def _parse_dan_validasi(raw: str, schema_config: dict) -> tuple[dict | None, list[str]]:
    """Output LLM -> (clean plan | None, daftar error validator)."""
    teks = _buang_pembungkus(raw)
    try:
        plan = json.loads(teks)
    except (ValueError, TypeError) as e:
        return None, [f"output bukan JSON valid: {e}"]
    clean, errors = validate_plan(plan, schema_config)
    if errors:
        return None, errors
    return clean, []


# ---------------------------------------------------------------------------
# Default LLM call (httpx, pola ai_orchestrator.build_chat_url)
# ---------------------------------------------------------------------------
async def panggil_llm_default(system: str, user: str, ai_config: dict) -> str:
    """Panggilan HTTP default ke gateway AI (openai/anthropic).

    openai: messages system+user + response_format json_object (memaksa
    output JSON murni di sisi gateway). anthropic: system terpisah + messages.
    Semua kegagalan jaringan/HTTP/konten -> PlanningError (bukan exception
    HTTP — pemetaan status dilakukan router).
    """
    api_type = (ai_config.get("api_type") or "openai").lower()
    model = ai_config.get("model")
    api_key = ai_config.get("api_key")
    temperature = ai_config.get("temperature", 0.2)

    try:
        url = build_chat_url({**ai_config, "api_type": api_type})
    except HTTPException as e:
        raise PlanningError(f"api_type tidak dikenali: {e.detail}") from e

    if api_type == "openai":
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
    else:  # anthropic
        headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01",
                   "Content-Type": "application/json"}
        payload = {
            "model": model,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "temperature": temperature,
            "max_tokens": _MAX_TOKENS_ANTHROPIC,
        }

    try:
        async with httpx.AsyncClient(timeout=_LLM_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, headers=headers, json=payload)
    except (httpx.TimeoutException, httpx.ConnectError) as e:
        raise PlanningError(f"AI gateway tidak dapat dihubungi: {e}") from e

    if resp.status_code != 200:
        raise PlanningError(
            f"AI gateway merespons {resp.status_code}: {resp.text[:200]}")

    try:
        data = resp.json()
        if api_type == "openai":
            content = data["choices"][0]["message"]["content"]
        else:
            content = data["content"][0]["text"]
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise PlanningError(f"respons gateway tidak terbaca: {e}") from e

    if not content or not str(content).strip():
        raise PlanningError("AI mengembalikan konten kosong")
    return str(content)


# ---------------------------------------------------------------------------
# Resolusi konfigurasi AI (user > tenant > global)
# ---------------------------------------------------------------------------
_SELECT_CONFIG = (
    "SELECT id, scope, target_id, provider, model, api_key, temperature, "
    "api_type, base_url FROM ai_configs WHERE scope = $1 AND target_id = $2 "
    "ORDER BY id LIMIT 1")


async def resolve_ai_config(pool, username: str, branch_code: str) -> dict:
    """Cari config AI untuk request chat ini: user > tenant > global.

    Raises:
        AIConfigError: tidak ada config sama sekali, API key kosong, atau
            API key gagal didekripsi (pesan siap ditampilkan ke user —
            HTTP 503 di router).
    """
    kandidat = (("user", username), ("tenant", branch_code), ("global", ""))
    row = None
    for scope, target in kandidat:
        row = await pool.fetchrow(_SELECT_CONFIG, scope, target)
        if row is not None:
            logger.info("planner: pakai ai_config scope '%s' (target '%s')",
                        scope, target)
            break
    if row is None:
        raise AIConfigError(
            "AI belum dikonfigurasi (tidak ada config scope user/tenant/global). "
            "Hubungi administrator.")

    cfg = dict(row)
    tersimpan = cfg.get("api_key")
    if not tersimpan:
        raise AIConfigError("Config AI ditemukan tetapi API key-nya kosong. "
                            "Hubungi administrator.")
    try:
        cfg["api_key"] = decrypt_credential(tersimpan)
    except Exception as e:
        raise AIConfigError(
            "API key tersimpan tidak dapat didekripsi (periksa FERNET_KEY).") from e
    return cfg


# ---------------------------------------------------------------------------
# plan_query — orkestrasi panggilan #1 + retry
# ---------------------------------------------------------------------------
async def plan_query(question: str, schema_config: dict, kb: dict,
                     ai_config: dict, llm_call_fn=None) -> dict:
    """Pertanyaan -> rencana JSON (clean, lolos validate_plan).

    Gagal parse/validasi pada percobaan pertama -> SATU retry dengan feedback
    error validator (reason = umpan balik, docs v2 §2). Tetap gagal ->
    PlanningError.

    Args:
        question: pertanyaan user apa adanya (belum dinormalisasi — konteks
            bahasa alami lebih kaya untuk LLM).
        schema_config: bentuk tenants.schema_config_json.
        kb: KB ternormalisasi (parse_stored_kb).
        ai_config: hasil resolve_ai_config (api_key sudah didekripsi).
        llm_call_fn: injectable async (system, user, ai_config) -> str;
            default panggil_llm_default.
    """
    llm = llm_call_fn or panggil_llm_default
    system = _system_prompt()
    user = build_user_prompt(question, schema_config, kb)

    raw = await llm(system, user, ai_config)
    plan, errors = _parse_dan_validasi(raw, schema_config)
    if plan is not None:
        return plan

    # --- retry 1x: umpan balik error validator + output lama (terpotong) ---
    feedback = "\n".join(f"- {e}" for e in errors[:10])
    user2 = (
        user + "\n\nPERCOBAAN SEBELUMNYA DITOLAK VALIDATOR dengan alasan:\n"
        + feedback
        + "\nOutput sebelumnya (bila ada):\n"
        + (raw or "")[:_MAX_FEEDBACK_OUTPUT]
        + "\nPerbaiki dan kembalikan HANYA rencana JSON yang valid sesuai "
          "ATURAN MUTLAK."
    )
    raw2 = await llm(system, user2, ai_config)
    plan2, errors2 = _parse_dan_validasi(raw2, schema_config)
    if plan2 is not None:
        logger.info("planner: lolos pada retry ke-1 (errors awal: %d)", len(errors))
        return plan2

    ringkas = "; ".join(errors2[:5])
    raise PlanningError(f"rencana dari LLM tidak valid setelah retry: {ringkas}")
