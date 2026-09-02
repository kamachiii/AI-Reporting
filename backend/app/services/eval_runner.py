"""F2.7 — Eval Harness Golden-Set (docs/PERANCANGAN-PIPELINE-AI-v2.md §6/§8).

Eval terkurasi per tenant: daftar "pertanyaan emas" (tabel `eval_cases`,
migration 009) dijalankan lewat alur internal pipeline chat SAMPAI SEBELUM
presenter — tanpa LLM presenter, TANPA eksekusi di jalur verifikasi — lalu
SQL final dibandingkan dengan `sql_harapan`:

1. status "persis"      — SQL final (hasil verifier, `detail["final_sql"]`)
                          identik dengan sql_harapan setelah KANONISASI
                          (kedua sisi dilewatkan bentuk final verifier: LIMIT
                          dipaksa + render sqlglot) lalu NORMALISASI
                          (lowercase, spasi dirapatkan, kutip-ganda & `;`
                          akhir dibuang). Perbedaan kapitalisasi/spasi/kutip
                          identifier/LIMIT implisit tidak dianggap beda.
2. status "semantik"    — bila teks tak persis: SQL final + sql_harapan
                          dieksekusi ke DB tenant (transaksi READ ONLY +
                          statement_timeout, cap 20 baris) dan dibandingkan
                          (nama kolom sama, nilai sama max 20 baris).
3. status "gagal"       — planner/generator/eksepsi apa pun, atau hasil
                          perbandingan semantik berbeda.
4. status "pelanggaran" — verifier (gerbang mana pun) menolak SQL di jalur
                          mana pun (SQL pipeline maupun sql_harapan).
                          Dihitung terpisah di `pelanggaran_verifier` —
                          gate Tier 2 menuntut 0 (docs v2 §8).

Perbedaan penting dengan pipeline produksi (chat_pipeline) — disengaja,
karena eval adalah alat regresi yang tidak boleh mengubah state:
- SQL Memory yang komposisi ulangnya tidak cocok TIDAK ditandai stale;
- verifier menolak entri memory TIDAK menandai stale (hanya dicatat).
Flag `tenants.chat_tier2` diikuti apa adanya (eval menguji pipeline penuh
sebagaimana dipakai produksi); jalur per kasus dicatat di field `jalur`
("memory" | "tier1" | "tier2").

Gate aktivasi Tier 2 (`status_gate`): baris eval_runs TERBARU harus
pass_rate >= 0.95 DAN 0 pelanggaran verifier (docs v2 §8). Belum pernah
run -> gate tertutup ("jalankan eval dulu").

Semua query core DB parameterized ($1, $2, ...). Tidak ada import FastAPI —
layer service murni (pola chat_pipeline).
"""
import asyncio
import json
import logging
import re
from datetime import datetime

from app.services.chat_pipeline import (
    SkemaTidakTersedia, TenantTidakAda, VerifierDitolak,
    _parse_json_mungkin_str, _parse_schema_config, _siapkan_skema_efektif,
    cari_memory_approved, normalisasi_pertanyaan, resolve_tenant)
from app.services.query_executor import _konversi_nilai
from app.services.query_planner import (
    AIConfigError, PlanningError, plan_query, resolve_ai_config)
from app.services.query_verifier import verify_query
from app.services.sql_composer import (
    SqlComposerError, compose_sql, ganti_placeholder_null)
from app.services.sql_guard import verify_sql
from app.services.tier2_generator import Tier2Error, generate_sql

logger = logging.getLogger(__name__)

# Ambang gate aktivasi Tier 2 (docs v2 §8 — keputusan terbuka §11 #1).
AMBANG_PASS_RATE_TIER2 = 0.95

# Timeout per kasus (docs v2 §8 skenario eval tidak boleh menggantung).
_TIMEOUT_CASE_DETIK = 60.0

# Perbandingan semantik: bandingkan maks 20 baris pertama (kontrak F2.7).
_MAKS_BARIS_SEMANTIK = 20

