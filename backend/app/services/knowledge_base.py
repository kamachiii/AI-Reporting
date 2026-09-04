"""Knowledge Base tenant (F2.0) — lapisan semantik untuk Context Builder AI.

Bentuk data mengikuti docs/PERANCANGAN-PIPELINE-AI.md §3 (satu kolom JSONB
`tenants.knowledge_base`). Kolom ditambahkan oleh migrations/005_knowledge_base.sql.

Modul ini murni load/validate/normalize — TIDAK ada eksekusi SQL dinamis;
semua query memakai parameter asyncpg ($1, $2, ...).

CATATAN `tabel_dilarang` / `tabel_diizinkan` / `kolom_dikecualikan`: isinya
dipakai pipeline chat (chat_pipeline) — `tabel_dilarang` masuk whitelist
verifier (kb_forbidden), `tabel_diizinkan` menyaring skema efektif yang
dilihat planner/composer/verifier (tenant skema raksasa tetap terpakai),
`kolom_dikecualikan` membuang kolom tak relevan (api key, token, logo, ...)
dari skema efektif itu. Modul ini sendiri tetap murni
load/validate/normalize — TIDAK ada eksekusi SQL dinamis; semua query memakai
parameter asyncpg ($1, $2, ...).
"""
import json
import logging
import re

logger = logging.getLogger(__name__)

# Field tingkat atas yang dikenal — field lain = error (validasi ketat).
KNOWN_KEYS = ("glossary", "catatan_kolom", "nilai_map", "contoh_tanya",
              "tabel_dilarang", "tabel_diizinkan", "kolom_dikecualikan",
              "relasi_tabel")

# Struktur kosong default: dipakai saat kolom NULL / tenant belum mengisi KB.
EMPTY_KB = {
    "glossary": [],
    "catatan_kolom": {},
    "nilai_map": {},
    "contoh_tanya": [],
    "tabel_dilarang": [],
    "tabel_diizinkan": [],
    "kolom_dikecualikan": [],
    "relasi_tabel": [],
}

# Pola ident aman untuk nama tabel pada tabel_diizinkan (allowlist). Allowlist
# HANYA menyaring nama tabel hasil introspeksi (tidak pernah membuat entri
# baru), jadi pola ini lapisan kebersihan data — bukan garis keamanan SQL.
_IDENT_TABEL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Pola `tabel.kolom` untuk kolom_dikecualikan — lapisan kebersihan data yang
# sama (pemakaian di pipeline hanya membuang kolom dari skema efektif).
_IDENT_KOLOM_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$")

# Field yang boleh ada di satu entri glossary / contoh_tanya / relasi_tabel.
GLOSSARY_FIELDS = ("istilah", "arti")
CONTOH_TANYA_FIELDS = ("tanya", "tabel", "agg", "time_range")
RELASI_TABEL_FIELDS = ("tabel", "kolom", "merujuk_tabel", "merujuk_kolom")


def _is_nonempty_str(value) -> bool:
    """True bila value adalah string non-kosong (setelah strip)."""
    return isinstance(value, str) and value.strip() != ""


def _empty_kb() -> dict:
    """Salinan segar struktur kosong (hindari state global terbagi)."""
    return {k: ({} if isinstance(EMPTY_KB[k], dict) else []) for k in KNOWN_KEYS}


def parse_stored_kb(raw) -> dict:
    """Konversi nilai kolom JSONB dari DB menjadi struktur KB normal.

    asyncpg mengembalikan JSONB sebagai string (pool inti tak memasang codec
    JSON), tapi tetap terima dict (mis. dari stub test / codec masa depan).
    NULL / rusak -> struktur kosong default (KB bersifat pelengkap: kegagalan
    membaca tidak boleh menjatuhkan pemanggilnya).
    """
    if raw is None:
        return _empty_kb()
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError) as e:
        logger.warning(f"knowledge_base tersimpan bukan JSON valid, pakai default: {e}")
        return _empty_kb()
    if not isinstance(data, dict):
        logger.warning("knowledge_base tersimpan bukan objek JSON, pakai default")
        return _empty_kb()
    # Isi field yang hilang dengan default kosong (normalisasi bentuk).
    clean = _empty_kb()
    for key in KNOWN_KEYS:
        if key in data and isinstance(data[key], type(EMPTY_KB[key])):
            clean[key] = data[key]
    return clean


