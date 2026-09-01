"""F2.6 — Tier 2 Verified Text2SQL generator (docs v2 §1/§2/§4/§7).

Satu panggilan LLM yang memutuskan jalur sekaligus menghasilkan output:

- `{"tier": 1, "plan": {...}}` — pertanyaan yang BISA diekspresikan sebagai
  laporan standar (kontrak rencana §3c). Rencana divalidasi `validate_plan`
  lalu dikomposisi `compose_sql` DI SINI (SQL final + params siap pakai).
  Verifier penuh tetap dijalankan pipeline — jalur tier 1 dari generator
  TIDAK menyentuh koneksi DB tenant.
- `{"tier": 2, "sql": "SELECT ..."}` — long-tail (subquery/CTE/perbandingan
  kompleks). SQL mentah diverifikasi INKREMENTAL di sini via
  `query_verifier.verify_query` (gerbang #1–#5, EXPLAIN murah). Gagal ->
  feedback `gate + reason` diumpankan balik ke LLM (self-repair maks 2x,
  docs v2 §1). Habis percobaan -> `Tier2Error` dengan alasan terakhir.

Keputusan tier DIKONSUMSI router (chat_pipeline) — generator tidak pernah
mengeksekusi dan tidak pernah memutuskan apa yang dieksekusi pipeline.

Kontrak `generate_sql` (dipakai chat_pipeline):
- tier 1: {"tier": 1, "sql", "params", "plan", "attempts"} — compose sudah
  selesai, pipeline REUSE hasilnya (tidak compose dua kali).
- tier 2: {"tier": 2, "sql", "verdict", "attempts"} — `sql` adalah
  `detail["final_sql"]` bila verifier menghasilkannya (LIMIT 500 dipaksa),
  atau SQL mentah bila tidak. `verdict` = verdict ok verifier inkremental.
- kegagalan apa pun setelah `max_attempts` percobaan -> Tier2Error.

`conn_factory` adalah async callable tanpa argumen -> koneksi tenant
(kontrak yang sama dengan query_verifier; TIDAK ditutup/dikembalikan di
sini — pemilik factory yang mengelola siklus hidupnya).
"""
import json
import logging

from app.services.query_planner import (
    _buang_pembungkus, build_user_prompt, panggil_llm_default)
from app.services.query_verifier import verify_query
from app.services.sql_composer import SqlComposerError, compose_sql, validate_plan

logger = logging.getLogger(__name__)

# 1 percobaan + self-repair maks 2x (docs v2 §1: "Gagal verifikasi ->
# self-repair maks 2x (error verifier diumpankan balik)"). Pemanggil boleh
# mengecilkan (test) tetapi tidak membesarkan tanpa alasan.
MAX_ATTEMPTS_DEFAULT = 3

# Ambil maksimal 800 char output LLM saat dimasukkan ke prompt feedback
# (jaga token & hindari prompt injection berulit dari output lama) — pola
# yang sama dengan query_planner.
_MAX_FEEDBACK_OUTPUT = 800


class Tier2Error(Exception):
    """Generator Tier 2 habis percobaan (JSON rusak / plan invalid / SQL
    ditolak verifier) — pembawa alasan terakhir (dipakai pipeline untuk
    fallback Tier 1 dan pesan 502 yang jujur)."""


def _system_prompt() -> str:
    """ATURAN keras: SATU objek JSON {"tier": 1|2, ...}, tanpa teks lain."""
    return (
        "Anda adalah generator query dua tier untuk laporan database dealer "
        "mobil. Untuk SATU pertanyaan user, Anda memutuskan jalur lalu "
        "mengembalikan HANYA SATU objek JSON.\n\n"
        "ATURAN MUTLAK:\n"
        "1. Bila pertanyaan bisa diekspresikan sebagai laporan standar (satu "
        "atau beberapa tabel yang terhubung lewat foreign key, filter, "
        "agregasi, group/order/limit), kembalikan:\n"
        '   {"tier": 1, "plan": {<rencana JSON kontrak di bawah>}}\n'
        "   Aturan rencana: kolom WAJIB qualified 'tabel.kolom' dan harus ada "
        "di skema; agregasi yang boleh SUM/COUNT/AVG/MIN/MAX (field 'agg', "
        "'column', 'alias'); operator filter standar eq/neq/gt/gte/lt/lte/"
        "like/in; time_range pakai preset atau from/to ISO YYYY-MM-DD; "
        "group_by/order_by hanya kolom skema atau alias; limit 1..500; "
        "JANGAN menulis SQL di dalam rencana.\n"
        "2. Bila pertanyaan TIDAK bisa diekspresikan sebagai laporan standar "
        "(butuh subquery, CTE, perbandingan antar-agregat, komparasi kompleks "
        "antar baris/tabel), kembalikan:\n"
        '   {"tier": 2, "sql": "SELECT ..."}\n'
        "   Aturan SQL tier 2:\n"
        "   - WAJIB satu statement SELECT read-only; boleh memakai CTE "
        "non-rekursif dan subquery.\n"
        "   - HANYA tabel dan kolom yang ada pada skema yang diberikan — "
        "objek di luar skema PASTI ditolak verifier.\n"
        "   - TANPA DDL/DML (INSERT/UPDATE/DELETE/CREATE/DROP), tanpa "
        "pg_sleep/dblink/pg_read_file/fungsi administrasi apa pun, tanpa "
        "lock clause (FOR UPDATE/SHARE).\n"
        "   - Nilai tanggal ditulis literal ISO YYYY-MM-DD.\n"
        "3. HANYA kembalikan objek JSON. Tanpa markdown, tanpa penjelasan, "
        "tanpa teks lain."
    )


