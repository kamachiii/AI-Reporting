"""SQL Guard (F2.3) + Verifier v2 (F2.3') — gerbang keamanan sebelum query
dieksekusi ke tenant DB.

Dua API dalam file ini:

1. `validate_readonly_query(sql, allowed_tables) -> str`  (F2.3, lama)
   Raise SqlGuardError (ValueError) pada setiap pelanggaran; bila lolos,
   KEMBALIKAN SQL final (dengan LIMIT dipaksa bila belum ada).
   API lama TIDAK diubah — perilaku & gerbangnya tetap persis seperti semula.

2. `verify_sql(sql, schema_config, kb_forbidden=None, budget=None) -> Verdict`
   (F2.3' Verifier v2, docs/PERANCANGAN-PIPELINE-AI-v2.md §2)
   Verifikasi TERSTRUKTUR gerbang offline #1–#4, mengembalikan dict Verdict
   `{ok, gate, reason, detail}` alih-alih raise — supaya query_verifier
   (gerbang #5 EXPLAIN) dan audit log bisa memakai keputusan per gerbang:
       gate: "bentuk" | "whitelist" | "profil" | "budget" | None (lolos)
       detail: konteks pelanggaran (mis. `objek`) atau, bila lolos,
               `final_sql` (LIMIT 500 dipaksa) + daftar tabel direferensikan.

Gerbang verify_sql (semua default-deny):
1. Parser & bentuk  — multi-statement, non-SELECT/UNION, INTO/COPY, lock
                      clause, SET, DML/DDL di posisi mana pun (termasuk di
                      dalam CTE), LIMIT > 500
2. Whitelist objek  — tabel & kolom di SEMUA node AST (subquery, CTE, join,
                      order by, dst.) dicocokkan ke `schema_config_json`
                      (bentuk: lihat schema_introspector) minus
                      `kb_forbidden` (tabel_dilarang dari knowledge base);
                      kolom tanpa kualifikasi divalidasi per-scope dengan
                      deteksi ambiguitas; identifier quoted dicek
                      case-sensitive (postgres), unquoted lowercase
3. Profil fitur     — SQL_FEATURE_PROFILE_V1: whitelist node AST + fungsi
                      (default-deny), RECURSIVE dilarang, hanya UNION ALL
                      (jumlah kolom sama), JOIN wajib ON dan terhubung
                      peta FK skema
4. Budget           — kedalaman AST, jumlah join, jumlah CTE, jumlah UNION

Catatan sqlglot: parse dilakukan dengan read="postgres" karena tenant DB
adalah PostgreSQL. Unparsable input tetap ditolak (fail-closed).
"""
import logging

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

logger = logging.getLogger(__name__)

# Fungsi yang dipakai untuk DoS / manipulasi waktu eksekusi.
# pg_sleep & varianten; daftar kecil dan eksplisit (bukan blacklist luas).
_DANGEROUS_FUNCTIONS = {
    "pg_sleep",
    "pg_sleep_for",
    "pg_sleep_until",
    "pg_terminate_backend",
    "pg_cancel_backend",
}

MAX_LIMIT = 500
DEFAULT_LIMIT = 500


class SqlGuardError(ValueError):
    """Pelanggaran kebijakan query read-only. Subclass ValueError agar
    penanganan lama (wrap ValueError -> HTTP 400) tetap bekerja."""


def _extract_table_names(tree: exp.Expression) -> set[str]:
    """Kumpulkan semua nama tabel yang direferensikan AST (tanpa alias)."""
    names: set[str] = set()
    for table in tree.find_all(exp.Table):
        # table.name = nama tabel tanpa katalog/schema; jangan pakai str(table)
        # karena itu bisa "schema.table" atau "db.schema.table".
        names.add(table.name.lower())
    return names


def _has_dangerous_function(tree: exp.Expression) -> str | None:
    for func in tree.find_all(exp.Anonymous):
        if func.name.lower() in _DANGEROUS_FUNCTIONS:
            return func.name
    # sqlglot bisa memetakan beberapa fungsi ke kelas ekspresi khusus,
    # jadi cek juga semua Anonymous di atas sudah cukup untuk pg_sleep.
    return None