# Placeholder $n (SQL berparameter hasil composer) — pola yang sama dengan
# chat_pipeline; diganti NULL hanya untuk VERIFIKASI offline (kontrak F2.2).
_PLACEHOLDER_RE = re.compile(r"\$\d+")
# Literal tanggal pada SQL — penanda data basi utk replay entri tier2.
_TANGGAL_LITERAL_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_SPASI_RE = re.compile(r"\s+")

_JALUR_MEMORY = "memory"
_JALUR_TIER1 = "tier1"
_JALUR_TIER2 = "tier2"

# Status per kasus (kontrak response)
_ST_PERSIS = "persis"
_ST_SEMANTIK = "semantik"
_ST_GAGAL = "gagal"
_ST_PELANGGARAN = "pelanggaran"


# ===========================================================================
# Helper murni
# ===========================================================================
def normalisasi_sql(sql: str) -> str:
    """Normalisasi teks SQL utk perbandingan "persis" (keputusan teknis F2.7):
    lowercase, spasi dirapatkan, kutip-ganda identifier dibuang, `;` akhir
    dibuang. Kutip tunggal (string literal) dipertahankan — mengubahnya
    mengubah makna SQL."""
    if not sql:
        return ""
    tanpa_kutip = sql.replace('"', " ").strip().rstrip(";")
    return _SPASI_RE.sub(" ", tanpa_kutip.lower()).strip()


def verifikasi_sql_harapan(tenant_row: dict, sql_harapan: str) -> dict:
    """Verifikasi sql_harapan terhadap skema EFEKTIF tenant (gerbang #1–#4).

    Skema efektif = schema_config dipotong KB (`tabel_diizinkan` menyempitkan,
    `tabel_dilarang`/`kolom_dikecualikan` membuang) — persis seperti skema
    yang dilihat verifier di pipeline. Golden set yang salah TIDAK BOLEH
    masuk (422 di router): bila allowlist membuat skema kosong, singkatan
    gagal-cepat chat_pipeline melempar VerifierDitolak (gate "skema").

    Returns:
        Verdict dict verify_sql — ok=True menyertakan detail["final_sql"].
    """
    schema_config = _parse_schema_config(tenant_row["schema_config_json"])
    kb = parse_kb_tenant(tenant_row)
    kb_forbidden = kb.get("tabel_dilarang") or []
    schema_config, _ = _siapkan_skema_efektif(
        schema_config, kb_forbidden, kb.get("tabel_diizinkan") or [],
        kb.get("kolom_dikecualikan") or [])
    return verify_sql(sql_harapan, schema_config, kb_forbidden=kb_forbidden)


def parse_kb_tenant(tenant_row: dict) -> dict:
    """KB ternormalisasi dari baris tenant (kolom knowledge_base)."""
    from app.services.knowledge_base import parse_stored_kb
    return parse_stored_kb(tenant_row.get("knowledge_base"))


