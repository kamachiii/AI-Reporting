"""F3 — Chat Pipeline: pertanyaan user -> jawaban + audit (docs v2 §1/§3).

Urutan tahap (milestone perangkuman):

1.  Normalisasi pertanyaan (lowercase + strip tanda baca, v2 §11 #2).
2.  Load tenant by branch (join tenants+db_connections) — 409 bila belum
    terhubung / nonaktif / schema_config belum diintrospeksi. Lalu skema
    EFEKTIF: `tabel_dilarang` dipotong lebih dulu, bila KB memuat
    `tabel_diizinkan` skema disempitkan HANYA ke tabel itu (tenant skema
    raksasa, mis. 2.387 tabel, tetap terpakai), lalu `kolom_dikecualikan`
    membuang kolom tak relevan (api key, token, logo, ...) — hemat token
    prompt planner. Allowlist kosong + skema
    > 150 tabel -> gagal cepat (422, gate "skema") meminta admin menetapkan
    allowlist. Skema efektif dipakai SEMUA tahap downstream (replay,
    planner, composer, verifier) — whitelist verifier otomatis menyempit.
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
    duration_ms, memory_id} — memory_id = id baris sql_memory PENDING yang
    baru dibuat (hanya jalur tier1; null untuk replay, karena entri replay
    sudah approved dan tidak butuh konfirmasi user).
8.  F2.5 presenter (ringkasan + saran): tier1 menjalankan buat_ringkasan
    (LLM #2, fail-open ke template) SEBELUM upsert agar ikut tersimpan di
    sql_memory; replay memakai ringkasan tersimpan (metode "cache") atau
    self-heal sekali bila NULL. Response menambah field {ringkasan, saran,
    metode} — metode: "llm" | "template" | "cache". Kegagalan presenter
    TIDAK PERNAH menggagalkan jawaban (log + lanjut tanpa ringkasan).
9.  F2.6 Tier 2 (flag `tenants.chat_tier2`, default FALSE — docs v2 §1):
    - Flag OFF: alur lama apa adanya (planner -> composer), tanpa perubahan.
    - Flag ON: pada MISS, router+generator (`tier2_generator.generate_sql`,
      SATU panggilan LLM) dipanggil dulu — generator yang memutuskan tier:
      hasil tier 1 = compose SUDAH selesai di generator (di-reuse, tidak
      compose dua kali) lalu lanjut alur lama persis; hasil tier 2 = SQL
      baru diverifikasi LAGI oleh verify_and_execute (defense-in-depth —
      verifier murah, keamanan tidak bergantung pada keputusan generator)
      lalu dieksekusi langsung (mode auto, docs v2 §7): source="tier2",
      confidence="C", attempts=n, memory pending (sumber="tier2",
      plan_json={"tier2": true}), presenter seperti biasa, ter-audit.
    - Tier2Error (self-repair habis, maks 2x) -> fallback ke alur Tier 1
      lama; fallback juga gagal (Planning/Composer) -> 502 dengan pesan
      gabungan yang jujur.
    - Replay entri memory tier2 (plan_json berisi {"tier2": true}): bila SQL
      tersimpan memuat literal tanggal (regex YYYY-MM-DD — menangkap literal
      string maupun cast ::date) -> anggap MISS (jangan replay data basi)
      TAPI baris TIDAK dihapus/di-stale-kan; tanpa literal tanggal -> replay
      normal (verify ulang tetap jalan).

F4 (tombol UI chat): `ubah_status_memory` menaikkan/menolak entri pending —
confirm: pending -> approved (approved = no-op sukses); reject: pending ->
rejected (rejected = no-op). Status TIDAK PERNAH diturunkan (docs v2 §3):
approved tidak boleh jadi rejected, dst. — ditolak dengan pesan jelas.

Exception service-layer -> router memetakan ke HTTP (lihat routers/chat.py):
TenantTidakAda/SkemaTidakTersedia -> 409, AIConfigError -> 503,
PlanningError/SqlComposerError -> 502, VerifierDitolak -> 422,
QueryCanceledError (timeout #6) -> 504, ExecutorError -> 500,
MemoryTidakDitemukan -> 404, StatusMemoryBertentangan -> 409.

Semua query core DB parameterized ($1, $2, ...) — tanpa eksepsi (pelajaran
PROGRES §4). Tidak ada import FastAPI — layer service murni.
"""
import json
import logging
import re
from datetime import datetime