def _parse_output(raw: str, schema_config: dict):
    """Output LLM -> (jalur, muatan, errors).

    Returns:
        ("tier1", plan_dict, []) | ("tier2", sql_str, []) |
        (None, None, [errors]) — errors dijadikan umpan balik retry.
    """
    teks = _buang_pembungkus(raw)
    try:
        data = json.loads(teks)
    except (ValueError, TypeError) as e:
        return None, None, [f"output bukan JSON valid: {e}"]
    if not isinstance(data, dict):
        return None, None, [f"output bukan objek JSON (ditemukan: {type(data).__name__})"]

    tier = data.get("tier")
    if tier == 1:
        plan = data.get("plan")
        if not isinstance(plan, dict):
            return None, None, ["'plan' hilang atau bukan objek untuk tier 1"]
        return "tier1", plan, []
    if tier == 2:
        sql = data.get("sql")
        if not isinstance(sql, str) or not sql.strip():
            return None, None, ["'sql' hilang atau kosong untuk tier 2"]
        return "tier2", sql.strip(), []
    return None, None, [f"'tier' harus 1 atau 2 (ditemukan: {tier!r})"]


async def generate_sql(question: str, schema_config: dict, kb: dict,
                       ai_config: dict, conn_factory, llm_call_fn=None,
                       max_attempts: int = MAX_ATTEMPTS_DEFAULT,
                       now=None) -> dict:
    """Satu panggilan LLM -> keputusan tier + output sesuai jalurnya.

    Args:
        question: pertanyaan user apa adanya (bahasa alami).
        schema_config: bentuk tenants.schema_config_json (SUDAH efektif bila
            pipeline memotong allowlist — lihat _siapkan_skema_efektif).
        kb: KB ternormalisasi (parse_stored_kb); `tabel_dilarang` diteruskan
            ke verifier sebagai kb_forbidden.
        ai_config: hasil resolve_ai_config (api_key sudah didekripsi).
        conn_factory: async callable () -> koneksi tenant — dipakai gerbang
            #5 (EXPLAIN) hanya untuk SQL tier 2. Tier 1 tidak menyentuh DB.
        llm_call_fn: injectable async (system, user, ai_config) -> str;
            default panggil_llm_default.
        max_attempts: total percobaan LLM (default 3 = 1 + self-repair 2x).
        now: datetime untuk compose_sql preset waktu (kontrak F2.2; None ->
            datetime.now() di composer).

    Returns:
        dict kontrak (lihat docstring modul).

    Raises:
        Tier2Error: semua percobaan gagal — alasan terakhir dibawa.
    """
    llm = llm_call_fn or panggil_llm_default
    kb_forbidden = kb.get("tabel_dilarang") or []
    system = _system_prompt()
    user_dasar = build_user_prompt(question, schema_config, kb)

    alasan_terakhir = None
    raw_lama = None
    for percobaan in range(1, max_attempts + 1):
        user = user_dasar
        if alasan_terakhir is not None:
            # Self-repair: umpan balik alasan penolakan + output lama
            # (terpotong) — doktrin docs v2 §2 "reason dipakai sebagai umpan
            # balik self-repair Tier 2 (maks 2x)".
            user = (
                user_dasar
                + "\n\nPERCOBAAN SEBELUMNYA DITOLAK dengan alasan:\n- "
                + alasan_terakhir
                + "\nOutput sebelumnya (bila ada):\n"
                + (raw_lama or "")[:_MAX_FEEDBACK_OUTPUT]
                + "\nPerbaiki dan kembalikan HANYA objek JSON sesuai ATURAN "
                  "MUTLAK."
            )
        raw_lama = await llm(system, user, ai_config)
        jalur, muatan, errors = _parse_output(raw_lama, schema_config)

        if jalur == "tier1":
            clean, errors_val = validate_plan(muatan, schema_config)
            if errors_val:
                alasan_terakhir = "rencana tidak valid: " + "; ".join(errors_val[:5])
                continue
            try:
                composed = compose_sql(clean, schema_config, now=now)
            except SqlComposerError as e:
                alasan_terakhir = f"compose rencana gagal: {e}"
                continue
            # Verifier penuh TIDAK dijalankan di sini (kontrak §3c) — SQL
            # hasil compose nanti diverifikasi pipeline bersama jalur lama.
            return {
                "tier": 1, "sql": composed["sql"], "params": composed["params"],
                "plan": clean, "attempts": percobaan,
            }

        if jalur == "tier2":
            verdict = await verify_query(muatan, schema_config, conn_factory,
                                         kb_forbidden=kb_forbidden)
            if verdict["ok"]:
                sql = verdict["detail"].get("final_sql") or muatan
                logger.info("tier2: SQL lolos verifier pada percobaan ke-%d", percobaan)
                return {"tier": 2, "sql": sql, "verdict": verdict,
                        "attempts": percobaan}
            alasan_terakhir = (
                f"verifier menolak (gate {verdict.get('gate')}): "
                f"{verdict.get('reason')}")
            continue

        # jalur None: JSON rusak / field hilang / tier tak dikenal
        alasan_terakhir = "; ".join(errors[:5])

    raise Tier2Error(
        f"Tier 2 gagal setelah {max_attempts} percobaan: {alasan_terakhir}")
