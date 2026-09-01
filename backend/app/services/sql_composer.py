"""
F2.2 — SQL Composer Tier 1: rencana JSON → SQL deterministik (TANPA LLM).

Posisi dalam pipeline (docs/PERANCANGAN-PIPELINE-AI-v2.md §1):

    F3: LLM planner → rencana JSON → COMPOSER (modul ini)
        → SQL parameterized → verifier (sql_guard/query_verifier) → executor

Composer murni fungsi: TANPA LLM, TANPA DB, TANPA I/O. SQL dibangun
deterministik — rencana + `now` yang sama menghasilkan SQL byte-identik.

== Kontrak rencana (plan) — disepakati dengan planner F3 ==

{
  "tables":   ["penjualan", "kendaraan"],   // >=1; tables[0] tabel utama (FROM);
                                            // tabel lain wajib terhubung FK path
  "columns":  ["penjualan.tanggal",
               {"agg": "SUM", "column": "penjualan.harga_deal", "alias": "omzet"}],
  "filters":  [{"column": "penjualan.metode_pembayaran",
                "op": "eq", "value": "cash"}],
  "time_range": {"field": "penjualan.tanggal", "preset": "this_month"},
  "group_by": ["penjualan.tanggal"],        // opsional
  "order_by": [{"by": "omzet", "dir": "DESC"}],  // opsional; by = alias SELECT
                                            // atau "tabel.kolom"; dir ASC|DESC
  "limit": 50,                              // opsional; clamp 1..500; default 200
  "distinct": false,                        // opsional boolean

  // field presentational — boleh ada, TIDAK memengaruhi SQL (untuk presenter):
  "intent": "...", "chart_hint": "...", "answer_style": "..."
}

- columns   : string "tabel.kolom" ATAU objek {agg, column, alias?}.
              agg hanya SUM/COUNT/AVG/MIN/MAX; column "*" hanya untuk COUNT
              (COUNT(*)). alias opsional, pola [a-z_][a-z0-9_]*, wajib unik.
- filters.op: eq|neq|gt|gte|lt|lte|like|in|between|is_null|is_not_null.
              in -> list tak kosong; between -> list tepat 2; is_null/
              is_not_null tanpa value; like -> string pola (planner yang
              menyertakan wildcard %); operator skalar lain -> value scalar
              (None ditolak: gunakan is_null).
- time_range: {"field", "preset"} ATAU {"field", "from", "to"} (ISO date atau
              ISO datetime). preset: this_month|last_month|this_week|
              last_week|last_7_days|last_30_days|this_year. field wajib kolom
              bertipe date/timestamp (dicek dari schema_config).
- order_by  : by = alias SELECT ATAU "tabel.kolom" (alias menang bila bentrok
              nama, sama seperti PostgreSQL); dir ASC|DESC (default ASC).
- limit     : clamp 1..500 (sinkron budget verifier); default 200.

Semua referensi kolom WAJIB terkualifikasi "tabel.kolom" dan tabelnya harus
tercantum di plan.tables (kolom dari tabel perantara FK path tidak bisa
direferensikan tanpa mencantumkan tabelnya).

== Keputusan teknis ==

1. Parameterisasi penuh. SEMUA nilai filter/time_range menjadi parameter
   $1..$n (gaya asyncpg); SQL tidak pernah memuat literal nilai. Satu-satunya
   angka literal adalah LIMIT — sql_guard menuntut LIMIT literal (gerbang
   "bentuk": "LIMIT harus berupa angka tetap"). Nilai urut sesuai kemunculan
   di SQL: filter (urut rencana) lebih dulu, lalu time_range.

2. Zona waktu (TZ) adalah keputusan pemanggil. Preset dihitung dari `now`
   apa adanya (wall-clock sesuai `now`; naive/aware sama-sama diterima —
   composer tidak mengonversi zona). Preset = setengah-terbuka [mulai, sampai)
   (aman untuk kolom timestamp); custom from/to = tertutup [from, to].
   last_7_days/last_30_days = 7/30 hari kalender TERMASUK hari ini.
   Pekan mengikuti ISO (Senin awal pekan).

3. JOIN via FK path. Graph FK dibaca tak berarah (a->b atau b->a, konsisten
   dengan sql_guard._KonteksSkema.fk_terhubung). BFS terpendek dari tables[0];
   jalur boleh melewati tabel perantara yang tidak tercantum di plan.tables —
   otomatis di-join dan dilaporkan di used_tables. Pemilihan jalur & kolom ON
   deterministik (tetangga dan FK diurutkan nama). Tabel duplikat/self-join
   tidak didukung Tier 1. Jumlah join dicek terhadap DEFAULT_BUDGET verifier.

4. Semantik SELECT ketat (SQL hasil harus valid PostgreSQL, bukan hanya aman):
   bila ada agregasi, kolom plain wajib masuk group_by; bila tidak ada
   group_by, select tidak boleh mencampur agregat dan kolom plain; order_by
   kolom wajib ada di group_by (bila group_by dipakai), wajib alias (bila
   agregasi tanpa group_by), dan wajib masuk select list (bila DISTINCT).

5. Belt-and-suspenders. compose_sql WAJIB menjalankan verify_sql() atas SQL
   hasil compose sebelum mengembalikannya; gagal = bug composer -> raise
   SqlComposerError (bukan lubang keamanan). Catatan: verify_sql saat ini
   menolak SQL ber-placeholder $n karena SQL_FEATURE_PROFILE_V1 belum
   mendaftar node `Parameter` milik sqlglot — padahal nilai memang tidak pernah
   ada di SQL (semua jadi parameter driver). Karena itu verifikasi dijalankan
   atas salinan dengan placeholder diganti NULL (lihat ganti_placeholder_null):
   seluruh gerbang (bentuk/whitelist/profil/budget) tetap memeriksa struktur
   sungguhan; nilai tidak ada untuk diperiksa. Bila profil versi berikutnya
   mendaftar `Parameter`, pemanggilan ini cukup diarahkan ke SQL mentah tanpa
   mengubah bagian lain composer.
"""
import re
from datetime import date, datetime, timedelta