def status_gate(tenant_row, eval_runs_terakhir) -> dict:
    """Gate aktivasi Tier 2 (docs v2 §8) — murni fungsi.

    Args:
        tenant_row: baris/dict tenant (dipakai untuk label cabang di pesan).
        eval_runs_terakhir: baris eval_runs TERBARU milik tenant (dict/Record)
            atau None bila belum pernah menjalankan eval.

    Returns:
        {"tier2_diizinkan": bool, "alasan": str} — lulus hanya bila
        pass_rate >= AMBANG_PASS_RATE_TIER2 (0.95) DAN 0 pelanggaran
        verifier. Belum pernah run -> tertutup dengan pesan "jalankan eval
        dulu".
    """
    cabang = (tenant_row or {}).get("branch_code") if tenant_row else None
    if eval_runs_terakhir is None:
        return {
            "tier2_diizinkan": False,
            "alasan": "Belum pernah menjalankan eval — jalankan eval dulu "
                      "(POST /admin/tenants/{branch}/eval-run) untuk "
                      "membuka gate Tier 2.",
        }
    pass_rate = float(eval_runs_terakhir.get("pass_rate") or 0.0)
    pelanggaran = int(eval_runs_terakhir.get("pelanggaran_verifier") or 0)
    if pass_rate >= AMBANG_PASS_RATE_TIER2 and pelanggaran == 0:
        return {
            "tier2_diizinkan": True,
            "alasan": f"Eval terakhir lulus gate: pass_rate "
                      f"{pass_rate:.0%} >= {AMBANG_PASS_RATE_TIER2:.0%}, "
                      f"0 pelanggaran verifier.",
        }
    alasan = (f"Eval terakhir belum memenuhi gate Tier 2: pass_rate "
              f"{pass_rate:.0%} < {AMBANG_PASS_RATE_TIER2:.0%}")
    if pelanggaran:
        alasan += f", {pelanggaran} pelanggaran verifier (wajib 0)"
    if cabang:
        alasan += f" (cabang {cabang})"
    return {"tier2_diizinkan": False, "alasan": alasan}


async def ambil_run_terakhir(core_pool, tenant_id: int):
    """Baris eval_runs terbaru milik tenant (atau None bila belum pernah)."""
    return await core_pool.fetchrow(
        "SELECT id, total, lulus, pelanggaran_verifier, pass_rate, detail, "
        "dijalankan_oleh, created_at "
        "FROM eval_runs WHERE tenant_id = $1 "
        "ORDER BY created_at DESC, id DESC LIMIT 1", tenant_id)


# ===========================================================================
# Eksekusi utk perbandingan semantik (satu-satunya tempat eval menyentuh
# data DB tenant — terkurung seperti gerbang #6)
# ===========================================================================
async def _eksekusi_bandingkan(conn, sql: str, params=None) -> tuple:
    """Eksekusi read-only utk perbandingan semantik -> (kolom, baris).

    Terkurung seperti gerbang #6 (docs v2 §2): transaksi READ ONLY +
    statement_timeout + cap baris (_MAKS_BARIS_SEMANTIK + 1 utk deteksi
    terpotong — cukup bandingkan 20 baris pertama)."""
    async with conn.transaction(readonly=True):
        await conn.execute("SET LOCAL statement_timeout = '10s'")
        stmt = await conn.prepare(sql)
        kolom = [attr.name for attr in stmt.get_attributes()]
        cursor = await conn.cursor(sql, *(params or []))
        baris = await cursor.fetch(_MAKS_BARIS_SEMANTIK + 1)
    return kolom, [[_konversi_nilai(v) for v in r]
                   for r in baris[:_MAKS_BARIS_SEMANTIK]]


def _case(id_case, pertanyaan, status, sql_dihasilkan=None, alasan=None,
          jalur=None) -> dict:
    """Bentuk hasil satu kasus (kontrak response/detail JSONB)."""
    return {"id": id_case, "pertanyaan": pertanyaan, "status": status,
            "sql_dihasilkan": sql_dihasilkan, "alasan": alasan,
            "jalur": jalur}