from app.services.knowledge_base import parse_stored_kb
from app.services.presenter import buat_ringkasan
from app.services.query_executor import verify_and_execute
from app.services.query_planner import AIConfigError, PlanningError, plan_query, \
    resolve_ai_config
from app.services.sql_composer import SqlComposerError, compose_sql
from app.services.tier2_generator import Tier2Error, generate_sql

logger = logging.getLogger(__name__)

# --- Normalisasi pertanyaan untuk replay (keputusan v2 §11 #2: lowercase +
# strip tanda baca; kecocokan longgar, jawaban replay tetap level A karena
# entri yang di-replay wajib approved). Tanda baca diganti spasi lalu spasi
# dirapatkan — "omzet, bulan ini?" == "omzet bulan ini" == "OMZET BULAN INI".
_TANDA_BACA_RE = re.compile(r"[^\w\s]", re.UNICODE)
_SPASI_RE = re.compile(r"\s+")
_PLACEHOLDER_RE = re.compile(r"\$\d+")
# Literal tanggal/timestamp ISO pada SQL (menangkap literal string
# 'YYYY-MM-DD' maupun cast 'YYYY-MM-DD'::date) — penanda data basi untuk
# replay entri tier2 (jendela waktu beku saat SQL dibuat).
_TANGGAL_LITERAL_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

_STATUS_SUCCESS = "success"
_STATUS_REJECTED = "rejected"
_STATUS_ERROR = "error"

_SOURCE_MEMORY = "memory"
_SOURCE_TIER1 = "tier1"
_SOURCE_TIER2 = "tier2"
_CONF_A = "A"
_CONF_B = "B"
_CONF_C = "C"


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


class MemoryTidakDitemukan(Exception):
    """Entri sql_memory tidak ada / bukan milik tenant cabang ini (404).

    Milik tenant lain sengaja memakai 404 yang sama — keberadaan entri
    tenant lain tidak dibocorkan."""


class StatusMemoryBertentangan(Exception):
    """Transisi status memory tidak diizinkan (409) — status tidak pernah
    diturunkan (docs v2 §3), mis. approved ditolak kembali."""


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


# Ambang gagal-cepat: skema dengan tabel lebih banyak dari ini WAJIB punya
# allowlist — prompt planner & whitelist verifier tidak realistis untuk skema
# raksasa (kasus nyata tenant: 2.387 tabel).
_SKEMA_MAX_TABEL = 150