async def load_kb(pool, branch_code: str) -> dict:
    """Baca KB satu tenant dari kolom tenants.knowledge_base.

    NULL / baris tidak ada -> struktur kosong default (bukan error):
    pemanggil (router/chat) cukup memakai hasilnya apa adanya.
    """
    row = await pool.fetchrow(
        "SELECT knowledge_base FROM tenants WHERE branch_code = $1", branch_code)
    if not row:
        return _empty_kb()
    return parse_stored_kb(row["knowledge_base"])


def _validate_glossary(glossary, errors: list[str]) -> list | None:
    """Validasi bagian glossary; return versi bersih bila bagian ini valid."""
    if not isinstance(glossary, list):
        errors.append("glossary: harus berupa array (list) of objek")
        return None
    ok = True
    for i, entry in enumerate(glossary):
        if not isinstance(entry, dict):
            errors.append(f"glossary[{i}]: entri harus berupa objek {{istilah, arti}}")
            ok = False
            continue
        for field in entry:
            if field not in GLOSSARY_FIELDS:
                errors.append(f"glossary[{i}]: field '{field}' tidak dikenal "
                              "(field yang valid: istilah, arti)")
                ok = False
        for field in GLOSSARY_FIELDS:
            if not _is_nonempty_str(entry.get(field)):
                errors.append(f"glossary[{i}]: field '{field}' wajib diisi "
                              "(string non-kosong)")
                ok = False
    if not ok:
        return None
    return [{"istilah": e["istilah"].strip(), "arti": e["arti"].strip()} for e in glossary]


def _validate_catatan_kolom(catatan, errors: list[str]) -> dict | None:
    """Validasi bagian catatan_kolom ({\"tabel.kolom\": \"catatan\"})."""
    if not isinstance(catatan, dict):
        errors.append('catatan_kolom: harus berupa objek {"tabel.kolom": "catatan"}')
        return None
    ok = True
    for key, value in catatan.items():
        if not _is_nonempty_str(key):
            errors.append("catatan_kolom: nama kolom wajib diisi (string non-kosong)")
            ok = False
        elif not _is_nonempty_str(value):
            errors.append(f"catatan_kolom['{key}']: nilai harus string non-kosong")
            ok = False
    if not ok:
        return None
    return {k.strip(): v.strip() for k, v in catatan.items()}


def _validate_nilai_map(nilai_map, errors: list[str]) -> dict | None:
    """Validasi bagian nilai_map ({\"tabel.kolom\": {\"nilai_asli\": \"makna\"}})."""
    if not isinstance(nilai_map, dict):
        errors.append('nilai_map: harus berupa objek {"tabel.kolom": {"nilai": "makna"}}')
        return None
    ok = True
    for key, mapping in nilai_map.items():
        if not _is_nonempty_str(key):
            errors.append("nilai_map: nama kolom wajib diisi (string non-kosong)")
            ok = False
        elif not isinstance(mapping, dict):
            errors.append(f"nilai_map['{key}']: harus berupa objek {{nilai_asli: makna}}")
            ok = False
        else:
            for val, meaning in mapping.items():
                if not _is_nonempty_str(val) or not _is_nonempty_str(meaning):
                    errors.append(f"nilai_map['{key}']['{val}']: "
                                  "kunci & nilai harus string non-kosong")
                    ok = False
    if not ok:
        return None
    return {
        k.strip(): {val: meaning for val, meaning in mapping.items()}
        for k, mapping in nilai_map.items() if isinstance(mapping, dict)
    }


def _validate_contoh_tanya(contoh, errors: list[str]) -> list | None:
    """Validasi bagian contoh_tanya (minimal field 'tanya' wajib)."""
    if not isinstance(contoh, list):
        errors.append("contoh_tanya: harus berupa array (list) of objek")
        return None
    ok = True
    for i, entry in enumerate(contoh):
        if not isinstance(entry, dict):
            errors.append(f"contoh_tanya[{i}]: entri harus berupa objek "
                          "(minimal punya field 'tanya')")
            ok = False
            continue
        for field in entry:
            if field not in CONTOH_TANYA_FIELDS:
                errors.append(f"contoh_tanya[{i}]: field '{field}' tidak dikenal "
                              "(field yang valid: tanya, tabel, agg, time_range)")
                ok = False
        if not _is_nonempty_str(entry.get("tanya")):
            errors.append(f"contoh_tanya[{i}]: field 'tanya' wajib diisi (string non-kosong)")
            ok = False
        tabel = entry.get("tabel")
        if tabel is not None and (
                not isinstance(tabel, list) or not all(_is_nonempty_str(t) for t in tabel)):
            errors.append(f"contoh_tanya[{i}]: 'tabel' harus array of string")
            ok = False
        for field in ("agg", "time_range"):
            if field in entry and not _is_nonempty_str(entry[field]):
                errors.append(f"contoh_tanya[{i}]: '{field}' harus string non-kosong")
                ok = False
    if not ok:
        return None
    # Normalisasi: 'tanya' di-strip; field opsional hanya diikutkan bila ada.
    return [
        {"tanya": e["tanya"].strip(),
         **({"tabel": e["tabel"]} if "tabel" in e else {}),
         **({"agg": e["agg"]} if "agg" in e else {}),
         **({"time_range": e["time_range"]} if "time_range" in e else {})}
        for e in contoh if isinstance(e, dict)
    ]