# ===========================================================================
# Pemrosesan SATU kasus (mirroring chat_pipeline sampai sebelum presenter)
# ===========================================================================
async def _proses_satu_case(core_pool, *, tenant: dict, schema_config: dict,
                            kb: dict, kb_forbidden: list, chat_tier2: bool,
                            username_admin: str, branch_code: str,
                            case: dict, conn_factory, now, llm_call_fn) -> dict:
    """Jalankan satu pertanyaan emas lewat alur pipeline (tanpa presenter,
    tanpa eksekusi di jalur verifikasi) lalu bandingkan dgn sql_harapan.

    Raises:
        Exception apa pun dibiarkan naik — dibungkus timeout/except di
        jalankan_eval menjadi status "gagal" dengan alasan.
    """
    pertanyaan = case["pertanyaan"]
    sql_harapan = case["sql_harapan"]
    id_case = case["id"]
    q_norm = normalisasi_pertanyaan(pertanyaan)

    # --- Golden set wajib tetap lolos verifier (skema bisa berubah sejak
    # kasus dibuat) — ditolak sekarang = pelanggaran tercatat, bukan senyap.
    verdict_harapan = verify_sql(sql_harapan, schema_config,
                                 kb_forbidden=kb_forbidden)
    if not verdict_harapan["ok"]:
        return _case(id_case, pertanyaan, _ST_PELANGGARAN,
                     sql_dihasilkan=None,
                     alasan=f"sql_harapan ditolak verifier "
                            f"(gate {verdict_harapan['gate']}): "
                            f"{verdict_harapan['reason']}")
    final_harapan = verdict_harapan["detail"]["final_sql"]

    # ---------- Tahap 3: SQL Memory replay (0 panggilan LLM) ----------
    entri = await cari_memory_approved(core_pool, tenant["tenant_id"], q_norm)
    pakai_memory = False
    if entri is not None:
        sql_tersimpan = entri["sql"]
        params = None
        plan_tersimpan = _parse_json_mungkin_str(entri["plan_json"])
        pakai_memory = True
        if isinstance(plan_tersimpan, dict) and plan_tersimpan.get("tier2"):
            # Entri tier2 berliteral tanggal = jendela waktu beku (data basi)
            # -> MISS tanpa menyentuh baris (aturan sama dgn chat_pipeline).
            if _TANGGAL_LITERAL_RE.search(sql_tersimpan or ""):
                pakai_memory = False
        elif plan_tersimpan is not None:
            try:
                composed = compose_sql(plan_tersimpan, schema_config, now=now)
                if composed["sql"] != sql_tersimpan:
                    pakai_memory = False  # eval TIDAK menandai stale
                else:
                    params = composed["params"]
            except SqlComposerError:
                pakai_memory = False
        elif _PLACEHOLDER_RE.search(sql_tersimpan or ""):
            pakai_memory = False  # berparameter tanpa plan -> tak bisa replay

        if pakai_memory:
            sql_cek = ganti_placeholder_null(sql_tersimpan)
            if conn_factory is not None:
                verdict = await verify_query(sql_cek, schema_config,
                                             conn_factory,
                                             kb_forbidden=kb_forbidden)
            else:
                verdict = verify_sql(sql_cek, schema_config,
                                     kb_forbidden=kb_forbidden)
            if not verdict["ok"]:
                return _case(id_case, pertanyaan, _ST_PELANGGARAN,
                             sql_dihasilkan=sql_tersimpan,
                             alasan=f"memory ditolak verifier "
                                    f"(gate {verdict['gate']}): "
                                    f"{verdict['reason']}",
                             jalur=_JALUR_MEMORY)
            sql_final = verdict["detail"].get("final_sql") or sql_tersimpan
            return await _bandingkan(
                id_case, pertanyaan, sql_final, params, final_harapan,
                conn_factory, sql_eksekusi=sql_tersimpan,
                jalur=_JALUR_MEMORY)

    # ---------- Tahap 4: MISS -> planner / router dua tier ----------
    ai_config = await resolve_ai_config(core_pool, username_admin,
                                        branch_code)
    hasil_router = None
    pesan_tier2 = None
    if chat_tier2 and conn_factory is not None:
        # Flag ON: router+generator SATU panggilan LLM (docs v2 §1) —
        # keputusan tier diambil generator, seperti pipeline produksi.
        try:
            hasil_router = await generate_sql(
                pertanyaan, schema_config, kb, ai_config, conn_factory,
                llm_call_fn=llm_call_fn, now=now)
        except Tier2Error as e:
            # Self-repair habis -> fallback alur Tier 1 (pola chat_pipeline).
            pesan_tier2 = str(e)
            logger.info("eval: tier2 habis percobaan, fallback tier1: %s", e)
    elif chat_tier2:
        pesan_tier2 = "eval tanpa koneksi tenant — jalur tier 2 dilewati"

    if hasil_router is not None and hasil_router["tier"] == 2:
        # Verifier DIJALANKAN ULANG (defense-in-depth, docs v2 §1) — tanpa
        # eksekusi. SQL tier2 literal (tanpa placeholder).
        sql_tier2 = hasil_router["sql"]
        if conn_factory is not None:
            verdict = await verify_query(sql_tier2, schema_config,
                                         conn_factory,
                                         kb_forbidden=kb_forbidden)
        else:
            verdict = verify_sql(sql_tier2, schema_config,
                                 kb_forbidden=kb_forbidden)
        if not verdict["ok"]:
            return _case(id_case, pertanyaan, _ST_PELANGGARAN,
                         sql_dihasilkan=sql_tier2,
                         alasan=f"tier2 ditolak verifier "
                                f"(gate {verdict['gate']}): "
                                f"{verdict['reason']}",
                         jalur=_JALUR_TIER2)
        sql_final = verdict["detail"].get("final_sql") or sql_tier2
        return await _bandingkan(
            id_case, pertanyaan, sql_final, None, final_harapan,
            conn_factory, sql_eksekusi=verdict["detail"]["final_sql"],
            jalur=_JALUR_TIER2)

    # ---- Jalur Tier 1: flag OFF, hasil router tier 1, atau fallback ----
    if hasil_router is not None:
        # Router memilih tier 1: compose sudah selesai di generator — reuse
        # (pola chat_pipeline; JANGAN compose dua kali).
        sql_final = hasil_router["sql"]
        params = hasil_router["params"]
    else:
        plan = await plan_query(pertanyaan, schema_config, kb, ai_config,
                                llm_call_fn=llm_call_fn)
        composed = compose_sql(plan, schema_config, now=now)
        sql_final = composed["sql"]
        params = composed["params"]

    sql_cek = ganti_placeholder_null(sql_final)
    if conn_factory is not None:
        verdict = await verify_query(sql_cek, schema_config, conn_factory,
                                     kb_forbidden=kb_forbidden)
    else:
        verdict = verify_sql(sql_cek, schema_config, kb_forbidden=kb_forbidden)
    if not verdict["ok"]:
        alasan = f"tier1 ditolak verifier (gate {verdict['gate']}): " \
                 f"{verdict['reason']}"
        if pesan_tier2:
            alasan = f"tier2 gagal ({pesan_tier2}); " + alasan
        return _case(id_case, pertanyaan, _ST_PELANGGARAN,
                     sql_dihasilkan=sql_final, alasan=alasan,
                     jalur=_JALUR_TIER1)

    return await _bandingkan(
        id_case, pertanyaan,
        verdict["detail"].get("final_sql") or sql_final, params,
        final_harapan, conn_factory, sql_eksekusi=sql_final,
        jalur=_JALUR_TIER1, catatan_tier2=pesan_tier2)