from app.services.sql_guard import DEFAULT_BUDGET, verify_sql

__all__ = [
    "SqlComposerError",
    "validate_plan",
    "compose_sql",
    "ganti_placeholder_null",
    "AGGREGASI_DIIZINKAN",
    "OPERATOR_DIIZINKAN",
    "PRESET_WAKTU",
    "BATAS_LIMIT",
    "LIMIT_BAWAAN",
    "FIELD_PRESENTASIONAL",
]

# --- Whitelist kosakata rencana (default-deny, konsisten profil verifier) ---
AGGREGASI_DIIZINKAN = frozenset({"SUM", "COUNT", "AVG", "MIN", "MAX"})
OPERATOR_DIIZINKAN = frozenset({
    "eq", "neq", "gt", "gte", "lt", "lte",
    "like", "in", "between", "is_null", "is_not_null",
})
PRESET_WAKTU = frozenset({
    "this_month", "last_month", "this_week", "last_week",
    "last_7_days", "last_30_days", "this_year",
})
FIELD_PRESENTASIONAL = ("intent", "chart_hint", "answer_style")

_FIELD_DIKENAL = frozenset({
    "tables", "columns", "filters", "time_range", "group_by", "order_by",
    "limit", "distinct", *FIELD_PRESENTASIONAL,
})

# Sinkron dengan sql_guard: LIMIT literal, cap 500 (DEFAULT_BUDGET/MAX_LIMIT)
BATAS_LIMIT = (1, 500)
LIMIT_BAWAAN = 200

# alias hanya huruf kecil/underscore di awal, lalu [a-z0-9_] (kontrak F3)
_ALIAS_RE = re.compile(r"[a-z_][a-z0-9_]*")
# placeholder $n (nilai filter/time_range) — hanya muncul di posisi nilai
# karena SQL dibangun sendiri dari identifier terwhitelist
_PLACEHOLDER_RE = re.compile(r"\$\d+")

_OP_SQL = {"eq": "=", "neq": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}


class SqlComposerError(ValueError):
    """Rencana tidak valid, atau SQL hasil compose ditolak verifier (bug
    composer). Subclass ValueError agar penanganan HTTP 400 yang sudah ada
    tetap bekerja."""


# ============================================================================
# Util identifier & skema
# ============================================================================
def _ident_aman(nama) -> bool:
    """Identifier tidak boleh kosong / mengandung kutip-ganda / NUL
    (konsisten _nama_tabel_aman schema_introspector)."""
    return isinstance(nama, str) and bool(nama) and '"' not in nama and "\x00" not in nama


def _q(nama: str) -> str:
    """Kutip identifier dengan kutip-ganda (nama berasal dari whitelist skema)."""
    return '"' + nama + '"'


def _kolom_sql(ref: str) -> str:
    """'tabel.kolom' -> '"tabel"."kolom"' (ref sudah divalidasi validate_plan)."""
    t, k = ref.split(".")
    return f"{_q(t)}.{_q(k)}"


def _schema_tables(schema_config, errors: list) -> dict:
    tabels = schema_config.get("tables") if isinstance(schema_config, dict) else None
    if not isinstance(tabels, dict) or not tabels:
        errors.append("schema_config tidak memiliki 'tables' yang sah")
        return {}
    return tabels