def _validate_tabel_dilarang(dilarang, errors: list[str]) -> list | None:
    """Validasi bagian tabel_dilarang (array of string, hanya disimpan)."""
    if not isinstance(dilarang, list) or not all(isinstance(t, str) for t in dilarang):
        errors.append("tabel_dilarang: harus berupa array of string")
        return None
    if any(not t.strip() for t in dilarang):
        errors.append("tabel_dilarang: nama tabel tidak boleh kosong")
        return None
    return [t.strip() for t in dilarang]


def _validate_tabel_diizinkan(diizinkan, errors: list[str]) -> list | None:
    """Validasi bagian tabel_diizinkan (allowlist skema efektif per tenant).

    Wajib array of string non-kosong berpola ident aman
    ([A-Za-z_][A-Za-z0-9_]*) — error dilaporkan per indeks agar form admin
    menunjuk entri yang salah. Nama yang tidak ada di skema tenant TIDAK
    dianggap error di sini (skema bisa berubah; di pipeline nama tsb. cukup
    diabaikan dengan catatan).
    """
    if not isinstance(diizinkan, list) or not all(
            isinstance(t, str) for t in diizinkan):
        errors.append("tabel_diizinkan: harus berupa array of string")
        return None
    ok = True
    for i, nama in enumerate(diizinkan):
        bersih = nama.strip()
        if not bersih:
            errors.append(f"tabel_diizinkan[{i}]: nama tabel tidak boleh kosong")
            ok = False
        elif not _IDENT_TABEL_RE.match(bersih):
            errors.append(
                f"tabel_diizinkan[{i}]: '{bersih}' bukan nama tabel yang valid "
                "(hanya huruf, angka, underscore; tidak boleh diawali angka)")
            ok = False
    if not ok:
        return None
    return [t.strip() for t in diizinkan]


def _validate_kolom_dikecualikan(dikecualikan, errors: list[str]) -> list | None:
    """Validasi bagian kolom_dikecualikan (buang kolom dari skema efektif).

    Wajib array of string berpola ident aman 'tabel.kolom'
    ([A-Za-z_][A-Za-z0-9_]* di kedua sisi titik) — error dilaporkan per
    indeks agar form admin menunjuk entri yang salah. Entri yang tidak ada
    di skema tenant TIDAK dianggap error di sini (skema bisa berubah; di
    pipeline entri tsb. cukup diabaikan).
    """
    if not isinstance(dikecualikan, list) or not all(
            isinstance(t, str) for t in dikecualikan):
        errors.append("kolom_dikecualikan: harus berupa array of string")
        return None
    ok = True
    for i, entri in enumerate(dikecualikan):
        bersih = entri.strip()
        if not bersih:
            errors.append(f"kolom_dikecualikan[{i}]: entri tidak boleh kosong")
            ok = False
        elif not _IDENT_KOLOM_RE.match(bersih):
            errors.append(
                f"kolom_dikecualikan[{i}]: '{bersih}' bukan format "
                "'tabel.kolom' yang valid (hanya huruf, angka, underscore; "
                "dipisah tepat satu titik)")
            ok = False
    if not ok:
        return None
    return [t.strip() for t in dikecualikan]