def _siapkan_skema_efektif(schema_config: dict, tabel_dilarang: list[str],
                           tabel_diizinkan: list[str],
                           kolom_dikecualikan: list[str]) -> tuple[dict, list[str]]:
    """Skema penuh tenant -> skema EFEKTIF untuk seluruh tahap downstream.

    Urutan pemotongan (terikat keputusan):
    1. `tabel_dilarang` SELALU dipotong lebih dulu — DILARANG menang atas
       DIIZINKAN bila satu tabel masuk dua daftar sekaligus.
    2. Bila `tabel_diizinkan` terisi, sisa skema disempitkan HANYA ke tabel
       pada allowlist; struktur kolom/FK tabel yang lolos dipertahankan apa
       adanya. Nama allowlist yang tidak ada di skema DIABAIKAN dan
       dikembalikan di `tabel_diabaikan` untuk catatan audit/log.
    3. `kolom_dikecualikan` membuang kolom (exact match "tabel.kolom") dari
       sisa tabel — entri yang tidak cocok diabaikan senyap. Skema efektif
       yang sama dipakai verifier, jadi SQL yang memakai kolom terbuang
       otomatis ditolak gerbang whitelist tanpa perubahan verifier.

    Bila allowlist kosong dan jumlah tabel melewati _SKEMA_MAX_TABEL — atau
    allowlist terisi tetapi tidak cocok satu tabel pun — -> VerifierDitolak
    dengan verdict sintetis gate "skema" (dipetakan 422 oleh router lewat
    pola error map verifier yang sudah ada; tanpa class error baru).
    """
    tables = dict(schema_config.get("tables") or {})
    for nama in tabel_dilarang or []:
        tables.pop(nama, None)  # dilarang menang: buang sebelum allowlist

    tabel_diabaikan: list[str] = []
    if tabel_diizinkan:
        saring = set(tabel_diizinkan)
        tabel_diabaikan = sorted({n for n in tabel_diizinkan if n not in tables})
        tables = {n: t for n, t in tables.items() if n in saring}
        if not tables:
            raise VerifierDitolak({
                "ok": False, "gate": "skema",
                "reason": "tabel_diizinkan tidak cocok dengan skema tenant "
                          "(tidak ada nama yang dikenal). Periksa kembali "
                          "allowlist di Knowledge Base."})
    elif len(tables) > _SKEMA_MAX_TABEL:
        raise VerifierDitolak({
            "ok": False, "gate": "skema",
            "reason": f"Skema tenant terlalu besar ({len(tables)} tabel). "
                      "Admin perlu menetapkan tabel_diizinkan di Knowledge "
                      "Base."})

    # 3. Buang kolom dikecualikan (exact match "tabel.kolom"). Entri tabel
    #    yang berubah diganti salinan BARU — info dict milik schema_config
    #    asal jangan dimutasi in-place (pemanggil masih memegang referensi).
    if kolom_dikecualikan:
        dibuang = set(kolom_dikecualikan)
        for nama, info in tables.items():
            kolom_lama = info.get("columns") or []
            kolom_baru = [c for c in kolom_lama
                          if f"{nama}.{c.get('name')}" not in dibuang]
            if len(kolom_baru) != len(kolom_lama):
                info_baru = dict(info)
                info_baru["columns"] = kolom_baru
                tables[nama] = info_baru

    skema = dict(schema_config)  # pertahankan kunci lain (introspected_at, dll)
    skema["tables"] = tables
    return skema, tabel_diabaikan


_SQL_TENANT = (
    "SELECT t.id AS tenant_id, t.branch_code, t.schema_config_json, "
    "       t.knowledge_base, t.is_active AS tenant_aktif, t.chat_tier2, "
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
        "SELECT id, sql, plan_json, times_used, fingerprint_tabel, "
        "ringkasan, saran "
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
                                fingerprint_tabel: str | None,
                                ringkasan: str | None = None,
                                saran: list | None = None) -> int:
    """Upsert SQL baru (lolos verifier) berstatus 'pending' (mode auto v2 §7).

    "Upsert" pada kunci (tenant_id, pertanyaan_ternormalisasi, sql): entri
    yang sudah ada diperbarui plan/fingerprints-nya TANPA menurunkan status
    (approved tetap approved — menaikkan boleh, menurunkan tidak). Entri baru
    -> INSERT status 'pending'; konfirmasi user/admin yang mengangkat ke
    'approved' (di luar jalur ini). F2.5: ringkasan & saran hasil presenter
    ikut disimpan agar replay tidak memanggil LLM lagi (NULL = self-heal
    pada replay berikutnya).
    """
    lama = await core_pool.fetchrow(
        "SELECT id FROM sql_memory WHERE tenant_id = $1 AND "
        "pertanyaan_ternormalisasi = $2 AND sql = $3 LIMIT 1",
        tenant_id, q_norm, sql)
    if lama:
        await core_pool.execute(
            "UPDATE sql_memory SET plan_json = $1, sumber = $2, "
            "fingerprint_tabel = $3, ringkasan = $4, saran = $5, "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE id = $6",
            json.dumps(plan, ensure_ascii=False), sumber, fingerprint_tabel,
            ringkasan, json.dumps(saran, ensure_ascii=False)
            if saran is not None else None,
            lama["id"])
        return lama["id"]
    return await core_pool.fetchval(
        "INSERT INTO sql_memory (tenant_id, pertanyaan_ternormalisasi, sql, "
        "plan_json, status, sumber, fingerprint_tabel, ringkasan, saran) "
        "VALUES ($1, $2, $3, $4, 'pending', $5, $6, $7, $8) RETURNING id",
        tenant_id, q_norm, sql, json.dumps(plan, ensure_ascii=False), sumber,
        fingerprint_tabel, ringkasan,
        json.dumps(saran, ensure_ascii=False) if saran is not None else None)