def _tipe_kolom(tabels: dict, tabel: str, kolom: str) -> str:
    for c in tabels[tabel].get("columns", []):
        if c.get("name") == kolom:
            return c.get("type", "") or ""
    return ""


# ============================================================================
# F2.2a — validate_plan: validasi ketat rencana JSON
# ============================================================================
def validate_plan(plan, schema_config) -> tuple[dict | None, list[str]]:
    """Validasi ketat rencana JSON terhadap skema tenant.

    Returns:
        (clean_plan, errors). Bila errors tidak kosong -> clean_plan = None.
        clean_plan JSON-safe (agg/dir huruf besar, is_null tanpa "value",
        field presentational dipertahankan) — siap compose_sql maupun disimpan
        ke sql_memory.rencana_json.

    Semua pelanggaran dikumpulkan (bukan fail-first) agar planner F3 mendapat
    umpan balik lengkap dalam satu putaran self-repair.
    """
    errors: list[str] = []
    if not isinstance(plan, dict):
        return None, ["rencana harus objek JSON (dict)"]
    tabels = _schema_tables(schema_config, errors)

    # --- field top-level: default-deny; presentational dikenal tapi tidak
    #     memengaruhi SQL ---
    for f in plan:
        if f not in _FIELD_DIKENAL:
            errors.append(f"field tak dikenal: '{f}'")

    # --- tables ---
    tables_ok = set()  # tabel valid di dalam rencana
    tables = plan.get("tables")
    if not isinstance(tables, list) or not tables:
        errors.append("tables wajib list berisi minimal satu nama tabel")
    else:
        sudah = set()
        for i, t in enumerate(tables):
            if not _ident_aman(t):
                errors.append(f"tables[{i}] bukan nama tabel sah: {t!r}")
                continue
            if t in sudah:
                errors.append(f"tabel duplikat dalam rencana: '{t}' (self-join "
                              f"tidak didukung Tier 1)")
                continue
            sudah.add(t)
            if t not in tabels:
                errors.append(f"tabel '{t}' tidak ada di skema")
                continue
            tables_ok.add(t)

    def cek_ref(ref, konteks: str):
        """Validasi referensi 'tabel.kolom'. Return (tabel, kolom) / None."""
        if not isinstance(ref, str) or ref.count(".") != 1:
            errors.append(f"{konteks}: referensi kolom harus 'tabel.kolom' "
                          f"(dapat: {ref!r})")
            return None
        t, k = ref.split(".")
        if not _ident_aman(t) or not _ident_aman(k):
            errors.append(f"{konteks}: nama identifier tidak sah: {ref!r}")
            return None
        if t not in tables_ok:
            if t in tabels:
                errors.append(f"{konteks}: kolom '{ref}' merujuk tabel di luar "
                              f"rencana (tambahkan '{t}' ke tables)")
            else:
                errors.append(f"{konteks}: tabel '{t}' tidak ada di skema")
            return None
        if not any(c.get("name") == k for c in tabels[t].get("columns", [])):
            errors.append(f"{konteks}: kolom '{k}' tidak ada di tabel '{t}'")
            return None
        return t, k

    # --- columns ---
    columns = plan.get("columns")
    clean_columns: list = []
    alias_map: dict[str, int] = {}
    if not isinstance(columns, list) or not columns:
        errors.append("columns wajib list berisi minimal satu kolom")
    else:
        for i, col in enumerate(columns):
            if isinstance(col, str):
                if cek_ref(col, f"columns[{i}]"):
                    clean_columns.append(col)
                continue
            if not isinstance(col, dict):
                errors.append(f"columns[{i}]: entri harus string 'tabel.kolom' "
                              f"atau objek {{agg, column, alias?}}")
                continue
            kunci = set(col)
            if "agg" not in kunci or "column" not in kunci or \
                    not kunci <= {"agg", "column", "alias"}:
                errors.append(f"columns[{i}]: objek kolom hanya boleh "
                              f"{{agg, column, alias?}}")
                continue
            agg = col["agg"].upper() if isinstance(col["agg"], str) else None
            if agg not in AGGREGASI_DIIZINKAN:
                errors.append(f"columns[{i}]: agg hanya "
                              f"{', '.join(sorted(AGGREGASI_DIIZINKAN))} "
                              f"(dapat: {col['agg']!r})")
                continue
            # alias: pola ketat + unik
            alias = col.get("alias")
            if alias is not None:
                if not (isinstance(alias, str) and _ALIAS_RE.fullmatch(alias)):
                    errors.append(f"columns[{i}]: alias '{alias}' tidak cocok "
                                  f"pola [a-z_][a-z0-9_]*")
                    continue
                if alias in alias_map:
                    errors.append(f"columns[{i}]: alias duplikat: '{alias}'")
                    continue
                alias_map[alias] = i
            if col["column"] == "*":
                if agg != "COUNT":
                    errors.append(f"columns[{i}]: column '*' hanya untuk "
                                  f"agg COUNT")
                    continue
                bersih = {"agg": agg, "column": "*"}
            else:
                if not cek_ref(col["column"], f"columns[{i}].column"):
                    continue
                bersih = {"agg": agg, "column": col["column"]}
            if alias is not None:
                bersih["alias"] = alias
            clean_columns.append(bersih)

    # --- filters ---
    clean_filters: list = []
    filters = plan.get("filters")
    if filters is not None:
        if not isinstance(filters, list):
            errors.append("filters wajib list")
        else:
            for i, f in enumerate(filters):
                kesalahan = _validasi_filter(f, i, cek_ref)
                if kesalahan:
                    errors.extend(kesalahan)
                    continue
                bersih = {"column": f["column"], "op": f["op"]}
                # cek ke rencana asli `f` (bukan `bersih` yang baru dibuat
                # tanpa "value") — kalau tidak, nilai filter terbuang
                if "value" in f and f["op"] not in ("is_null", "is_not_null"):
                    bersih["value"] = f["value"]
                clean_filters.append(bersih)

    # --- time_range ---
    clean_tr = None
    tr = plan.get("time_range")
    if tr is not None:
        if not isinstance(tr, dict):
            errors.append("time_range wajib objek {field, preset} atau "
                          "{field, from, to}")
        else:
            kunci = set(tr)
            if "field" not in kunci:
                errors.append("time_range wajib punya 'field'")
            elif not kunci <= {"field", "preset", "from", "to"}:
                errors.append(f"time_range: field tak dikenal "
                              f"{sorted(kunci - {'field', 'preset', 'from', 'to'})}")
            else:
                ref = cek_ref(tr["field"], "time_range.field")
                if ref is not None:
                    tipe = _tipe_kolom(tabels, ref[0], ref[1])
                    if "date" not in tipe and "timestamp" not in tipe:
                        errors.append(f"time_range.field '{tr['field']}' wajib "
                                      f"bertipe tanggal/timestamp (dapat: "
                                      f"{tipe or '?'})")
                punya_preset = "preset" in kunci
                punya_range = "from" in kunci or "to" in kunci
                if punya_preset and punya_range:
                    errors.append("time_range: pilih preset ATAU from/to, "
                                  "bukan keduanya")
                elif punya_preset:
                    # guard str: preset unhashable jangan bikin TypeError
                    # (sama seperti guard op di _validasi_filter)
                    if not isinstance(tr["preset"], str) or \
                            tr["preset"] not in PRESET_WAKTU:
                        errors.append(f"time_range.preset tidak dikenal: "
                                      f"{tr['preset']!r} (pilihan: "
                                      f"{', '.join(sorted(PRESET_WAKTU))})")
                    else:
                        clean_tr = {"field": tr["field"], "preset": tr["preset"]}
                elif punya_range:
                    if "from" not in kunci or "to" not in kunci:
                        errors.append("time_range: from dan to wajib bersamaan")
                    else:
                        d1 = _parse_iso(tr["from"], "time_range.from", errors)
                        d2 = _parse_iso(tr["to"], "time_range.to", errors)
                        if d1 is not None and d2 is not None:
                            try:
                                terurut = d1 <= d2
                            except TypeError:
                                errors.append("time_range: from dan to harus "
                                              "se-tipe (date atau datetime)")
                            else:
                                if not terurut:
                                    errors.append("time_range: from harus <= to")
                                else:
                                    clean_tr = {"field": tr["field"],
                                                "from": tr["from"],
                                                "to": tr["to"]}
                else:
                    errors.append("time_range wajib punya preset atau from/to")

    # --- group_by ---
    group_refs: set[str] = set()
    group_by = plan.get("group_by")
    if group_by is not None:
        if not isinstance(group_by, list) or not group_by:
            errors.append("group_by wajib list 'tabel.kolom' tidak kosong")
        else:
            for i, ref in enumerate(group_by):
                if cek_ref(ref, f"group_by[{i}]") is None:
                    continue
                if ref in group_refs:
                    errors.append(f"group_by[{i}]: duplikat: '{ref}'")
                    continue
                group_refs.add(ref)

    # --- order_by ---
    order_entries: list[dict] = []
    order_by = plan.get("order_by")
    if order_by is not None:
        if not isinstance(order_by, list) or not order_by:
            errors.append("order_by wajib list objek {by, dir?}")
        else:
            for i, o in enumerate(order_by):
                if not isinstance(o, dict) or "by" not in o or \
                        not set(o) <= {"by", "dir"}:
                    errors.append(f"order_by[{i}]: objek hanya boleh "
                                  f"{{by, dir?}} dan wajib punya 'by'")
                    continue
                by = o["by"]
                if not isinstance(by, str):
                    errors.append(f"order_by[{i}].by wajib string "
                                  f"(alias atau 'tabel.kolom')")
                    continue
                arah = o.get("dir", "ASC")
                if not isinstance(arah, str) or arah.upper() not in ("ASC", "DESC"):
                    errors.append(f"order_by[{i}].dir hanya ASC/DESC "
                                  f"(dapat: {arah!r})")
                    continue
                if by not in alias_map:
                    # bukan alias -> harus kolom sah
                    if cek_ref(by, f"order_by[{i}].by") is None:
                        if by not in tabels or "." in by:
                            errors.append(f"order_by[{i}].by '{by}' bukan alias "
                                          f"SELECT dan bukan kolom sah")
                        continue
                order_entries.append({"by": by, "dir": arah.upper()})

    # --- limit & distinct ---
    limit = plan.get("limit")
    if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool)):
        errors.append(f"limit wajib integer (dapat: {limit!r})")
    distinct = plan.get("distinct")
    if distinct is not None and not isinstance(distinct, bool):
        errors.append(f"distinct wajib boolean (dapat: {distinct!r})")

    # --- field presentational: boleh ada, wajib string/null, tidak memengaruhi SQL ---
    for f in FIELD_PRESENTASIONAL:
        if f in plan and plan[f] is not None and not isinstance(plan[f], str):
            errors.append(f"field presentational '{f}' wajib string atau null")

    # --- semantik agregasi / group_by / order_by (SQL harus valid PostgreSQL) ---
    punya_agg = any(isinstance(c, dict) for c in clean_columns)
    kolom_plain = [c for c in clean_columns if isinstance(c, str)]
    if punya_agg and not group_refs and kolom_plain:
        errors.append("select mencampur agregat dan kolom plain tanpa group_by "
                      f"({', '.join(kolom_plain)})")
    for ref in kolom_plain:
        if group_refs and ref not in group_refs:
            errors.append(f"kolom '{ref}' diseleksi tanpa agregasi sehingga wajib "
                          f"masuk group_by")
    for o in order_entries:
        by = o["by"]
        if by in alias_map:
            continue  # alias proyeksi selalu boleh
        if group_refs:
            if by not in group_refs:
                errors.append(f"order_by '{by}' wajib masuk group_by bila "
                              f"group_by dipakai")
        elif punya_agg:
            errors.append(f"order_by '{by}' wajib merujuk alias SELECT bila "
                          f"select memakai agregat tanpa group_by")
        elif plan.get("distinct"):
            if by not in kolom_plain:
                errors.append(f"SELECT DISTINCT: order_by '{by}' wajib masuk "
                              f"daftar kolom select")

    if errors:
        return None, errors

    clean: dict = {"tables": list(tables), "columns": clean_columns}
    if clean_filters:
        clean["filters"] = clean_filters
    if clean_tr is not None:
        clean["time_range"] = clean_tr
    if group_refs:
        clean["group_by"] = [r for r in group_by if r in group_refs]
    if order_entries:
        clean["order_by"] = order_entries
    if limit is not None:
        clean["limit"] = limit
    if distinct is not None:
        clean["distinct"] = distinct
    for f in FIELD_PRESENTASIONAL:
        if f in plan:
            clean[f] = plan[f]
    return clean, []