def validate_readonly_query(sql: str, allowed_tables: set[str]) -> str:
    """Validasi satu statement SELECT read-only terhadap whitelist tabel.

    Args:
        sql: teks query dari user/planner.
        allowed_tables: nama tabel (lowercase) yang boleh disentuh.

    Returns:
        SQL final yang siap dieksekusi — LIMIT dipaksa bila belum ada
        (query tanpa LIMIT diberi LIMIT DEFAULT_LIMIT).

    Raises:
        SqlGuardError (ValueError): bila query melanggar kebijakan.
    """
    if not sql or not sql.strip():
        raise SqlGuardError("Query kosong")

    # --- Gerbang 1: parse tunggal, fail-closed ---
    try:
        statements = sqlglot.parse(sql, read="postgres")
    except ParseError as e:
        raise SqlGuardError(f"SQL tidak bisa diparse: {e}") from e

    # buang None (sqlglot bisa menghasilkan None untuk ';')
    statements = [s for s in statements if s is not None]
    if not statements:
        raise SqlGuardError("Tidak ada statement yang bisa dievaluasi")
    if len(statements) > 1:
        raise SqlGuardError("Multi-statement tidak diizinkan")

    tree = statements[0]

    # --- Gerbang 2: read-only, SELECT tunggal di root ---
    if not isinstance(tree, exp.Select):
        kind = type(tree).__name__
        raise SqlGuardError(
            f"Hanya SELECT yang diizinkan (ditemukan: {kind})")

    # SELECT INTO menulis tabel baru — masih exp.Select, blokir eksplisit
    if tree.args.get("into"):
        raise SqlGuardError("SELECT INTO tidak diizinkan")

    # --- Gerbang 4: fungsi berbahaya (cek sebelum whitelist agar pesan jelas) ---
    dangerous = _has_dangerous_function(tree)
    if dangerous:
        raise SqlGuardError(f"Fungsi tidak diizinkan: {dangerous}")

    # --- Gerbang 3: whitelist tabel ---
    referenced = _extract_table_names(tree)
    allowed_lower = {t.lower() for t in allowed_tables}
    unknown = sorted(referenced - allowed_lower)
    if unknown:
        raise SqlGuardError(
            f"Tabel di luar whitelist: {', '.join(unknown)}")

    # --- Gerbang 5: LIMIT wajib, cap 500 ---
    limit_arg = tree.args.get("limit")
    if limit_arg is not None:
        limit_expr = limit_arg.expression if hasattr(limit_arg, "expression") else limit_arg
        try:
            limit_value = int(limit_expr.sql(dialect="postgres").strip())
        except (ValueError, AttributeError):
            raise SqlGuardError("LIMIT harus berupa angka tetap")
        if limit_value > MAX_LIMIT:
            raise SqlGuardError(f"LIMIT maksimal {MAX_LIMIT} (ditemukan: {limit_value})")
        final_sql = tree.sql(dialect="postgres")
    else:
        # tanpa LIMIT -> sisipkan default (builder bawaan sqlglot)
        tree = tree.limit(DEFAULT_LIMIT)
        final_sql = tree.sql(dialect="postgres")

    logger.debug("sql_guard: query lolos (%d tabel direferensikan)", len(referenced))
    return final_sql


# ============================================================================
# F2.3' Verifier v2 — gerbang offline #1–#4 (docs/PERANCANGAN-PIPELINE-AI-v2.md
# §2 dan §9). verify_sql() mengembalikan Verdict terstruktur; fungsi lama di
# atas tetap utuh demi kompatibilitas pemanggil existing.
# ============================================================================

PROFILE_VERSION = 1

