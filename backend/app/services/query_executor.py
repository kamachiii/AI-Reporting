"""F2.4 — Query Executor: gerbang #6 eksekusi terkurung (docs v2 §2).

Pintu masuk tunggal F3 untuk menjalankan SQL ke tenant DB:

1. `verify_and_execute(pool, sql, schema_config, ...)` — jalankan
   `query_verifier.verify_query` (gerbang #1–#5) DULU; verdict gagal = JANGAN
   eksekusi (return `{verdict, result: None}` tanpa exception supaya pemanggil
   bisa mengaudit `gate`+`reason`). Verdict lolos -> eksekusi via
   `execute_tenant_query` (gerbang #6).

2. `execute_tenant_query(pool, final_sql, params, row_cap)` — eksekusi
   terkurung di atas pool tenant:
   - transaksi READ ONLY (`BEGIN READ ONLY` — postgres menolak penulisan
     apa pun meski SQL lolos verifier),
   - `SET LOCAL statement_timeout = '10s'` (batalkan query lambat; konstanta
     literal — SET tidak bisa parameterized, nilainya bukan input user),
   - cap baris via CURSOR (`fetch(row_cap + 1)`) — query berhenti dibaca
     setelah cap, tidak menunggu seluruh hasil,
   - konversi tipe aman-JSON (lihat `_konversi_nilai`).

## Keputusan penting: SQL berparameter ($1..$n) vs verifier

Profil verifier v1 belum mendaftar node `Parameter` sqlglot, sehingga SQL
dengan placeholder $n TIDAK bisa diverifikasi langsung (kontrak F2.2:
`ganti_placeholder_null` HANYA untuk verifikasi offline). Konsekuensinya di
`verify_and_execute`:

- Verifikasi (#1–#5) dijalankan pada `sql_cek = ganti_placeholder_null(sql)`.
- TANPA params  -> yang dieksekusi adalah `verdict.detail["final_sql"]`
  (render sqlglot dari SQL yang baru saja terverifikasi — jaminan kuat SQL
  eksekusi == SQL verifikasi).
- DENGAN params -> yang dieksekusi adalah SQL asli (berparameter). Sebelum
  eksekusi, struktur SQL asli DIBUKTIKAN identik dengan `final_sql`:
  parse SQL asli, ganti setiap `exp.Parameter` -> `exp.Null`, lalu bandingkan
  render sqlglot-nya dengan `final_sql`. Tidak cocok -> `ExecutorError`
  (fail-closed, tidak pernah dieksekusi). Karena nilai filter selalu lewat
  params (composer tidak pernah menaruh literal di SQL), substitusi NULL
  tidak menyembunyikan apa pun kecuali nilai itu sendiri.

Catatan EXPLAIN (#5): dijalankan pada teks NULL-substitusi (verify_query
tidak menerima args), sehingga estimasi cost bisa sedikit berbeda dari
eksekusi nyata. Penangkal tetap: budget gerbang #4 (join/CTE), statement
timeout 10 dtk, dan cap baris di gerbang #6 — tidak ada jalur eksekusi tanpa
#6.

Konversi tipe (dokumentasi): Decimal -> float (nilai rupiah pada skema dealer
jauh di bawah 2^53 sehingga aman; bila suatu saat perlu presisi penuh,
kirim sebagai string — keputusan v1: float agar chart langsung bisa memakai),
date/datetime -> ISO string, time/timedelta/UUID/bytes -> string, sisanya
diteruskan apa adanya (None/bool/int/float/str). Konversi rekursif untuk
list/dict (tipe array/composite asyncpg).
"""
import logging
import time
import uuid
from datetime import date, datetime, time as dtime, timedelta
from decimal import Decimal

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from app.services.query_verifier import verify_query
from app.services.sql_composer import ganti_placeholder_null

logger = logging.getLogger(__name__)

# Gerbang #6 — konstanta terkurung (docs v2 §2 baris #6).
STATEMENT_TIMEOUT = "10s"
DEFAULT_ROW_CAP = 500