def _validasi_filter(f, i: int, cek_ref) -> list[str]:
    """Cek satu filter; daftar pesan error (kosong = sah)."""
    if not isinstance(f, dict):
        return [f"filters[{i}]: wajib objek {{column, op, value?}}"]
    kunci = set(f)
    if not kunci <= {"column", "op", "value"}:
        return [f"filters[{i}]: kunci tak dikenal "
                f"{sorted(kunci - {'column', 'op', 'value'})}"]
    if "column" not in kunci or "op" not in kunci:
        return [f"filters[{i}]: wajib punya 'column' dan 'op'"]
    op = f["op"]
    # guard str: op unhashable (list/dict dari rencana rusak) jangan bikin
    # TypeError saat `in frozenset` — kontrak validate_plan adalah mengumpulkan
    # error, bukan melempar
    if not isinstance(op, str) or op not in OPERATOR_DIIZINKAN:
        return [f"filters[{i}].op tidak dikenal: {op!r} (pilihan: "
                f"{', '.join(sorted(OPERATOR_DIIZINKAN))})"]
    cek_ref(f["column"], f"filters[{i}].column")

    def scalar(v) -> bool:
        return isinstance(v, (str, int, float, bool))

    value = f.get("value")
    if op in ("is_null", "is_not_null"):
        if "value" in f and value is not None:
            return [f"filters[{i}]: op '{op}' tidak memakai value "
                    f"(value ditemukan: {value!r})"]
        return []
    if op == "like":
        if not isinstance(value, str):
            return [f"filters[{i}]: op 'like' wajib value string pola "
                    f"(planner menyertakan %)"]
        return []
    if op == "in":
        if not isinstance(value, list) or not value:
            return [f"filters[{i}]: op 'in' wajib list value tidak kosong"]
        if not all(scalar(v) for v in value):
            return [f"filters[{i}]: op 'in' hanya boleh berisi nilai scalar"]
        return []
    if op == "between":
        if not isinstance(value, list) or len(value) != 2:
            return [f"filters[{i}]: op 'between' wajib list tepat 2 nilai"]
        if not (scalar(value[0]) and scalar(value[1])):
            return [f"filters[{i}]: op 'between' wajib dua nilai scalar"]
        try:
            terbalik = value[0] > value[1]
        except TypeError:
            return [f"filters[{i}]: op 'between' wajib dua nilai se-tipe"]
        if terbalik:
            return [f"filters[{i}]: op 'between' batas terbalik: "
                    f"{value[0]!r} > {value[1]!r}"]
        return []
    # operator skalar: eq neq gt gte lt lte
    if "value" not in f or not scalar(value):
        return [f"filters[{i}]: op '{op}' wajib value scalar (string/angka); "
                f"gunakan is_null untuk NULL"]
    return []