# --- F4: konfirmasi / penolakan entri pending dari tombol UI chat ----------
# Status TIDAK PERNAH diturunkan (docs v2 §3): confirm hanya menaikkan
# pending -> approved; reject menurunkan pending -> rejected. Transisi lain:
# approved kembali ditolak = DITOLAK; no-op untuk kondisi yang sudah sama.
_TRANSISI_MEMORY = {
    ("confirm", "pending"): "approved",
    ("confirm", "approved"): "approved",  # no-op — sudah terverifikasi
    ("reject", "pending"): "rejected",
    ("reject", "rejected"): "rejected",   # no-op — sudah ditolak
}

# Pesan jelas untuk transisi yang dilarang (dikembalikan apa adanya ke UI).
_PESAN_TRANSISI_TOLAK = {
    ("confirm", "rejected"):
        "Jawaban ini sudah ditandai salah sebelumnya dan tidak dapat "
        "dikonfirmasi. Tanyakan ulang untuk membuat entri baru.",
    ("confirm", "stale"):
        "Jawaban ini sudah tidak berlaku (stale) dan tidak dapat "
        "dikonfirmasi.",
    ("reject", "approved"):
        "Jawaban ini sudah terverifikasi (approved) — tidak dapat ditandai "
        "salah. Status memori tidak pernah diturunkan.",
    ("reject", "stale"):
        "Jawaban ini sudah tidak berlaku (stale) — tidak perlu ditolak.",
}