# --- Gerbang 3: profil fitur SQL versioned (docs v2 §9) ---------------------
# Analogi: whitelist "kosakata" SQL reporting. DEFAULT-DENY: node AST yang
# tidak tercantum = tolak. Kosakata baru hanya lewat revisi profil versioned
# + uji katalog serangan + changelog (jangan dibuka diam-diam).
#
# SQL_FEATURE_PROFILE_V1: struktur dict publik (untuk introspeksi/audit);
# implementasi memakai frozenset turunannya di bawah agar cepat.
SQL_FEATURE_PROFILE_V1 = {
    "version": PROFILE_VERSION,
    # konstruksi struktur query yang boleh muncul di AST
    "node_types": [
        # kerangka statement
        "Select", "From", "Join", "Where", "Group", "Order", "Ordered",
        "Limit", "With", "CTE", "Union", "Subquery", "Sub", "Paren",
        "Alias", "Distinct", "Table", "TableAlias", "Column", "Identifier",
        "Star",
        # literal, tipe & predikat
        "Literal", "Boolean", "Null", "DataType", "Interval", "Var",
        "Cast", "Case", "If",   # If = cabang WHEN pada CASE (sqlglot 26)
        "In", "Is", "Between", "Like", "ILike", "Not", "And", "Or",
        # operator perbandingan & aritmetika
        "EQ", "NEQ", "GT", "GTE", "LT", "LTE",
        "Add", "Sub", "Mul", "Div", "Mod", "Neg", "DPipe",
    ],
    # fungsi (kelas ekspresi sqlglot) — reporting umum PostgreSQL
    "functions": [
        # agregasi
        "Count", "Sum", "Avg", "Min", "Max",
        # string
        "Lower", "Upper", "Length", "Concat", "Substring", "Trim",
        "Left", "Right", "Nullif", "Coalesce", "Greatest", "Least",
        # tanggal & numerik
        "Extract", "TimeToStr", "TimestampTrunc",  # to_char(), date_trunc()
        "CurrentDate", "CurrentTimestamp", "CurrentTime",
        "Abs", "Round", "Ceil", "Floor",
    ],
    # fungsi yang sqlglot TIDAK petakan ke kelas ekspresi (tetap exp.Anonymous)
    # tapi aman untuk reporting — wajib eksplisit, sisanya default-deny
    "anonymous_functions": ["replace"],
    # denylist eksplisit — dokumentasi kebijakan + pesan error yang jelas;
    # pencegahan aktual tetap default-deny (fungsi di luar daftar = tolak)
    "denylist_functions": [
        # DoS / manipulasi waktu
        "pg_sleep", "pg_sleep_for", "pg_sleep_until",
        # jaringan antar-DB
        "dblink", "dblink_exec",
        # akses file & large object server
        "pg_read_file", "pg_read_binary_file", "pg_ls_dir", "pg_stat_file",
        "lo_import", "lo_export", "lo_get", "lo_put",
        # administrasi sesi
        "pg_terminate_backend", "pg_cancel_backend", "pg_reload_conf",
    ],
    # konstruksi yang DILARANG eksplisit (v2 §9 awal dilarang)
    "denylist_constructions": [
        "DDL/DML apa pun", "WITH RECURSIVE", "UNION (dedup, non-ALL)",
        "CROSS JOIN", "JOIN tanpa ON", "JOIN di luar peta FK",
        "window function", "HAVING", "OFFSET", "EXISTS", "set-returning func",
    ],
}

_STRUKTUR_WHITELIST = frozenset(SQL_FEATURE_PROFILE_V1["node_types"])
_FUNGSI_WHITELIST = frozenset(SQL_FEATURE_PROFILE_V1["functions"])
_FUNGSI_ANONIM_WHITELIST = frozenset(SQL_FEATURE_PROFILE_V1["anonymous_functions"])
_DENYLIST_FUNGSI = frozenset(SQL_FEATURE_PROFILE_V1["denylist_functions"])

# Node yang dilarang DI POSISI MANA PUN (gerbang #1, defense-in-depth untuk
# DML yang disembunyikan di dalam CTE, mis. WITH x AS (DELETE ...) SELECT ...).
# Dicek per nama tipe (string) agar aman terhadap perbedaan versi sqlglot.
_NODE_TERLARANG_DI_MANA_PUN = frozenset({
    "Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter",
    "Truncate", "Copy", "Set", "Command", "Transaction", "Commit",
    "Rollback", "Grant", "Use", "Analyze", "Vacuum", "LoadData", "Call",
})

# --- Gerbang 4: budget kompleksitas (default; bisa dioverride per panggilan) -
DEFAULT_BUDGET = {
    "kedalaman_ast": 12,   # node terdalam dari root (termasuk daun literal)
    "jumlah_join": 6,
    "jumlah_cte": 4,
    "jumlah_union": 3,
}


def _verdict(ok: bool, gate: str | None, reason: str, **detail) -> dict:
    """Bentuk Verdict seragam: {ok, gate, reason, detail}."""
    return {"ok": ok, "gate": gate, "reason": reason, "detail": detail}