def _parse_iso(s, konteks: str, errors: list):
    """ISO date ('YYYY-MM-DD') -> date; ISO datetime -> datetime; None bila
    gagal (error dicatat). String asli dipertahankan di clean_plan agar
    tetap JSON-safe."""
    if isinstance(s, str):
        try:
            return date.fromisoformat(s)
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            pass
    errors.append(f"{konteks}: bukan ISO date/datetime yang sah: {s!r}")
    return None


# ============================================================================
# F2.2b — FK path (BFS deterministik, konsisten peta FK sql_guard)
# ============================================================================
def _fk_pasangan(tabels: dict, a: str, b: str) -> list[tuple[str, str]]:
    """Semua FK dari tabel a menunjuk tabel b, sebagai (kolom_a, kolom_b),
    diurutkan agar deterministik."""
    hasil = []
    for fk in tabels[a].get("foreign_keys", []):
        if fk.get("references_table") == b and _ident_aman(fk.get("column")) \
                and _ident_aman(fk.get("references_column")):
            hasil.append((fk["column"], fk["references_column"]))
    return sorted(hasil)


def _fk_join_chain(plan_tables: list[str], tabels: dict) -> list[tuple]:
    """Hitung chain JOIN dari tables[0] ke seluruh tabel rencana.

    Returns:
        List (tabel, parent, kolom_child, kolom_parent) terurut kedalaman lalu
        nama — tabel perantara FK path ikut masuk (auto-join).

    Raises:
        SqlComposerError: bila ada tabel rencana yang tak terhubung FK path.
    """
    root = plan_tables[0]
    targets = set(plan_tables[1:])
    # BFS level-order; tetangga diurutkan nama supaya jalur terpilih stabil
    parent: dict[str, tuple] = {root: None}
    level = [root]
    while level and any(t not in parent for t in targets):
        berikut = []
        for node in sorted(level):
            tetangga = set()
            for fk in tabels[node].get("foreign_keys", []):
                b = fk.get("references_table")
                if b in tabels:
                    tetangga.add(b)
            for kandidat, info in tabels.items():
                if any(fk.get("references_table") == node
                       for fk in info.get("foreign_keys", [])):
                    tetangga.add(kandidat)
            for nb in sorted(tetangga):
                if nb in parent:
                    continue
                # utamakan FK child->parent (ON child.kol = parent.ref);
                # bila tak ada, pakai arah sebaliknya
                cp = _fk_pasangan(tabels, nb, node)
                if cp:
                    kc, kp = cp[0]
                else:
                    pc = _fk_pasangan(tabels, node, nb)
                    if not pc:
                        continue
                    kc, kp = pc[0][1], pc[0][0]
                parent[nb] = (node, kc, kp)
                berikut.append(nb)
        level = berikut

    tak_terhubung = sorted(t for t in targets if t not in parent)
    if tak_terhubung:
        raise SqlComposerError(
            f"tidak ada FK path dari '{root}' ke: {', '.join(tak_terhubung)}")

    # kumpulkan node jalur tiap target (termasuk perantara), urut kedalaman
    kedalaman = {root: 0}
    node = root
    # isi kedalaman untuk semua yang reachable
    antre = [root]
    while antre:
        n = antre.pop()
        for anak, entri in parent.items():
            if entri is None:  # entri root — tidak punya parent, jangan di-unpack
                continue
            p, _, _ = entri
            if p == n and anak not in kedalaman:
                kedalaman[anak] = kedalaman[n] + 1
                antre.append(anak)

    perlu = set()
    for t in targets:
        n = t
        while n != root:
            perlu.add(n)
            n = parent[n][0]
    return sorted(
        ((n, parent[n][0], parent[n][1], parent[n][2]) for n in perlu),
        key=lambda e: (kedalaman[e[0]], e[0]),
    )