def _validate_relasi_tabel(relasi, errors: list[str]) -> list | None:
    """Validasi bagian relasi_tabel (virtual foreign keys antar tabel).

    Bentuk: [{"tabel": "untt_pembelian", "kolom": "norangka",
             "merujuk_tabel": "untt_datakendaraan", "merujuk_kolom": "norangka"}]
    """
    if not isinstance(relasi, list):
        errors.append("relasi_tabel: harus berupa array (list) of objek")
        return None
    ok = True
    for i, entry in enumerate(relasi):
        if not isinstance(entry, dict):
            errors.append(f"relasi_tabel[{i}]: entri harus berupa objek {{tabel, kolom, merujuk_tabel, merujuk_kolom}}")
            ok = False
            continue
        for field in entry:
            if field not in RELASI_TABEL_FIELDS:
                errors.append(f"relasi_tabel[{i}]: field '{field}' tidak dikenal "
                              "(field yang valid: tabel, kolom, merujuk_tabel, merujuk_kolom)")
                ok = False
        for field in RELASI_TABEL_FIELDS:
            val = entry.get(field)
            if not _is_nonempty_str(val):
                errors.append(f"relasi_tabel[{i}]: field '{field}' wajib diisi (string non-kosong)")
                ok = False
            elif not _IDENT_TABEL_RE.match(val.strip()):
                errors.append(f"relasi_tabel[{i}]: '{val}' bukan identifier yang valid pada field '{field}'")
                ok = False
    if not ok:
        return None
    return [
        {
            "tabel": e["tabel"].strip(),
            "kolom": e["kolom"].strip(),
            "merujuk_tabel": e["merujuk_tabel"].strip(),
            "merujuk_kolom": e["merujuk_kolom"].strip(),
        }
        for e in relasi if isinstance(e, dict)
    ]


# Peta field -> validator bagian; mengembalikan versi bersih bila bagian valid.
_SECTION_VALIDATORS = {
    "glossary": _validate_glossary,
    "catatan_kolom": _validate_catatan_kolom,
    "nilai_map": _validate_nilai_map,
    "contoh_tanya": _validate_contoh_tanya,
    "tabel_dilarang": _validate_tabel_dilarang,
    "tabel_diizinkan": _validate_tabel_diizinkan,
    "kolom_dikecualikan": _validate_kolom_dikecualikan,
    "relasi_tabel": _validate_relasi_tabel,
}


def validate_kb(payload) -> tuple[dict, list[str]]:
    """Validasi ketat payload KB (dari PUT admin / tombol Validasi).

    Returns:
        (clean, errors) — clean = KB ternormalisasi penuh (7 field selalu ada)
        dan layak disimpan HANYA bila errors == []. Setiap pelanggaran
        dilaporkan per indeks/field agar mudah ditampilkan di form admin.
    """
    errors: list[str] = []
    clean = _empty_kb()

    if not isinstance(payload, dict):
        return clean, [f"Payload harus berupa objek JSON (dict), bukan {type(payload).__name__}"]

    # Field tingkat atas tidak dikenal = error.
    valid_keys_txt = ", ".join(KNOWN_KEYS)
    for key in payload:
        if key not in KNOWN_KEYS:
            errors.append(f"Field '{key}' tidak dikenal (field yang valid: {valid_keys_txt})")

    for key, validator in _SECTION_VALIDATORS.items():
        if key in payload:
            section_clean = validator(payload[key], errors)
            if section_clean is not None:
                clean[key] = section_clean

    return clean, errors