def _norm_identifier(node) -> str:
    """Normalisasi identifier postgres: unquoted -> lowercase (case-insensitive),
    quoted -> dipertahankan persis (case-sensitive)."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node.lower()
    nama = node.name
    return nama if getattr(node, "quoted", False) else nama.lower()


def _nama_cte(cte) -> str:
    alias = cte.args.get("alias")
    return _norm_identifier(alias.this) if alias is not None else cte.alias_or_name.lower()


def _punya_kolom(sets: tuple, nama: str) -> bool:
    """sets = (kolom asli, kolom lowercase). Nama sudah dinormalisasi
    (quoted = exact, unquoted = lowercase)."""
    asli, kecil = sets
    return nama in asli or nama.lower() in kecil


def _dua_set(nama_list) -> tuple:
    daftar = [n for n in nama_list if n]
    return (set(daftar), {n.lower() for n in daftar})


def _kedalaman_ast(node) -> int:
    """Kedalaman = jumlah node terdalam dari root (root dihitung 1)."""
    anak = list(node.iter_expressions())
    if not anak:
        return 1
    return 1 + max(_kedalaman_ast(a) for a in anak)


def _daun_union(union):
    """Kumpulkan Select daun dari pohon UNION (kiri dulu)."""
    if isinstance(union, exp.Union):
        return _daun_union(union.this) + _daun_union(union.expression)
    return [union]


class _KonteksSkema:
    """Resolusi tabel/kolom terhadap schema_config_json untuk gerbang #2.

    Bentuk schema_config mengikuti schema_introspector.introspect_schema():
        {"tables": {nama: {"columns": [{"name", ...}],
                           "foreign_keys": [{"column", "references_table",
                                             "references_column"}], ...}}}
    """

    def __init__(self, tree, schema_config, tabel_dilarang):
        tabels = (schema_config or {}).get("tables", {}) or {}
        self.kolom_tabel: dict[str, tuple] = {}
        for nama, info in tabels.items():
            self.kolom_tabel[nama.lower()] = _dua_set(
                [c.get("name", "") for c in info.get("columns", [])])
        # peta FK: nama tabel -> set tabel yang dirujuk FK-nya
        self.fk_tabel: dict[str, set] = {}
        for nama, info in tabels.items():
            rujukan = {
                fk.get("references_table", "").lower()
                for fk in info.get("foreign_keys", []) if fk.get("references_table")
            }
            if rujukan:
                self.fk_tabel[nama.lower()] = rujukan
        self.dilarang = {t.lower() for t in (tabel_dilarang or [])}

        # CTE: nama -> body AST (Select/Union); nama CTE = referensi lokal
        self.cte_body: dict[str, object] = {}
        for w in tree.find_all(exp.With):
            for cte in w.expressions:
                self.cte_body[_nama_cte(cte)] = cte.this
        # semua node Table di query (untuk daftar tabel direferensikan)
        self.tree_sumber: list = list(tree.find_all(exp.Table))

        self._cte_output: dict[str, tuple | None] = {}
        self._cte_fallback: dict[str, frozenset] = {}
        self._sub_output: dict[int, tuple | None] = {}
        self._sub_fallback: dict[int, frozenset] = {}
        self._scope_sumber: dict[int, list] = {}
        self._scope_alias: dict[int, dict] = {}

    # -- gerbang 2a: tabel ----------------------------------------------------
    def cek_tabel(self, tb) -> str | None:
        """Pesan pelanggaran bila referensi tabel tidak valid, None bila OK."""
        if tb.db or tb.catalog:
            return (f"referensi skema non-public tidak diizinkan: "
                    f"{tb.sql(dialect='postgres')}")
        nama = _norm_identifier(tb.this)
        if nama in self.cte_body:
            return None  # referensi CTE lokal — body-nya divalidasi terpisah
        if nama in self.dilarang:
            return (f"tabel '{nama}' ada di daftar tabel_dilarang "
                    f"(knowledge base)")
        if nama not in self.kolom_tabel:
            return f"tabel di luar whitelist: {nama}"
        return None

    # -- sumber scope: ("tabel", nama) | ("cte", nama) | ("sub", Subquery) ----
    def _sumber_dari_node(self, node):
        if isinstance(node, exp.Table):
            nama = _norm_identifier(node.this)
            return ("cte", nama) if nama in self.cte_body else ("tabel", nama)
        if isinstance(node, exp.Subquery):
            return ("sub", node)
        return None

    def _tabel_dalam(self, body) -> frozenset:
        """Tabel basis (non-CTE, terdaftar di skema) di dalam sebuah body."""
        hasil = set()
        for tb in body.find_all(exp.Table):
            nama = _norm_identifier(tb.this)
            if nama not in self.cte_body and nama in self.kolom_tabel:
                hasil.add(nama)
        return frozenset(hasil)

    def _infer_output(self, body):
        """Kolom output sebuah Select/Union bila semua proyeksinya bernama;
        None bila ada `*` / ekspresi tanpa alias (tidak bisa diinfer)."""
        if isinstance(body, exp.Select):
            hasil = []
            for e in body.expressions:
                if isinstance(e, exp.Star) or isinstance(getattr(e, "this", None), exp.Star):
                    return None  # SELECT * / t.* — output tidak bisa diinfer
                if not e.output_name:
                    return None
                hasil.append(e.output_name)
            return _dua_set(hasil)
        if isinstance(body, exp.Union):
            return self._infer_output(body.this)
        return None

    def _kolom_sumber(self, sumber) -> tuple:
        """(kolom_pasti, kolom_fallback) dari satu sumber scope.
        Fallback dipakai bila output sumber (CTE/subquery ber-`*`) tidak bisa
        diinfer: gabungan kolom tabel basis di dalam body — resolusi pastinya
        diserahkan ke gerbang #5 (EXPLAIN) yang mengecek DB sungguhan."""
        jenis, kunci = sumber
        kosong = (set(), set())
        if jenis == "tabel":
            return (self.kolom_tabel.get(kunci, kosong), kosong)
        if jenis == "cte":
            if kunci not in self._cte_output:
                body = self.cte_body[kunci]
                self._cte_output[kunci] = self._infer_output(body)
                self._cte_fallback[kunci] = self._tabel_dalam(body)
            pasti = self._cte_output[kunci]
            if pasti is not None:
                return (pasti, kosong)
            fallback = set()
            for t in self._cte_fallback[kunci]:
                gab = self.kolom_tabel.get(t)
                if gab:
                    fallback |= gab[0]
            return (kosong, _dua_set(fallback))
        # subquery di FROM/JOIN
        if id(kunci) not in self._sub_output:
            body = kunci.this
            self._sub_output[id(kunci)] = self._infer_output(body)
            self._sub_fallback[id(kunci)] = self._tabel_dalam(body)
        pasti = self._sub_output[id(kunci)]
        if pasti is not None:
            return (pasti, kosong)
        fallback = set()
        for t in self._sub_fallback[id(kunci)]:
            gab = self.kolom_tabel.get(t)
            if gab:
                fallback |= gab[0]
        return (kosong, _dua_set(fallback))

    def _sumber_scope(self, select_node) -> list:
        key = id(select_node)
        if key not in self._scope_sumber:
            sumber = []
            frm = select_node.args.get("from")
            if frm is not None and frm.this is not None:
                s = self._sumber_dari_node(frm.this)
                if s:
                    sumber.append(s)
            for j in select_node.args.get("joins") or []:
                s = self._sumber_dari_node(j.this)
                if s:
                    sumber.append(s)
            self._scope_sumber[key] = sumber
        return self._scope_sumber[key]

    def _alias_scope(self, select_node) -> dict:
        """Alias -> sumber untuk satu scope (kualifikasi resolved per-scope,
        bukan global, supaya alias sama di scope berbeda tidak tertukar)."""
        key = id(select_node)
        if key not in self._scope_alias:
            hasil: dict[str, tuple] = {}
            frm = select_node.args.get("from")
            node_sumber = []
            if frm is not None and frm.this is not None:
                node_sumber.append(frm.this)
            for j in select_node.args.get("joins") or []:
                node_sumber.append(j.this)
            for node in node_sumber:
                s = self._sumber_dari_node(node)
                if s is None:
                    continue
                alias = (getattr(node, "alias", "") or "").lower()
                if alias:
                    hasil[alias] = s
                elif isinstance(node, exp.Table):
                    # tanpa alias: tabel bisa dikualifikasi pakai namanya sendiri
                    hasil[s[1].lower()] = s
            self._scope_alias[key] = hasil
        return self._scope_alias[key]

    def _select_di_atas(self, select_node):
        node = select_node.parent
        while node is not None and not isinstance(node, exp.Select):
            node = node.parent
        return node

    def _resolve_qualifier(self, col, kual: str):
        """Cari sumber untuk kualifikasi alias/tabel, per-scope + korrelasi
        ke scope luar. Berhenti di batas CTE (body CTE tidak melihat FROM
        query luarnya)."""
        scope = col.find_ancestor(exp.Select)
        while scope is not None:
            amap = self._alias_scope(scope)
            if kual in amap:
                return amap[kual]
            if isinstance(scope.parent, exp.CTE):
                return None
            scope = self._select_di_atas(scope)
        # fallback longgar: kualifikasi = nama tabel yang dipakai di query
        if kual in {s[1] for s in self._semua_sumber() if s[0] == "tabel"}:
            return ("tabel", kual)
        return None

    def _semua_sumber(self) -> list:
        hasil = []
        for s in self.tree_sumber:
            m = self._sumber_dari_node(s)
            if m:
                hasil.append(m)
        return hasil

    def cek_kolom(self, col) -> str | None:
        """Pesan pelanggaran bila referensi kolom tidak valid, None bila OK."""
        if isinstance(col.this, exp.Star):
            return None  # p.* — tabelnya sudah dicek di cek_tabel
        nama_kol = _norm_identifier(col.this)
        if not nama_kol:
            return None
        kual_node = col.args.get("table")
        if kual_node is not None:
            kual = _norm_identifier(kual_node)
            return self._cek_qualified(col, kual, nama_kol)
        return self._cek_unqualified(col, nama_kol)

    def _cek_qualified(self, col, kual: str, nama_kol: str) -> str | None:
        sumber = self._resolve_qualifier(col, kual)
        if sumber is None:
            return f"kualifikasi '{kual}' tidak dikenal (kolom '{nama_kol}')"
        pasti, fallback = self._kolom_sumber(sumber)
        if _punya_kolom(pasti, nama_kol) or _punya_kolom(fallback, nama_kol):
            return None
        return (f"kolom '{kual}.{nama_kol}' tidak ada di objek "
                f"yang diizinkan")

    def _cek_unqualified(self, col, nama_kol: str) -> str | None:
        # (1) ORDER BY boleh merujuk alias proyeksi SELECT yang sama
        order_node = col.find_ancestor(exp.Order)
        if order_node is not None:
            pemilik = order_node.parent
            if isinstance(pemilik, exp.Select):
                alias_proyeksi = {
                    e.output_name.lower()
                    for e in pemilik.expressions if e.output_name
                }
                if nama_kol.lower() in alias_proyeksi:
                    return None
            elif isinstance(pemilik, exp.Union):
                # ORDER BY di akar UNION merujuk nama output union
                daun = _daun_union(pemilik)
                nama_out = self._infer_output(daun[0])
                if nama_out is not None and _punya_kolom(nama_out, nama_kol):
                    return None
        # (2) resolusi per-scope dengan deteksi ambiguitas + korrelasi
        scope = col.find_ancestor(exp.Select)
        while scope is not None:
            cocok = []
            ada_fallback = False
            for s in self._sumber_scope(scope):
                pasti, fallback = self._kolom_sumber(s)
                if _punya_kolom(pasti, nama_kol):
                    cocok.append(s)
                elif _punya_kolom(fallback, nama_kol):
                    ada_fallback = True
            if len(cocok) > 1:
                kandidat = sorted({s[1] for s in cocok})
                return (f"kolom '{nama_kol}' ambigu (muncul di: "
                        f"{', '.join(map(str, kandidat))}); kualifikasi "
                        f"dengan alias/tabel")
            if len(cocok) == 1:
                return None
            if ada_fallback:
                return None  # tak pasti — gerbang #5 (EXPLAIN) yang memutuskan
            if isinstance(scope.parent, exp.CTE):
                break  # body CTE tidak berkorelasi ke scope luar
            scope = self._select_di_atas(scope)
        return f"kolom '{nama_kol}' tidak ada di tabel yang diizinkan"

    # -- peta FK untuk gerbang 3 ----------------------------------------------
    def fk_terhubung(self, a: str, b: str) -> bool:
        """Dua tabel terhubung bila salah satunya punya FK ke yang lain."""
        return b in self.fk_tabel.get(a, set()) or a in self.fk_tabel.get(b, set())