# ============================================================================
# F2.2c — preset waktu (dihitung dari `now` yang diberikan pemanggil)
# ============================================================================
def _bulan_depan(d: date) -> date:
    return date(d.year + (1 if d.month == 12 else 0),
                1 if d.month == 12 else d.month + 1, 1)


def _batas_preset(preset: str, now: datetime) -> tuple[date, date]:
    """(mulai_inklusif, sampai_eksklusif) dari `now` — TZ keputusan pemanggil."""
    hari = date(now.year, now.month, now.day)
    if preset == "this_month":
        return hari.replace(day=1), _bulan_depan(hari)
    if preset == "last_month":
        bulan_ini = hari.replace(day=1)
        # awal bulan lalu = tanggal 1 dari (bulan_ini - 1 hari); jangan pakai
        # _bulan_depan di sini — itu melompat balik ke bulan ini (rentang kosong)
        return (bulan_ini - timedelta(days=1)).replace(day=1), bulan_ini
    if preset == "this_week":
        senin = hari - timedelta(days=hari.weekday())
        return senin, senin + timedelta(days=7)
    if preset == "last_week":
        senin = hari - timedelta(days=hari.weekday())
        return senin - timedelta(days=7), senin
    if preset == "last_7_days":
        return hari - timedelta(days=6), hari + timedelta(days=1)
    if preset == "last_30_days":
        return hari - timedelta(days=29), hari + timedelta(days=1)
    if preset == "this_year":
        return date(hari.year, 1, 1), date(hari.year + 1, 1, 1)
    raise SqlComposerError(f"preset tidak dikenal: {preset!r}")  # tak terjadi


