"""F3 — Chat Pipeline: pertanyaan user -> jawaban + audit (docs v2 §1/§3).

Urutan tahap (milestone perangkuman):

1.  Normalisasi pertanyaan (lowercase + strip tanda baca, v2 §11 #2).
2.  Load tenant by branch (join tenants+db_connections) — 409 bila belum
    terhubung / nonaktif / schema_config belum diintrospeksi.
3.  SQL Memory replay: entri `approved` dengan pertanyaan ternormalisasi sama
    -> `verify_and_execute` SQL tersimpan (VERIFIER TETAP JALAN — keamanan
    tidak pernah di-skip) -> source="memory", confidence="A", times_used++.
    Params preset waktu dihitung ULANG dari plan_json (SQL replay memakai
    jendela waktu relatif "now", bukan tanggal saat SQL disetujui — docs v2
    §3). SQL hasil komposisi ulang != SQL tersimpan -> tandai 'stale'
    (invalidasi otomatis, docs v2 §3) dan anggap MISS.
4.  MISS -> planner LLM (panggilan #1) -> compose_sql (now dari pemanggil —
    TZ server) -> verify_and_execute -> source="tier1", confidence="B".
    SQL baru lolos verifier -> upsert sql_memory status 'pending' (mode auto,
    v2 §7 — tanpa antrean admin).
5.  Audit SELALU (sukses & gagal) ke audit_logs — nama kolom nyata skema:
    user_id, branch_code, prompt_text, ai_json_filter, generated_sql,
    execution_time_ms, status, error_message. plan JSON disimpan di
    ai_json_filter (warisan kolom lama filter AI — dokumentasi keputusan).
6.  Percakapan: 1 conversation per (user, branch) — pakai tabel
    conversations/messages existing; sukses = append 2 pesan (user +
    assistant). Gagal tidak menulis pesan (audit sudah mencatat).
7.  Response selalu menyertakan SQL (kejujuran UI, docs v2 §4):
    {source, confidence, sql, params, columns, rows, row_count, truncated,
    duration_ms}.

Exception service-layer -> router memetakan ke HTTP (lihat routers/chat.py):
TenantTidakAda/SkemaTidakTersedia -> 409, AIConfigError -> 503,
PlanningError/SqlComposerError -> 502, VerifierDitolak -> 422,
QueryCanceledError (timeout #6) -> 504, ExecutorError -> 500.

Semua query core DB parameterized ($1, $2, ...) — tanpa eksepsi (pelajaran
PROGRES §4). Tidak ada import FastAPI — layer service murni.
"""
import json
import logging
import re
from datetime import datetime

from app.services.knowledge_base import parse_stored_kb
from app.services.query_executor import verify_and_execute
from app.services.query_planner import AIConfigError, PlanningError, plan_query, \
    resolve_ai_config
from app.services.sql_composer import SqlComposerError, compose_sql

logger = logging.getLogger(__name__)

# --- Normalisasi pertanyaan untuk replay (keputusan v2 §11 #2: lowercase +
# strip tanda baca; kecocokan longgar, jawaban replay tetap level A karena
# entri yang di-replay wajib approved). Tanda baca diganti spasi lalu spasi
# dirapatkan — "omzet, bulan ini?" == "omzet bulan ini" == "OMZET BULAN INI".
_TANDA_BACA_RE = re.compile(r"[^\w\s]", re.UNICODE)
_SPASI_RE = re.compile(r"\s+")
_PLACEHOLDER_RE = re.compile(r"\$\d+")

_STATUS_SUCCESS = "success"
_STATUS_REJECTED = "rejected"
_STATUS_ERROR = "error"

_SOURCE_MEMORY = "memory"
_SOURCE_TIER1 = "tier1"
_CONF_A = "A"
_CONF_B = "B"


# ===========================================================================
# Exception domain (router memetakan ke HTTP)
# ===========================================================================
class TenantTidakAda(Exception):
    """Cabang belum terhubung sebagai tenant / tenant nonaktif (409)."""


class SkemaTidakTersedia(Exception):
    """Tenant terhubung tetapi schema_config_json belum diintrospeksi (409)."""


class VerifierDitolak(Exception):
    """Verifier menolak SQL (gerbang mana pun) — bawa verdict utuh (422)."""

    def __init__(self, verdict: dict):
        self.verdict = verdict
        super().__init__(verdict.get("reason") or "verifier menolak SQL")


# ===========================================================================
# Helper murni / pembacaan
# ===========================================================================
def normalisasi_pertanyaan(pertanyaan: str) -> str:
    """Lowercase + strip tanda baca + rapikan spasi (kunci replay memory)."""
    if not pertanyaan:
        return ""
    tanpa_tanda = _TANDA_BACA_RE.sub(" ", pertanyaan.lower())
    return _SPASI_RE.sub(" ", tanpa_tanda).strip()