def verify_sql(sql: str, schema_config: dict,
               kb_forbidden=None, budget: dict | None = None) -> dict:
    """Verifikasi offline gerbang #1–#4 (F2.3' Verifier v2) — TANPA DB.

    Args:
        sql: teks query dari user/planner (harus satu statement SELECT).
        schema_config: bentuk `tenants.schema_config_json` (lihat
            schema_introspector.introspect_schema).
        kb_forbidden: `tabel_dilarang` dari knowledge base tenant (opsional).
        budget: override budget kompleksitas; kunci yang tidak diisi memakai
            DEFAULT_BUDGET (kedalaman_ast=12, jumlah_join=6, jumlah_cte=4,
            jumlah_union=3).

    Returns:
        Verdict dict {ok, gate, reason, detail}:
        - ok=True  : gate=None, detail["final_sql"] SIAP DIEKSEKUSI (LIMIT
          500 dipaksa bila belum ada), detail["tabel_direferensikan"] untuk
          audit/fingerprint SQL Memory.
        - ok=False : gate = "bentuk"|"whitelist"|"profil"|"budget", reason
          siap ditampilkan/diaudit/umpan-balik self-repair.

    Catatan pemanggil (F2.4): verdict WAJIB dicatat ke audit log (ok/gate/
    reason); eksekusi tetap harus dalam gerbang #6 (transaksi READ ONLY +
    statement_timeout + user DB read-only). EXPLAIN pre-flight (gerbang #5)
    dijalankan oleh app.services.query_verifier.verify_query, bukan di sini.
    """
    anggaran = {**DEFAULT_BUDGET, **(budget or {})}

    # --- Gerbang 1: parser & bentuk ------------------------------------------
    if not sql or not sql.strip():
        return _verdict(False, "bentuk", "Query kosong")
    try:
        statements = sqlglot.parse(sql, read="postgres")
    except ParseError as e:
        return _verdict(False, "bentuk", f"SQL tidak bisa diparse: {e}")

    statements = [s for s in statements if s is not None]
    if not statements:
        return _verdict(False, "bentuk", "Tidak ada statement yang bisa dievaluasi")
    if len(statements) > 1:
        return _verdict(False, "bentuk", "Multi-statement tidak diizinkan")

    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.Union)):
        kind = type(tree).__name__
        return _verdict(False, "bentuk", f"Hanya SELECT yang diizinkan (ditemukan: {kind})")

    for n in tree.walk():
        if type(n).__name__ in _NODE_TERLARANG_DI_MANA_PUN:
            return _verdict(False, "bentuk",
                            f"konstruksi dilarang di posisi mana pun: {type(n).__name__}")
    for s in tree.find_all(exp.Select):
        if s.args.get("into"):
            return _verdict(False, "bentuk", "SELECT INTO tidak diizinkan")
        if s.args.get("locks"):
            return _verdict(False, "bentuk",
                            "lock clause (FOR UPDATE/SHARE) tidak diizinkan")

    # LIMIT policy v1 dipertahankan: cap 500 di SEMUA exp.Limit (root maupun
    # subquery); bila akar tanpa LIMIT, default disisipkan di akhir.
    for lim in tree.find_all(exp.Limit):
        e = lim.expression
        if not isinstance(e, exp.Literal) or not e.is_int:
            return _verdict(False, "bentuk", "LIMIT harus berupa angka tetap")
        if int(e.this) > MAX_LIMIT:
            return _verdict(False, "bentuk",
                            f"LIMIT maksimal {MAX_LIMIT} (ditemukan: {int(e.this)})")

    # --- Gerbang 2: whitelist objek menyeluruh (tabel & kolom) ---------------
    ctx = _KonteksSkema(tree, schema_config, kb_forbidden)
    for tb in tree.find_all(exp.Table):
        pesan = ctx.cek_tabel(tb)
        if pesan:
            return _verdict(False, "whitelist", pesan, objek=tb.sql(dialect="postgres"))
    for col in tree.find_all(exp.Column):
        pesan = ctx.cek_kolom(col)
        if pesan:
            return _verdict(False, "whitelist", pesan, objek=nama_objek(col))

    # --- Gerbang 3: profil fitur SQL (SQL_FEATURE_PROFILE_V1) ----------------
    pesan = _verifikasi_profil(tree, ctx)
    if pesan:
        return _verdict(False, "profil", pesan)

    # --- Gerbang 4: budget kompleksitas --------------------------------------
    pesan = _verifikasi_budget(tree, anggaran)
    if pesan:
        return _verdict(False, "budget", pesan)

    # --- LIMIT wajib pada akar (perilaku v1: paksa cap 500) ------------------
    if tree.args.get("limit") is None:
        tree = tree.limit(DEFAULT_LIMIT)
    final_sql = tree.sql(dialect="postgres")

    tabel_ref = sorted({_norm_identifier(tb.this)
                        for tb in ctx.tree_sumber
                        if _norm_identifier(tb.this) not in ctx.cte_body})
    logger.debug("verifier: query lolos gerbang #1-#4 (%d tabel)", len(tabel_ref))
    return _verdict(True, None, "lolos semua gerbang offline",
                    final_sql=final_sql,
                    tabel_direferensikan=tabel_ref,
                    profil=f"SQL_FEATURE_PROFILE_V{PROFILE_VERSION}")