async def _bandingkan(id_case, pertanyaan, sql_verifikasi, params,
                      final_harapan, conn_factory, *, sql_eksekusi, jalur,
                      catatan_tier2=None) -> dict:
    """Bandingkan SQL final dgn sql_harapan: persis -> semantik -> gagal.

    sql_verifikasi: bentuk final hasil verifier (utk perbandingan teks).
    sql_eksekusi + params: bentuk yang dieksekusi bila perlu semantik
    (SQL berparameter dieksekusi DENGAN params-nya — bukan substitusi NULL).
    """
    if normalisasi_sql(sql_verifikasi) == normalisasi_sql(final_harapan):
        return _case(id_case, pertanyaan, _ST_PERSIS,
                     sql_dihasilkan=sql_verifikasi, jalur=jalur)

    # ---- Tidak persis -> perbandingan semantik (butuh koneksi tenant) ----
    if conn_factory is None:
        return _case(id_case, pertanyaan, _ST_GAGAL,
                     sql_dihasilkan=sql_verifikasi,
                     alasan="SQL tidak persis dan perbandingan semantik "
                            "butuh koneksi tenant (tenant_pool_manager "
                            "tidak diberikan)",
                     jalur=jalur)
    conn = await conn_factory()  # siklus hidup dikelola pemilik factory
    kolom_hasil, baris_hasil = await _eksekusi_bandingkan(
        conn, sql_eksekusi, params)
    kolom_harap, baris_harap = await _eksekusi_bandingkan(
        conn, final_harapan, None)

    if kolom_hasil == kolom_harap and baris_hasil == baris_harap:
        alasan = "SQL berbeda teks tetapi hasil query identik (semantik)"
        if catatan_tier2:
            alasan += f"; {catatan_tier2}"
        return _case(id_case, pertanyaan, _ST_SEMANTIK,
                     sql_dihasilkan=sql_verifikasi, alasan=alasan,
                     jalur=jalur)
    alasan = "hasil query berbeda dari sql_harapan"
    if kolom_hasil != kolom_harap:
        alasan += (f" (kolom {kolom_hasil} vs {kolom_harap})")
    elif baris_hasil != baris_harap:
        alasan += (f" (baris {baris_hasil} vs {baris_harap})")
    if catatan_tier2:
        alasan += f"; {catatan_tier2}"
    return _case(id_case, pertanyaan, _ST_GAGAL,
                 sql_dihasilkan=sql_verifikasi, alasan=alasan, jalur=jalur)