async def ubah_status_memory(core_pool, user, branch_code: str, memory_id: int,
                             aksi: str) -> dict:
    """F4 — confirm/reject entri SQL Memory milik cabang user (tombol UI).

    Entri hanya boleh milik tenant cabang tersebut; milik tenant lain /
    tidak ada -> MemoryTidakDitemukan (404, keberadaan entri orang lain
    tidak dibocorkan). SQL TIDAK disentuh di sini — SQL tersimpan sudah
    tervalidasi verifier saat pertama dibuat; fungsi ini hanya menaikkan
    status. Semua hasil ter-audit (sukses & penolakan).

    Args:
        aksi: "confirm" (jawaban benar) atau "reject" (jawaban salah).
        user: payload token (guard role & cabang sudah di router).

    Returns:
        {"ok": True, "status": "<status final>"} — no-op sukses juga
        mengembalikan bentuk ini.

    Raises:
        TenantTidakAda: cabang tidak terdaftar sebagai tenant (409).
        MemoryTidakDitemukan: entri bukan milik tenant ini / tidak ada (404).
        StatusMemoryBertentangan: transisi dilarang (409).
    """
    prompt_audit = f"[{aksi}-memory #{memory_id}]"
    sql_audit = None
    try:
        tenant_id = await core_pool.fetchval(
            "SELECT id FROM tenants WHERE branch_code = $1", branch_code)
        if tenant_id is None:
            raise TenantTidakAda(
                f"Cabang '{branch_code}' belum terhubung ke database tenant.")
        baris = await core_pool.fetchrow(
            "SELECT id, status, pertanyaan_ternormalisasi, sql "
            "FROM sql_memory WHERE id = $1 AND tenant_id = $2",
            memory_id, tenant_id)
        if baris is None:
            raise MemoryTidakDitemukan(
                "Jawaban yang ingin dinilai tidak ditemukan.")
        prompt_audit = (f"[{aksi}-memory #{memory_id}] "
                        f"{baris['pertanyaan_ternormalisasi']}")
        sql_audit = baris["sql"]

        status_lama = baris["status"]
        status_baru = _TRANSISI_MEMORY.get((aksi, status_lama))
        if status_baru is None:
            raise StatusMemoryBertentangan(
                _PESAN_TRANSISI_TOLAK.get((aksi, status_lama))
                or f"Status '{status_lama}' tidak dapat diubah oleh '{aksi}'.")
        if status_baru != status_lama:
            await core_pool.execute(
                "UPDATE sql_memory SET status = $1, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = $2",
                status_baru, memory_id)
        await tulis_audit(
            core_pool, user_id=(user or {}).get("user_id"),
            branch_code=branch_code, prompt_text=prompt_audit,
            ai_json_filter=None, generated_sql=sql_audit,
            execution_time_ms=None, status=_STATUS_SUCCESS, error_message=None)
        return {"ok": True, "status": status_baru}
    except (TenantTidakAda, MemoryTidakDitemukan,
            StatusMemoryBertentangan) as e:
        # Percobaan yang ditolak TETAP ter-audit (jejak keputusan/pensondelan).
        await _audit_gagal(core_pool, user, branch_code, prompt_audit, None,
                           sql_audit, None, _STATUS_ERROR, str(e))
        raise


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
                     result: dict, memory_id: int | None = None) -> dict:
    """Bentuk response API — SQL selalu disertakan (kejujuran, docs v2 §4).

    memory_id: id baris sql_memory PENDING yang baru dibuat (jalur tier1);
    None untuk replay — entri yang di-replay sudah approved sehingga tidak
    butuh tombol konfirmasi user. Field tambahan bersifat backward-compatible.
    """
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
        "memory_id": memory_id,
    }


# ===========================================================================
# F2.5 — presenter (ringkasan + saran) pada tier1 & replay
# ===========================================================================
def _saring_saran(raw) -> list[str]:
    """Kolom JSONB `saran` dari DB -> list[str] bersih (maks 3, buang kosong).

    asyncpg pool inti tanpa codec JSON mengembalikan str — pola
    _parse_json_mungkin_str; bentuk lain/rusak -> [] (tidak menjatuhkan
    replay hanya karena saran tersimpan rusak)."""
    data = _parse_json_mungkin_str(raw)
    if not isinstance(data, list):
        return []
    return [s.strip() for s in data if isinstance(s, str) and s.strip()][:3]


async def _ringkasan_replay(core_pool, entri, question: str, result: dict,
                            username: str, branch_code: str,
                            llm_call_fn=None) -> tuple:
    """Ringkasan untuk jalur replay (F2.5): (ringkasan, saran, metode).

    - baris memory PUNYA ringkasan -> pakai apa adanya (metode "cache",
      0 panggilan LLM, 0 resolve config).
    - ringkasan NULL -> self-heal: presenter dijalankan SEKALI lalu hasilnya
      di-UPDATE ke baris memory itu (replay berikutnya sudah cache). Resolve
      ai_config gagal -> tanpa LLM (kasus trivial tetap dapat template,
      sisanya ringkasan None). Semua kegagalan presenter/log DB hanya
      di-log — replay tidak pernah gagal karena pelapis presentasi.
    """
    tersimpan = entri["ringkasan"]
    if tersimpan:
        return tersimpan, _saring_saran(entri["saran"]), "cache"

    ai_config = None
    try:
        ai_config = await resolve_ai_config(core_pool, username, branch_code)
    except Exception as e:  # AIConfigError/dekripsi -> lanjut tanpa LLM
        logger.warning("chat_pipeline: replay tanpa ai_config: %s", e)
    try:
        pres = await buat_ringkasan(
            question, result["columns"], result["rows"],
            result["row_count"], ai_config, llm_call_fn=llm_call_fn)
    except Exception as e:  # belt-and-suspenders: presenter fail-open
        logger.error("chat_pipeline: presenter replay gagal: %s", e)
        pres = {"ringkasan": None, "saran": [], "metode": "template"}
    try:
        await core_pool.execute(
            "UPDATE sql_memory SET ringkasan = $1, saran = $2, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = $3",
            pres["ringkasan"],
            json.dumps(pres["saran"], ensure_ascii=False)
            if pres["saran"] else None,
            entri["id"])
    except Exception as e:
        logger.error("chat_pipeline: gagal self-heal ringkasan memory: %s", e)
    return pres["ringkasan"], pres["saran"], pres["metode"]