# ============================================================================
# F2.2d — compose_sql: rencana -> SQL deterministik parameterized
# ============================================================================
def ganti_placeholder_null(sql: str) -> str:
    """Ganti seluruh placeholder $n dengan NULL — HANYA untuk jalur verifikasi
    offline (profil verifier v1 belum mendaftar node `Parameter` sqlglot; nilai
    memang tidak pernah ada di SQL sehingga strukturnya tetap terverifikasi
    penuh). JANGAN dipakai untuk eksekusi."""
    return _PLACEHOLDER_RE.sub("NULL", sql)


def compose_sql(plan, schema_config, now=None) -> dict:
    """Rencana JSON (sudah lolos validate_plan) -> SQL SELECT deterministik.

    Args:
        plan: rencana JSON dari planner F3 (divalidasi ulang di sini).
        schema_config: bentuk `tenants.schema_config_json` (lihat
            schema_introspector).
        now: datetime WAJIB bila time_range memakai preset (TZ keputusan
            pemanggil); boleh None bila tidak ada preset.

    Returns:
        {"sql": str, "params": list, "used_tables": list[str] terurut,
         "limit": int final setelah clamp 1..500}

    Raises:
        SqlComposerError: rencana tidak valid, preset tanpa `now`, tidak ada
            FK path, jumlah join melebihi budget verifier, atau (bug composer)
            SQL hasil compose ditolak verify_sql.
    """
    clean, errs = validate_plan(plan, schema_config)
    if errs:
        raise SqlComposerError("rencana tidak valid: " + "; ".join(errs))

    tabels = schema_config["tables"]
    plan_tables = clean["tables"]

    # --- JOIN via FK path (bisa menambah tabel perantara) ---
    join_chain = _fk_join_chain(plan_tables, tabels)
    if len(join_chain) > DEFAULT_BUDGET["jumlah_join"]:
        raise SqlComposerError(
            f"FK path membutuhkan {len(join_chain)} join, melebihi budget "
            f"verifier {DEFAULT_BUDGET['jumlah_join']} — persingkat rencana")
    used_tables = {plan_tables[0], *(e[0] for e in join_chain)}

    params: list = []

    def param(v) -> str:
        params.append(v)
        return f"${len(params)}"

    # --- SELECT ---
    proyeksi = []
    alias_set = set()
    for col in clean["columns"]:
        if isinstance(col, str):
            proyeksi.append(_kolom_sql(col))
            continue
        alias = col.get("alias")
        if alias:
            alias_set.add(alias)
        if col["column"] == "*":
            ekspresi = "COUNT(*)"
        else:
            ekspresi = f"{col['agg']}({_kolom_sql(col['column'])})"
        proyeksi.append(f"{ekspresi} AS {_q(alias)}" if alias else ekspresi)

    sql = f"SELECT {'DISTINCT ' if clean.get('distinct') else ''}"
    sql += ", ".join(proyeksi)

    # --- FROM + JOIN ---
    sql += f" FROM {_q(plan_tables[0])}"
    for tabel, parent, kol_child, kol_parent in join_chain:
        sql += (f" JOIN {_q(tabel)} ON {_q(tabel)}.{_q(kol_child)}"
                f" = {_q(parent)}.{_q(kol_parent)}")

    # --- WHERE: nilai filter dulu (urut rencana), lalu time_range ---
    kondisi = []
    for f in clean.get("filters", []):
        kol = _kolom_sql(f["column"])
        op = f["op"]
        if op in _OP_SQL:
            kondisi.append(f"{kol} {_OP_SQL[op]} {param(f['value'])}")
        elif op == "like":
            kondisi.append(f"{kol} LIKE {param(f['value'])}")
        elif op == "in":
            isi = ", ".join(param(v) for v in f["value"])
            kondisi.append(f"{kol} IN ({isi})")
        elif op == "between":
            kondisi.append(f"{kol} BETWEEN {param(f['value'][0])}"
                           f" AND {param(f['value'][1])}")
        else:  # is_null / is_not_null
            kondisi.append(f"{kol} IS {'NOT ' if op == 'is_not_null' else ''}NULL")
    tr = clean.get("time_range")
    if tr is not None:
        kol = _kolom_sql(tr["field"])
        if "preset" in tr:
            if not isinstance(now, datetime):
                raise SqlComposerError(
                    "preset time_range wajib `now` bertipe datetime "
                    "(keputusan zona waktu ada di pemanggil)")
            d1, d2 = _batas_preset(tr["preset"], now)
            kondisi.append(f"{kol} >= {param(d1)}")
            kondisi.append(f"{kol} < {param(d2)}")
        else:
            d1 = _parse_iso(tr["from"], "time_range.from", [])
            d2 = _parse_iso(tr["to"], "time_range.to", [])
            kondisi.append(f"{kol} >= {param(d1)}")
            kondisi.append(f"{kol} <= {param(d2)}")
    if kondisi:
        sql += " WHERE " + " AND ".join(kondisi)

    # --- GROUP BY ---
    if clean.get("group_by"):
        sql += " GROUP BY " + ", ".join(_kolom_sql(r) for r in clean["group_by"])

    # --- ORDER BY: alias proyeksi menang atas nama kolom (spt PostgreSQL) ---
    if clean.get("order_by"):
        bagian = []
        for o in clean["order_by"]:
            ekspresi = _q(o["by"]) if o["by"] in alias_set else _kolom_sql(o["by"])
            bagian.append(f"{ekspresi} {o['dir']}")
        sql += " ORDER BY " + ", ".join(bagian)

    # --- LIMIT (literal — kebijakan sql_guard; clamp 1..500) ---
    limit = max(BATAS_LIMIT[0], min(BATAS_LIMIT[1], clean.get("limit", LIMIT_BAWAAN)))
    sql += f" LIMIT {limit}"

    # --- asersi internal: placeholder $1..$n persis sesuai jumlah params ---
    angka = {int(m[1:]) for m in _PLACEHOLDER_RE.findall(sql)}
    if angka != set(range(1, len(params) + 1)):
        raise SqlComposerError(
            f"bug composer: placeholder {sorted(angka)} tidak cocok dengan "
            f"{len(params)} parameter")

    # --- belt-and-suspenders: wajib lolos verifier (bug composer = raise) ---
    verdict = verify_sql(ganti_placeholder_null(sql), schema_config)
    if not verdict["ok"]:
        raise SqlComposerError(
            f"bug composer: SQL hasil compose ditolak verifier "
            f"(gerbang {verdict['gate']}): {verdict['reason']}")

    return {
        "sql": sql,
        "params": params,
        "used_tables": sorted(used_tables),
        "limit": limit,
    }