async def muat_kb_gabungan(core_pool, tenant_kb_raw, schema_tables: set) -> dict:
    """Gabungkan KB global + KB per-tenant (F3).

    Aturan merge (tenant menang jika konflik):
    - glossary: global + tenant (tenant menang jika 'istilah' sama)
    - catatan_kolom: global + tenant (tenant menang jika key sama)
    - nilai_map: global + tenant (tenant menang jika key sama)
    - contoh_tanya: tenant di depan + global di belakang (semua digabung)
    - tabel_dilarang/diizinkan/kolom_dikecualikan: HANYA dari tenant
      (kontrol akses per-DB, tidak boleh di-override global)

    KB global text bertipe 'Table X columns: ...' disaring berdasarkan
    schema_tables — hanya entri yang tabel-nya ada di skema tenant yang
    dikonversi menjadi catatan_kolom.

    Jika tabel global_knowledge_base belum ada (migration belum jalan),
    kembalikan KB tenant saja (graceful degradation).
    """
    tenant_kb = parse_stored_kb(tenant_kb_raw)

    try:
        global_rows = await core_pool.fetch(
            "SELECT kind, content, question, sql_example FROM global_knowledge_base"
        )
    except Exception as e:
        logger.warning(f"Gagal memuat KB global (mungkin tabel belum ada): {e}")
        return tenant_kb

    global_glossary = {}
    global_catatan = {}
    global_contoh = []

    for row in global_rows:
        kind = row["kind"]
        if kind == "text":
            content = row["content"].strip()
            table_match = re.match(r"^Table\s+([A-Za-z0-9_]+)\s+columns:", content, re.IGNORECASE)
            if table_match:
                tabel = table_match.group(1)
                if tabel in schema_tables:
                    global_catatan[tabel] = content
            else:
                maps_to_match = re.search(r"^(.*?)\s+maps to\s+(.*?)$", content, re.IGNORECASE)
                if maps_to_match:
                    istilah = maps_to_match.group(1).strip()
                    global_glossary[istilah] = content
                else:
                    istilah = (content[:30] + "...") if len(content) > 30 else content
                    global_glossary[istilah] = content
        elif kind == "example":
            if row.get("question"):
                contoh = {"tanya": row["question"]}
                if row.get("sql_example"):
                    # Beberapa field mungkin mengharapkan 'sql', disesuaikan
                    contoh["sql_example"] = row["sql_example"]
                global_contoh.append(contoh)

    # Gabungkan (tenant menang jika konflik)
    merged_kb = {
        "tabel_dilarang": list(tenant_kb.get("tabel_dilarang", [])),
        "tabel_diizinkan": list(tenant_kb.get("tabel_diizinkan", [])),
        "kolom_dikecualikan": list(tenant_kb.get("kolom_dikecualikan", [])),
        "nilai_map": dict(tenant_kb.get("nilai_map", {})),
    }

    # Merge glossary
    merged_glossary = {k: {"istilah": k, "arti": v} for k, v in global_glossary.items()}
    for entry in tenant_kb.get("glossary", []):
        istilah = entry.get("istilah")
        if istilah:
            merged_glossary[istilah] = entry
    merged_kb["glossary"] = list(merged_glossary.values())

    # Merge catatan_kolom
    merged_catatan = dict(global_catatan)
    merged_catatan.update(tenant_kb.get("catatan_kolom", {}))
    merged_kb["catatan_kolom"] = merged_catatan

    # Merge contoh_tanya
    merged_kb["contoh_tanya"] = list(tenant_kb.get("contoh_tanya", [])) + global_contoh

    # Merge relasi_tabel (tenant diutamakan, global melengkapi)
    seen_relasi = set()
    merged_relasi = []
    for r in tenant_kb.get("relasi_tabel", []):
        key = (r.get("tabel"), r.get("kolom"), r.get("merujuk_tabel"), r.get("merujuk_kolom"))
        if key not in seen_relasi and all(key):
            seen_relasi.add(key)
            merged_relasi.append(r)
    merged_kb["relasi_tabel"] = merged_relasi

    return merged_kb


def suntikkan_relasi_ke_skema(schema_config: dict, relasi_tabel: list[dict]) -> dict:
    """Suntikkan relasi foreign keys virtual dari KB ke schema_config['tables'].

    Menambahkan entri ke tabels[tabel]['foreign_keys'] secara non-mutatif
    (mengembalikan salinan baru) agar sql_composer dapat melakukan BFS FK path
    bahkan saat database fisik tidak memiliki constraint FOREIGN KEY DDL.
    """
    if not schema_config or not isinstance(schema_config, dict):
        return schema_config
    tabels = schema_config.get("tables")
    if not tabels or not isinstance(tabels, dict):
        return schema_config

    tables_copy = {}
    for tname, tinfo in tabels.items():
        tinfo_copy = dict(tinfo)
        tinfo_copy["foreign_keys"] = list(tinfo.get("foreign_keys", []))
        tables_copy[tname] = tinfo_copy

    for r in (relasi_tabel or []):
        t1 = r.get("tabel")
        c1 = r.get("kolom")
        t2 = r.get("merujuk_tabel")
        c2 = r.get("merujuk_kolom")
        if not (t1 and c1 and t2 and c2):
            continue
        if t1 in tables_copy and t2 in tables_copy:
            fks1 = tables_copy[t1]["foreign_keys"]
            if not any(fk.get("column") == c1 and fk.get("references_table") == t2 and fk.get("references_column") == c2 for fk in fks1):
                fks1.append({
                    "column": c1,
                    "references_table": t2,
                    "references_column": c2,
                })

    return {**schema_config, "tables": tables_copy}

