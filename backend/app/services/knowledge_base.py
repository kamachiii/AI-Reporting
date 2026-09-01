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
              "tabel_dilarang", "tabel_diizinkan", "kolom_dikecualikan")

# Struktur kosong default: dipakai saat kolom NULL / tenant belum mengisi KB.
EMPTY_KB = {
    "glossary": [],
    "catatan_kolom": {},
    "nilai_map": {},
    "contoh_tanya": [],
    "tabel_dilarang": [],
    "tabel_diizinkan": [],
    "kolom_dikecualikan": [],
}

# Pola ident aman untuk nama tabel pada tabel_diizinkan (allowlist). Allowlist
# HANYA menyaring nama tabel hasil introspeksi (tidak pernah membuat entri
# baru), jadi pola ini lapisan kebersihan data — bukan garis keamanan SQL.
_IDENT_TABEL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Pola `tabel.kolom` untuk kolom_dikecualikan — lapisan kebersihan data yang
# sama (pemakaian di pipeline hanya membuang kolom dari skema efektif).
_IDENT_KOLOM_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$")

# Field yang boleh ada di satu entri glossary / contoh_tanya.
GLOSSARY_FIELDS = ("istilah", "arti")
CONTOH_TANYA_FIELDS = ("tanya", "tabel", "agg", "time_range")


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


# Peta field -> validator bagian; mengembalikan versi bersih bila bagian valid.
_SECTION_VALIDATORS = {
    "glossary": _validate_glossary,
    "catatan_kolom": _validate_catatan_kolom,
    "nilai_map": _validate_nilai_map,
    "contoh_tanya": _validate_contoh_tanya,
    "tabel_dilarang": _validate_tabel_dilarang,
    "tabel_diizinkan": _validate_tabel_diizinkan,
    "kolom_dikecualikan": _validate_kolom_dikecualikan,
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