def nama_objek(col) -> str:
    """Nama kolom yang ramah audit, mis. 'p.harga_deal' atau 'merek'."""
    kual = _norm_identifier(col.args.get("table"))
    nama = _norm_identifier(col.this)
    return f"{kual}.{nama}" if kual else nama


def _verifikasi_profil(tree, ctx: _KonteksSkema) -> str | None:
    """Gerbang 3 — SQL_FEATURE_PROFILE_V1, default-deny. None = lolos."""
    # CTE rekursif dilarang (v2 §9: RECURSIVE tanpa batas kedalaman)
    for w in tree.find_all(exp.With):
        if w.args.get("recursive"):
            return "WITH RECURSIVE tidak diizinkan pada profil v1"

    # UNION: hanya UNION ALL, dan jumlah kolom antar cabang harus sama
    for u in tree.find_all(exp.Union):
        if u.args.get("distinct"):
            return "hanya UNION ALL yang diizinkan (UNION dedup di luar profil)"
        hitungan = {len(d.expressions) for d in _daun_union(u)}
        if len(hitungan) > 1:
            return "kolom hasil UNION ALL harus sama jumlahnya antar cabang"

    # JOIN: wajib ON/USING, tanpa CROSS, dan terhubung lewat peta FK skema
    for j in tree.find_all(exp.Join):
        if j.kind == "CROSS":
            return "CROSS JOIN tidak diizinkan (produk kartesian)"
        if j.args.get("on") is None and j.args.get("using") is None:
            return "JOIN wajib punya kondisi ON/USING"
        pesan = _cek_join_fk(j, ctx)
        if pesan:
            return pesan

    # whitelist node: apa pun yang tidak tercantum di profil = tolak
    for n in tree.walk():
        tipe = type(n).__name__
        if tipe in _STRUKTUR_WHITELIST or tipe in _FUNGSI_WHITELIST:
            continue
        if isinstance(n, exp.Anonymous):
            nama = n.name.lower()
            if nama in _FUNGSI_ANONIM_WHITELIST:
                continue
            if nama in _DENYLIST_FUNGSI:
                return f"fungsi dilarang (profil v{PROFILE_VERSION}): {nama}"
            return f"fungsi di luar profil (v{PROFILE_VERSION}): {nama}"
        return f"konstruksi di luar profil (v{PROFILE_VERSION}): {tipe}"
    return None