def _parse_json_mungkin_str(raw):
    """Kolom JSONB asyncpg datang sebagai string (pool inti tanpa codec) —
    terima juga dict bila codec aktif. Rusak/None -> None (pemanggil punya
    jalur fallback, KB/skema rusak tidak boleh menjatuhkan pipeline)."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw) if isinstance(raw, str) else None
    except (ValueError, TypeError):
        return None


def _parse_schema_config(raw) -> dict:
    """schema_config_json wajib objek dengan 'tables' — syarat verifier."""
    data = _parse_json_mungkin_str(raw)
    if not isinstance(data, dict) or not data.get("tables"):
        raise SkemaTidakTersedia(
            "Skema database tenant belum tersedia. Hubungi administrator "
            "untuk menjalankan introspeksi skema.")
    return data


_SQL_TENANT = (
    "SELECT t.id AS tenant_id, t.branch_code, t.schema_config_json, "
    "       t.knowledge_base, t.is_active AS tenant_aktif, "
    "       dc.id AS db_connection_id, dc.db_host, dc.db_port, dc.db_name, "
    "       dc.db_username, dc.db_password, dc.is_active AS koneksi_aktif "
    "FROM tenants t "
    "JOIN db_connections dc ON dc.id = t.db_connection_id "
    "WHERE t.branch_code = $1")


async def resolve_tenant(core_pool, branch_code: str) -> dict:
    """Tenant + koneksi DB untuk satu cabang; tidak ada/nonaktif -> error."""
    row = await core_pool.fetchrow(_SQL_TENANT, branch_code)
    if not row:
        raise TenantTidakAda(
            f"Cabang '{branch_code}' belum terhubung ke database tenant.")
    if not row["tenant_aktif"] or not row["koneksi_aktif"]:
        raise TenantTidakAda(
            f"Database tenant untuk cabang '{branch_code}' sedang nonaktif.")
    return dict(row)


async def cari_memory_approved(core_pool, tenant_id: int, q_norm: str):
    """Entri sql_memory approved terbaik untuk pertanyaan ini (atau None)."""
    return await core_pool.fetchrow(
        "SELECT id, sql, plan_json, times_used, fingerprint_tabel "
        "FROM sql_memory "
        "WHERE tenant_id = $1 AND pertanyaan_ternormalisasi = $2 "
        "  AND status = 'approved' "
        "ORDER BY times_used DESC, last_used DESC NULLS LAST, id DESC "
        "LIMIT 1", tenant_id, q_norm)


async def tandai_memory_dipakai(core_pool, memory_id: int) -> None:
    """times_used++ + last_used (metrik memory hit rate, docs v2 §8)."""
    await core_pool.execute(
        "UPDATE sql_memory SET times_used = times_used + 1, "
        "last_used = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = $1", memory_id)


async def tandai_memory_stale(core_pool, memory_id: int) -> None:
    """Invalidasi otomatis: verifier/komposisi tidak cocok lagi (docs v2 §3)."""
    await core_pool.execute(
        "UPDATE sql_memory SET status = 'stale', "
        "updated_at = CURRENT_TIMESTAMP WHERE id = $1", memory_id)


async def simpan_memory_pending(core_pool, tenant_id: int, q_norm: str,
                                sql: str, plan: dict, sumber: str,
                                fingerprint_tabel: str | None) -> int:
    """Upsert SQL baru (lolos verifier) berstatus 'pending' (mode auto v2 §7).

    "Upsert" pada kunci (tenant_id, pertanyaan_ternormalisasi, sql): entri
    yang sudah ada diperbarui plan/fingerprints-nya TANPA menurunkan status
    (approved tetap approved — menaikkan boleh, menurunkan tidak). Entri baru
    -> INSERT status 'pending'; konfirmasi user/admin yang mengangkat ke
    'approved' (di luar jalur ini).
    """
    lama = await core_pool.fetchrow(
        "SELECT id FROM sql_memory WHERE tenant_id = $1 AND "
        "pertanyaan_ternormalisasi = $2 AND sql = $3 LIMIT 1",
        tenant_id, q_norm, sql)
    if lama:
        await core_pool.execute(
            "UPDATE sql_memory SET plan_json = $1, sumber = $2, "
            "fingerprint_tabel = $3, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = $4",
            json.dumps(plan, ensure_ascii=False), sumber, fingerprint_tabel,
            lama["id"])
        return lama["id"]
    return await core_pool.fetchval(
        "INSERT INTO sql_memory (tenant_id, pertanyaan_ternormalisasi, sql, "
        "plan_json, status, sumber, fingerprint_tabel) "
        "VALUES ($1, $2, $3, $4, 'pending', $5, $6) RETURNING id",
        tenant_id, q_norm, sql, json.dumps(plan, ensure_ascii=False), sumber,
        fingerprint_tabel)


async def tulis_audit(core_pool, *, user_id, branch_code, prompt_text,
                      ai_json_filter, generated_sql, execution_time_ms,
                      status, error_message) -> None:
    """Audit keputusan pipeline — dipanggil pada sukses DAN kegagalan."""
    await core_pool.execute(
        "INSERT INTO audit_logs (user_id, branch_code, prompt_text, "
        "ai_json_filter, generated_sql, execution_time_ms, status, "
        "error_message) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
        user_id, branch_code, prompt_text,
        json.dumps(ai_json_filter, ensure_ascii=False) if ai_json_filter is not None else None,
        generated_sql, execution_time_ms, status, error_message)


async def ambil_atau_buat_conversation(core_pool, user_id: int,
                                       branch_code: str, judul: str) -> int:
    """Satu conversation per (user, branch) — pakai yang terakhir, atau buat."""
    cid = await core_pool.fetchval(
        "SELECT id FROM conversations WHERE user_id = $1 AND branch_code = $2 "
        "ORDER BY id DESC LIMIT 1", user_id, branch_code)
    if cid is not None:
        return cid
    return await core_pool.fetchval(
        "INSERT INTO conversations (user_id, branch_code, title) "
        "VALUES ($1, $2, $3) RETURNING id", user_id, branch_code, judul[:255])


async def simpan_pesan(core_pool, conversation_id: int, role: str,
                       content: str) -> None:
    await core_pool.execute(
        "INSERT INTO messages (conversation_id, role, content) "
        "VALUES ($1, $2, $3)", conversation_id, role, content)


def _bentuk_response(source: str, confidence: str, sql: str, params,
                     result: dict) -> dict:
    """Bentuk response API — SQL selalu disertakan (kejujuran, docs v2 §4)."""
    return {
        "source": source,
        "confidence": confidence,
        "sql": sql,
        "params": list(params or []),
        "columns": result["columns"],
        "rows": result["rows"],
        "row_count": result["row_count"],
        "truncated": result["truncated"],
        "duration_ms": result["duration_ms"],
    }


# ===========================================================================
# Pipeline utama
# ===========================================================================
async def proses_pertanyaan(core_pool, tenant_pool_manager, user: dict,
                            question: str, branch_code: str, *, now=None,
                            llm_call_fn=None,
                            row_cap: int = 500) -> dict:
    """Jalankan seluruh pipeline untuk SATU pertanyaan chat.

    Args:
        core_pool: pool DB core (asyncpg-compatible).
        tenant_pool_manager: TenantPoolManager (interface tunggal koneksi
            tenant; injectable fake di test).
        user: payload token {user_id, username, allowed_branches, ...} —
            guard role & cabang sudah dilakukan router.
        question / branch_code: input user (sudah tervalidasi bentuk).
        now: datetime untuk preset waktu composer. Default datetime.now()
            TZ SERVER (keputusan TZ di pemanggil — kontrak F2.2; laporan
            dealer mengikuti jam lokal server).
        llm_call_fn: injectable untuk test (tanpa LLM nyata).
        row_cap: diteruskan ke gerbang #6 (default 500).

    Returns:
        Response dict (lihat _bentuk_response) — dijamin memuat SQL.

    Raises:
        TenantTidakAda / SkemaTidakTersedia / TenantPoolError / AIConfigError
        / PlanningError / SqlComposerError / VerifierDitolak / ExecutorError
        / asyncpg.QueryCanceledError (timeout) — SEMUA kegagalan tetap
        ter-audit di blok except di bawah.
    """
    sekarang = now or datetime.now()  # TZ server — kontrak composer F2.2
    q_norm = normalisasi_pertanyaan(question)

    # Nilai untuk audit diisi progresif supaya kegagalan di tengah jalan
    # tetap meninggalkan konteks sebanyak mungkin.
    plan_terpakai = None
    sql_final = None
    durasi_ms = None

    try:
        tenant = await resolve_tenant(core_pool, branch_code)
        schema_config = _parse_schema_config(tenant["schema_config_json"])
        kb = parse_stored_kb(tenant["knowledge_base"])
        kb_forbidden = kb.get("tabel_dilarang") or []
        pool_tenant = await tenant_pool_manager.get_pool(tenant)

        # ---------- Tahap 3: SQL Memory replay (0 panggilan LLM) ----------
        entri = await cari_memory_approved(core_pool, tenant["tenant_id"],
                                           q_norm)
        if entri is not None:
            pakai_memory, params = True, None
            plan_tersimpan = _parse_json_mungkin_str(entri["plan_json"])
            sql_tersimpan = entri["sql"]
            if plan_tersimpan is not None:
                try:
                    composed = compose_sql(plan_tersimpan, schema_config,
                                           now=sekarang)
                    if composed["sql"] != sql_tersimpan:
                        # Komposisi ulang membedakan SQL tersimpan (versi
                        # composer/skema berubah) -> invalidasi otomatis.
                        await tandai_memory_stale(core_pool, entri["id"])
                        pakai_memory = False
                    else:
                        params = composed["params"]
                except SqlComposerError:
                    pakai_memory = False
            elif _PLACEHOLDER_RE.search(sql_tersimpan or ""):
                # SQL berparameter tanpa plan_json = tidak bisa dihitung
                # params-nya -> anggap MISS (planner akan membuat baru).
                pakai_memory = False

            if pakai_memory:
                hasil = await verify_and_execute(
                    pool_tenant, sql_tersimpan, schema_config, params=params,
                    kb_forbidden=kb_forbidden, row_cap=row_cap)
                if not hasil["verdict"]["ok"]:
                    # Entri approved seharusnya selalu lolos; kegagalan berarti
                    # skema berubah -> stale (audit tetap mencatat penolakan).
                    await tandai_memory_stale(core_pool, entri["id"])
                    raise VerifierDitolak(hasil["verdict"])
                await tandai_memory_dipakai(core_pool, entri["id"])
                plan_terpakai = plan_tersimpan
                sql_final = sql_tersimpan
                durasi_ms = hasil["result"]["duration_ms"]
                response = _bentuk_response(_SOURCE_MEMORY, _CONF_A,
                                            sql_tersimpan, params,
                                            hasil["result"])

        # ---------- Tahap 4: MISS -> planner + composer (panggilan #1) -----
        if entri is None or not pakai_memory:
            ai_config = await resolve_ai_config(core_pool, user["username"],
                                                branch_code)
            plan = await plan_query(question, schema_config, kb, ai_config,
                                    llm_call_fn=llm_call_fn)
            plan_terpakai = plan
            composed = compose_sql(plan, schema_config, now=sekarang)
            sql_final = composed["sql"]

            hasil = await verify_and_execute(
                pool_tenant, sql_final, schema_config,
                params=composed["params"], kb_forbidden=kb_forbidden,
                row_cap=row_cap)
            if not hasil["verdict"]["ok"]:
                raise VerifierDitolak(hasil["verdict"])

            durasi_ms = hasil["result"]["duration_ms"]
            fingerprint = ",".join(
                hasil["verdict"]["detail"].get("tabel_direferensikan") or [])
            await simpan_memory_pending(
                core_pool, tenant["tenant_id"], q_norm, sql_final, plan,
                sumber=_SOURCE_TIER1, fingerprint_tabel=fingerprint)
            response = _bentuk_response(_SOURCE_TIER1, _CONF_B, sql_final,
                                        composed["params"], hasil["result"])

        # ---------- Tahap 6: percakapan (2 pesan) + audit sukses ----------
        cid = await ambil_atau_buat_conversation(
            core_pool, user["user_id"], branch_code, question)
        await simpan_pesan(core_pool, cid, "user", question)
        # default=str: params berisi date/datetime dari preset waktu composer
        await simpan_pesan(core_pool, cid, "assistant",
                           json.dumps(response, ensure_ascii=False, default=str))
        await tulis_audit(
            core_pool, user_id=user["user_id"], branch_code=branch_code,
            prompt_text=question, ai_json_filter=plan_terpakai,
            generated_sql=sql_final, execution_time_ms=durasi_ms,
            status=_STATUS_SUCCESS, error_message=None)
        return response

    except VerifierDitolak as e:
        await _audit_gagal(core_pool, user, branch_code, question,
                           plan_terpakai, sql_final, durasi_ms,
                           _STATUS_REJECTED, e.verdict.get("reason"))
        raise
    except Exception as e:
        pesan = f"{type(e).__name__}: {e}"[:500]
        await _audit_gagal(core_pool, user, branch_code, question,
                           plan_terpakai, sql_final, durasi_ms,
                           _STATUS_ERROR, pesan)
        raise


async def _audit_gagal(core_pool, user, branch_code, question, plan, sql,
                       durasi_ms, status, pesan) -> None:
    """Audit kegagalan — TIDAK PERNAH menelan exception asli (kegagalan
    audit hanya di-log; error domain tetap sampai ke router)."""
    try:
        await tulis_audit(
            core_pool, user_id=(user or {}).get("user_id"),
            branch_code=branch_code, prompt_text=question,
            ai_json_filter=plan, generated_sql=sql,
            execution_time_ms=durasi_ms, status=status,
            error_message=pesan[:500])
    except Exception as audit_err:
        logger.error("chat_pipeline: gagal menulis audit: %s", audit_err)