class ExecutorError(Exception):
    """Pelanggaran invarian internal executor (fail-closed, tidak dieksekusi)."""


def _konversi_nilai(v):
    """Konversi satu nilai hasil asyncpg menjadi aman-JSON (rekursif).

    asyncpg mengembalikan tipe Python kaya (Decimal, date, UUID, ...) yang
    tidak bisa di-serialize FastAPI JSONResponse langsung. Aturan:
    - Decimal -> float (lihat catatan presisi di docstring modul)
    - date/datetime -> ISO-8601 string; time/timedelta/UUID -> string
    - bytes -> UTF-8 bila mungkin, kalau tidak hex string
    - list/tuple/set (array/composite) -> konversi per elemen
    - dict (composite row) -> konversi per nilai
    - None/bool/int/float/str diteruskan apa adanya
    - tipe lain -> string repr (jangan pernah gagalkan query hanya karena
      tipe presentasional tak terduga)
    """
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, dtime):
        return v.isoformat()
    if isinstance(v, timedelta):
        return str(v)
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        data = bytes(v)
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.hex()
    if isinstance(v, (list, tuple, set, frozenset)):
        return [_konversi_nilai(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _konversi_nilai(x) for k, x in v.items()}
    return str(v)


async def execute_tenant_query(pool, final_sql: str, params=None,
                               row_cap: int = DEFAULT_ROW_CAP) -> dict:
    """Gerbang #6 — eksekusi terkurung satu query SELECT ke pool tenant.

    Args:
        pool: pool tenant dari TenantPoolManager (atau fake pool di test).
        final_sql: SQL yang SUDAH lolos verifier (jangan dipakai tanpa
            verifikasi — pintu masuk yang benar adalah `verify_and_execute`).
        params: nilai untuk placeholder $1..$n (urut), boleh None/kosong.
        row_cap: batas baris hasil; lebih -> `truncated=True` dan sisanya
            tidak dibaca (cursor berhenti di row_cap + 1).

    Returns:
        {"columns": list[str], "rows": list[list], "row_count": int,
         "duration_ms": int, "truncated": bool}

    Raises:
        asyncpg.exceptions.QueryCanceledError: statement timeout tercapai
            (dimapkan router ke HTTP 504).
        ExecutorError: invarian terlanggar (SQL berparameter tanpa params).
    """
    if params is None:
        params = []
    if "$" in final_sql and not params:
        # SQL berparameter tanpa nilai = pasti salah jalur (mis. entri memory
        # tanpa plan_json). Lebih baik gagal jelas daripada mengeksekusi teks
        # NULL-substitusi yang semantiknya berbeda (WHERE x = NULL).
        raise ExecutorError("SQL berparameter ($n) dieksekusi tanpa params — tolak")

    conn = await pool.acquire()
    mulai = time.monotonic()
    try:
        async with conn.transaction(readonly=True):
            # SET LOCAL hanya berlaku untuk transaksi ini; nilai konstanta
            # internal (bukan input user) — tidak bisa diparameterkan.
            await conn.execute(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'")
            stmt = await conn.prepare(final_sql)
            # get_attributes() memberi nama kolom WALAU hasilnya kosong.
            kolom = [attr.name for attr in stmt.get_attributes()]
            cursor = await conn.cursor(final_sql, *params)
            baris = await cursor.fetch(row_cap + 1)
    finally:
        await pool.release(conn)

    durasi_ms = int((time.monotonic() - mulai) * 1000)
    truncated = len(baris) > row_cap
    if truncated:
        baris = baris[:row_cap]
    return {
        "columns": list(kolom),
        "rows": [[_konversi_nilai(v) for v in r] for r in baris],
        "row_count": len(baris),
        "duration_ms": durasi_ms,
        "truncated": truncated,
    }


def _petakan_sql_eksekusi(sql: str, final_sql: str, params) -> str:
    """Tentukan SQL yang dieksekusi + buktikan struktur == SQL terverifikasi.

    - Tanpa params: kembalikan `final_sql` (render sqlglot dari SQL yang baru
      diverifikasi) — bukti paling kuat.
    - Dengan params: SQL asli (berparameter) dipertahankan agar asyncpg
      mengirim nilai via protokol prepared statement. Struktur asli dibuktikan
      identik dengan `final_sql` (Parameter -> Null lalu bandingkan render).
    """
    if not params:
        return final_sql
    try:
        ast_asli = sqlglot.parse_one(sql, read="postgres")
        ast_cek = sqlglot.parse_one(final_sql, read="postgres")
    except ParseError as e:
        raise ExecutorError(f"SQL eksekusi tidak bisa diparse ulang: {e}") from e

    def _null_kan(node):
        return exp.Null() if isinstance(node, exp.Parameter) else node

    ast_asli = ast_asli.transform(_null_kan)
    if ast_asli.sql(dialect="postgres") != ast_cek.sql(dialect="postgres"):
        raise ExecutorError(
            "struktur SQL eksekusi tidak cocok dengan SQL terverifikasi "
            "(fail-closed) — jangan eksekusi")
    return sql


async def verify_and_execute(pool, sql: str, schema_config: dict, *,
                             params=None, kb_forbidden=None,
                             tenant_conn_factory=None,
                             row_cap: int = DEFAULT_ROW_CAP) -> dict:
    """Pintu masuk tunggal F3: verifier (gerbang #1–#5) lalu executor (#6).

    Args:
        pool: pool tenant (dipakai untuk EXPLAIN pre-flight bila
            `tenant_conn_factory` tidak diberikan, dan untuk eksekusi).
        sql: SQL dari composer / SQL Memory (boleh berparameter $1..$n).
        schema_config: bentuk `tenants.schema_config_json`.
        params: nilai placeholder (urut $1..$n); wajib konsisten dengan sql.
        kb_forbidden: `tabel_dilarang` dari knowledge base tenant.
        tenant_conn_factory: override factory koneksi untuk gerbang #5
            (injectable, dipakai test; verifier tidak menutup koneksi —
            kontrak query_verifier).
        row_cap: cap baris gerbang #6 (default 500, sejajar MAX_LIMIT guard).

    Returns:
        {"verdict": verdict, "result": hasil execute_tenant_query | None}
        — verdict gagal -> result None, TIDAK exception (pemanggil yang
        mengaudit gate+reason lalu memetakan ke HTTP 422).

    Raises:
        ExecutorError: invarian terlanggar (fail-closed).
        asyncpg.exceptions.*: kegagalan eksekusi runtime (mis. QueryCanceled
            pada timeout — dipetakan router ke 504).
    """
    sql_cek = ganti_placeholder_null(sql)

    if tenant_conn_factory is not None:
        verdict = await verify_query(sql_cek, schema_config, tenant_conn_factory,
                                     kb_forbidden=kb_forbidden)
    else:
        # Satu koneksi dari pool untuk EXPLAIN; dilepas lagi (verifier tidak
        # mengelola siklus hidup koneksi — kontrak di docstring-nya).
        conn = await pool.acquire()
        try:
            async def _factory():
                return conn
            verdict = await verify_query(sql_cek, schema_config, _factory,
                                         kb_forbidden=kb_forbidden)
        finally:
            await pool.release(conn)

    if not verdict["ok"]:
        logger.info("executor: verifier menolak (gate %s): %s",
                    verdict.get("gate"), verdict.get("reason"))
        return {"verdict": verdict, "result": None}

    final_sql = verdict["detail"]["final_sql"]
    sql_eksekusi = _petakan_sql_eksekusi(sql, final_sql, params)
    result = await execute_tenant_query(pool, sql_eksekusi, params=params,
                                        row_cap=row_cap)
    return {"verdict": verdict, "result": result}