def _sisi_join(j):
    """(node_kiri, node_kanan) untuk satu Join — kiri = sumber tepat sebelum
    join ini dalam scope yang sama."""
    sel = j.find_ancestor(exp.Select)
    joins = sel.args.get("joins") or []
    idx = next((i for i, jj in enumerate(joins) if jj is j), None)
    if idx is None or sel.args.get("from") is None:
        return None, j.this
    kiri = sel.args["from"].this if idx == 0 else joins[idx - 1].this
    return kiri, j.this


def _basis_tabel(node, ctx: _KonteksSkema) -> str | None:
    """Nama tabel basis dari sisi join; None bila CTE/subquery (tidak bisa
    dicek FK — biayanya ditangani gerbang #4/#5)."""
    if isinstance(node, exp.Table):
        nama = _norm_identifier(node.this)
        if nama in ctx.cte_body or nama not in ctx.kolom_tabel:
            return None
        return nama
    return None


def _cek_join_fk(j, ctx: _KonteksSkema) -> str | None:
    kiri, kanan = _sisi_join(j)
    a = _basis_tabel(kiri, ctx)
    b = _basis_tabel(kanan, ctx)
    if a is None or b is None:
        return None
    if a == b:  # self-join diizinkan
        return None
    if not ctx.fk_terhubung(a, b):
        return (f"JOIN antara '{a}' dan '{b}' tidak terhubung foreign key "
                f"(JOIN wajib lewat peta FK skema)")
    return None


def _verifikasi_budget(tree, anggaran: dict) -> str | None:
    """Gerbang 4 — budget kompleksitas (nalar-DoS). None = lolos."""
    kedalaman = _kedalaman_ast(tree)
    if kedalaman > anggaran["kedalaman_ast"]:
        return (f"kedalaman AST {kedalaman} melebihi budget "
                f"{anggaran['kedalaman_ast']}")
    jumlah_join = len(list(tree.find_all(exp.Join)))
    if jumlah_join > anggaran["jumlah_join"]:
        return (f"jumlah join {jumlah_join} melebihi budget "
                f"{anggaran['jumlah_join']}")
    jumlah_cte = sum(len(w.expressions) for w in tree.find_all(exp.With))
    if jumlah_cte > anggaran["jumlah_cte"]:
        return (f"jumlah CTE {jumlah_cte} melebihi budget "
                f"{anggaran['jumlah_cte']}")
    jumlah_union = len(list(tree.find_all(exp.Union)))
    if jumlah_union > anggaran["jumlah_union"]:
        return (f"jumlah UNION {jumlah_union} melebihi budget "
                f"{anggaran['jumlah_union']}")
    return None