# ===========================================================================
# Runner utama + penyimpanan metrik
# ===========================================================================
async def jalankan_eval(core_pool, branch_code: str, username_admin: str,
                        llm_call_fn=None, batas: int | None = None,
                        tenant_pool_manager=None, now=None,
                        timeout_per_case: float = _TIMEOUT_CASE_DETIK) -> dict:
    """Jalankan eval golden-set satu tenant (docs v2 §6/§8).

    Args:
        core_pool: pool DB core (asyncpg-compatible; fake diterima di test).
        branch_code: cabang tenant yang dievaluasi.
        username_admin: username admin pemicu (utk resolve ai_config
            scope user > tenant > global, seperti pipeline chat).
        llm_call_fn: injectable LLM utk planner/generator (None = LLM nyata).
        batas: maks kasus per run (None = semua kasus aktif).
        tenant_pool_manager: sumber koneksi tenant utk gerbang #5 (EXPLAIN)
            dan perbandingan semantik. None = verifikasi offline saja
            (gerbang #1–#4) dan kasus tak-persis otomatis gagal.
        now: datetime utk preset waktu composer (default datetime.now()).
        timeout_per_case: batas detik per kasus (default 60).

    Returns:
        {"total", "lulus", "gagal": [kasus gagal], "pelanggaran_verifier",
         "pass_rate", "detail": [semua kasus]} — lulus = persis + semantik;
         pass_rate = lulus / total (0.0 bila tak ada kasus — golden set
         kosong tidak boleh membuka gate).

    Raises:
        TenantTidakAda: cabang belum terhubung / nonaktif (409/404 di router).
        SkemaTidakTersedia / VerifierDitolak: skema belum diintrospeksi /
            skema efektif kosong (gate "skema").
    """
    sekarang = now or datetime.now()
    tenant = await resolve_tenant(core_pool, branch_code)
    schema_config = _parse_schema_config(tenant["schema_config_json"])
    kb = parse_kb_tenant(tenant)
    kb_forbidden = kb.get("tabel_dilarang") or []
    schema_config, _ = _siapkan_skema_efektif(
        schema_config, kb_forbidden, kb.get("tabel_diizinkan") or [],
        kb.get("kolom_dikecualikan") or [])
    # Flag chat_tier2 diikuti apa adanya (pipeline penuh); .get() agar baris
    # tanpa kolom (fake test lama) tetap flag OFF.
    chat_tier2 = bool(tenant.get("chat_tier2"))

    if batas is not None:
        rows = await core_pool.fetch(
            "SELECT id, pertanyaan, sql_harapan, catatan FROM eval_cases "
            "WHERE tenant_id = $1 AND aktif = TRUE ORDER BY id LIMIT $2",
            tenant["tenant_id"], batas)
    else:
        rows = await core_pool.fetch(
            "SELECT id, pertanyaan, sql_harapan, catatan FROM eval_cases "
            "WHERE tenant_id = $1 AND aktif = TRUE ORDER BY id",
            tenant["tenant_id"])

    conn_factory = None
    conn = None
    pool_tenant = None
    if tenant_pool_manager is not None:
        pool_tenant = await tenant_pool_manager.get_pool(tenant)
        conn = await pool_tenant.acquire()

        async def conn_factory():  # kontrak query_verifier: tidak menutup
            return conn

    detail: list[dict] = []
    try:
        for row in rows:
            case = dict(row)
            try:
                hasil_case = await asyncio.wait_for(
                    _proses_satu_case(
                        core_pool, tenant=tenant, schema_config=schema_config,
                        kb=kb, kb_forbidden=kb_forbidden,
                        chat_tier2=chat_tier2, username_admin=username_admin,
                        branch_code=branch_code, case=case,
                        conn_factory=conn_factory, now=sekarang,
                        llm_call_fn=llm_call_fn),
                    timeout=timeout_per_case)
            except asyncio.TimeoutError:
                hasil_case = _case(
                    case["id"], case["pertanyaan"], _ST_GAGAL,
                    alasan=f"timeout setelah {timeout_per_case:.0f} detik")
            except Exception as e:  # exception apa pun = gagal dgn alasan
                logger.warning("eval: kasus %s gagal: %s", case["id"], e)
                hasil_case = _case(case["id"], case["pertanyaan"],
                                   _ST_GAGAL,
                                   alasan=f"{type(e).__name__}: {e}"[:500])
            detail.append(hasil_case)
    finally:
        if pool_tenant is not None and conn is not None:
            await pool_tenant.release(conn)

    total = len(detail)
    gagal = [c for c in detail if c["status"] == _ST_GAGAL]
    pelanggaran = sum(1 for c in detail if c["status"] == _ST_PELANGGARAN)
    lulus = sum(1 for c in detail
                if c["status"] in (_ST_PERSIS, _ST_SEMANTIK))
    pass_rate = (lulus / total) if total else 0.0
    return {"total": total, "lulus": lulus, "gagal": gagal,
            "pelanggaran_verifier": pelanggaran, "pass_rate": pass_rate,
            "detail": detail}


async def simpan_metrik(core_pool, branch_code: str, hasil: dict) -> dict:
    """Simpan snapshot hasil eval ke eval_runs (migration 010) — metrik
    mingguan + sumber gate Tier 2 (docs v2 §8). Return baris ringkas."""
    tenant_id = await core_pool.fetchval(
        "SELECT id FROM tenants WHERE branch_code = $1", branch_code)
    run_id = await core_pool.fetchval(
        "INSERT INTO eval_runs (tenant_id, total, lulus, "
        "pelanggaran_verifier, pass_rate, detail, dijalankan_oleh) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id",
        tenant_id, hasil["total"], hasil["lulus"],
        hasil["pelanggaran_verifier"], float(hasil["pass_rate"]),
        json.dumps(hasil.get("detail") or [], ensure_ascii=False),
        (hasil.get("dijalankan_oleh") or None))
    return {"run_id": run_id, "branch_code": branch_code,
            "total": hasil["total"], "lulus": hasil["lulus"],
            "pelanggaran_verifier": hasil["pelanggaran_verifier"],
            "pass_rate": float(hasil["pass_rate"]),
            "dijalankan_oleh": hasil.get("dijalankan_oleh")}