async def _ringkasan_tier1(question: str, result: dict, ai_config: dict,
                           llm_call_fn=None) -> tuple:
    """Ringkasan untuk jalur tier1 — presenter dengan ai_config ter-resolve;
    exception apa pun (tidak diharapkan: presenter fail-open) hanya di-log.
    Mengembalikan TUPLE (ringkasan, saran, metode) — kontrak sama dengan
    _ringkasan_replay (dict presenter dibongkar di sini, bukan di pemanggil)."""
    try:
        pres = await buat_ringkasan(
            question, result["columns"], result["rows"],
            result["row_count"], ai_config, llm_call_fn=llm_call_fn)
        return pres["ringkasan"], pres["saran"], pres["metode"]
    except Exception as e:
        logger.error("chat_pipeline: presenter tier1 gagal: %s", e)
        return None, [], "template"


def _pasang_ringkasan(response: dict, ringkasan, saran, metode) -> None:
    """Tambah field F2.5 ke response (ikut tersimpan di pesan assistant)."""
    response["ringkasan"] = ringkasan
    response["saran"] = saran
    response["metode"] = metode


async def _jalur_tier2(core_pool, pool_tenant, *, tenant_id: int, q_norm: str,
                       question: str, sql: str, attempts: int,
                       schema_config: dict, kb_forbidden: list,
                       ai_config: dict, row_cap: int,
                       llm_call_fn=None) -> tuple:
    """F2.6 — jalur Tier 2: SQL baru dari generator -> eksekusi (mode auto,
    docs v2 §7) -> presenter -> memory pending. Mengembalikan TUPLE
    (response, plan_terpakai, sql, durasi_ms) — kontrak sama dengan jalur
    tier1 agar audit di proses_pertanyaan seragam.

    Verifier DIJALANKAN LAGI di sini lewat verify_and_execute (gerbang
    #1–#5 ulang + gerbang #6) — defense-in-depth yang disengaja (docs v2
    §1): verifier milidetik, keamanan tidak pernah bergantung pada
    keputusan generator. SQL tier2 literal tanpa placeholder ($n).
    """
    hasil = await verify_and_execute(
        pool_tenant, sql, schema_config, params=None,
        kb_forbidden=kb_forbidden, row_cap=row_cap)
    if not hasil["verdict"]["ok"]:
        raise VerifierDitolak(hasil["verdict"])

    durasi_ms = hasil["result"]["duration_ms"]
    fingerprint = ",".join(
        hasil["verdict"]["detail"].get("tabel_direferensikan") or [])
    # Presenter seperti biasa (fail-open); hasil ikut tersimpan di memory.
    ringkasan, saran, metode_r = await _ringkasan_tier1(
        question, hasil["result"], ai_config, llm_call_fn=llm_call_fn)
    memory_id_baru = await simpan_memory_pending(
        core_pool, tenant_id, q_norm, sql, {"tier2": True},
        sumber=_SOURCE_TIER2, fingerprint_tabel=fingerprint,
        ringkasan=ringkasan, saran=saran)
    response = _bentuk_response(_SOURCE_TIER2, _CONF_C, sql, None,
                                hasil["result"], memory_id=memory_id_baru)
    response["attempts"] = attempts
    _pasang_ringkasan(response, ringkasan, saran, metode_r)
    plan_terpakai = {"tier2": True, "attempts": attempts}
    return response, plan_terpakai, sql, durasi_ms


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
        ter-audit di blok except di bawah. VerifierDitolak juga dipakai
        gagal-cepat skema efektif (verdict sintetis gate "skema"): skema
        terlalu besar tanpa tabel_diizinkan, atau allowlist tak cocok sama
        sekali.
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

        # ---------- Skema efektif (allowlist tabel_diizinkan KB) ----------
        # Rebind sekali di sini: replay composer, planner, compose_sql, dan
        # verify_and_execute semuanya menerima variabel schema_config — tidak
        # ada tahap downstream yang masih melihat skema penuh (maupun kolom
        # yang dikecualikan KB).
        schema_config, tabel_diabaikan = _siapkan_skema_efektif(
            schema_config, kb_forbidden, kb.get("tabel_diizinkan") or [],
            kb.get("kolom_dikecualikan") or [])
        jumlah_tabel_efektif = len(schema_config["tables"])
        pool_tenant = await tenant_pool_manager.get_pool(tenant)
        # F2.6: flag Tier 2 per tenant (migration 008, default FALSE).
        # .get() agar baris tanpa kolom (fake/test lama) tetap flag OFF.
        chat_tier2_aktif = bool(tenant.get("chat_tier2"))

        # ---------- Tahap 3: SQL Memory replay (0 panggilan LLM) ----------
        entri = await cari_memory_approved(core_pool, tenant["tenant_id"],
                                           q_norm)
        if entri is not None:
            pakai_memory, params = True, None
            plan_tersimpan = _parse_json_mungkin_str(entri["plan_json"])
            sql_tersimpan = entri["sql"]
            if isinstance(plan_tersimpan, dict) and plan_tersimpan.get("tier2"):
                # F2.6 — entri tier2: SQL literal (tanpa plan composer, tanpa
                # placeholder $n). Bila SQL memuat literal tanggal, replay
                # akan memakai jendela waktu BEKU saat SQL dibuat (data basi)
                # -> anggap MISS agar pertanyaan dijawab ulang; baris tetap
                # disimpan apa adanya (tidak dihapus, tidak di-stale-kan).
                # Tanpa literal tanggal -> replay normal seperti tier1
                # (verify ulang tetap jalan di verify_and_execute).
                if _TANGGAL_LITERAL_RE.search(sql_tersimpan or ""):
                    pakai_memory = False
            elif plan_tersimpan is not None:
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
                # F2.5: ringkasan dari cache memory, atau self-heal sekali
                # bila masih NULL (lihat _ringkasan_replay).
                _pasang_ringkasan(response, *(await _ringkasan_replay(
                    core_pool, entri, question, hasil["result"],
                    user["username"], branch_code, llm_call_fn=llm_call_fn)))

        # ---------- Tahap 4: MISS -> router dua tier (F2.6) / planner lama -
        if entri is None or not pakai_memory:
            ai_config = await resolve_ai_config(core_pool, user["username"],
                                                branch_code)

            # F2.6: flag ON -> router+generator SATU panggilan LLM dulu
            # (docs v2 §1/§5); generator yang memutuskan tier 1 atau 2.
            hasil_router = None
            pesan_tier2 = None
            if chat_tier2_aktif:
                conn = await pool_tenant.acquire()
                try:
                    async def _factory():
                        return conn
                    try:
                        hasil_router = await generate_sql(
                            question, schema_config, kb, ai_config, _factory,
                            llm_call_fn=llm_call_fn, now=sekarang)
                    except Tier2Error as e:
                        # Self-repair habis -> fallback alur Tier 1 lama;
                        # alasan dibawa agar pesan 502 akhir jujur.
                        pesan_tier2 = str(e)
                        logger.warning("chat_pipeline: Tier 2 habis percobaan"
                                       ", fallback Tier 1: %s", e)
                finally:
                    await pool_tenant.release(conn)

            if hasil_router is not None and hasil_router["tier"] == 2:
                response, plan_terpakai, sql_final, durasi_ms = \
                    await _jalur_tier2(
                        core_pool, pool_tenant, tenant_id=tenant["tenant_id"],
                        q_norm=q_norm, question=question,
                        sql=hasil_router["sql"],
                        attempts=hasil_router["attempts"],
                        schema_config=schema_config,
                        kb_forbidden=kb_forbidden, ai_config=ai_config,
                        row_cap=row_cap, llm_call_fn=llm_call_fn)
            else:
                # ---- Jalur Tier 1: flag OFF, hasil router tier 1, atau
                # fallback setelah Tier2Error — alur lama persis.
                if hasil_router is not None:
                    # Router memilih tier 1: compose SUDAH selesai di
                    # generator — reuse hasilnya, JANGAN compose dua kali.
                    plan = hasil_router["plan"]
                    plan_terpakai = plan
                    sql_final = hasil_router["sql"]
                    params_final = hasil_router["params"]
                else:
                    try:
                        plan = await plan_query(
                            question, schema_config, kb, ai_config,
                            llm_call_fn=llm_call_fn)
                        plan_terpakai = plan
                        composed = compose_sql(plan, schema_config,
                                               now=sekarang)
                    except (PlanningError, SqlComposerError) as e:
                        if pesan_tier2 is None:
                            raise  # flag OFF — pemetaan lama apa adanya
                        # 502 jujur: kegagalan Tier 2 + kegagalan fallback.
                        raise PlanningError(
                            f"Tier 2 gagal ({pesan_tier2}); fallback Tier 1 "
                            f"juga gagal: {e}") from e
                    sql_final = composed["sql"]
                    params_final = composed["params"]

                hasil = await verify_and_execute(
                    pool_tenant, sql_final, schema_config,
                    params=params_final, kb_forbidden=kb_forbidden,
                    row_cap=row_cap)
                if not hasil["verdict"]["ok"]:
                    raise VerifierDitolak(hasil["verdict"])

                durasi_ms = hasil["result"]["duration_ms"]
                fingerprint = ",".join(
                    hasil["verdict"]["detail"].get("tabel_direferensikan") or [])
                # F2.5: ringkasan + saran (LLM #2, fail-open ke template)
                # dibentuk SEBELUM upsert agar ikut tersimpan di sql_memory.
                ringkasan, saran, metode_r = await _ringkasan_tier1(
                    question, hasil["result"], ai_config, llm_call_fn=llm_call_fn)
                memory_id_baru = await simpan_memory_pending(
                    core_pool, tenant["tenant_id"], q_norm, sql_final, plan,
                    sumber=_SOURCE_TIER1, fingerprint_tabel=fingerprint,
                    ringkasan=ringkasan, saran=saran)
                response = _bentuk_response(_SOURCE_TIER1, _CONF_B, sql_final,
                                            params_final, hasil["result"],
                                            memory_id=memory_id_baru)
                _pasang_ringkasan(response, ringkasan, saran, metode_r)

        # ---------- Tahap 6: percakapan (2 pesan) + audit sukses ----------
        cid = await ambil_atau_buat_conversation(
            core_pool, user["user_id"], branch_code, question)
        await simpan_pesan(core_pool, cid, "user", question)
        # default=str: params berisi date/datetime dari preset waktu composer
        await simpan_pesan(core_pool, cid, "assistant",
                           json.dumps(response, ensure_ascii=False, default=str))
        # Catatan skema efektif di audit ai_json_filter: jumlah tabel yang
        # benar-benar dipakai planner/composer/verifier (plan dibungkus agar
        # audit tetap satu objek JSON; plan asli TIDAK dimutasi — dipakai
        # ulang untuk replay sql_memory).
        catatan_ai = {"plan": plan_terpakai,
                      "tables_effective": jumlah_tabel_efektif}
        if tabel_diabaikan:
            catatan_ai["tables_ignored"] = tabel_diabaikan
        await tulis_audit(
            core_pool, user_id=user["user_id"], branch_code=branch_code,
            prompt_text=question, ai_json_filter=catatan_ai,
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
