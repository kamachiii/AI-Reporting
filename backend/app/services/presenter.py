r"""F2.5 (bagian 1) — Presenter: ringkasan jawaban + saran pertanyaan lanjutan.

Mengubah hasil eksekusi SQL (columns + rows + row_count) menjadi ringkasan
laporan dealer bahasa Indonesia MAKS 2 kalimat + 2-3 saran pertanyaan
lanjutan, memakai LLM (panggilan #2, docs v2) dengan NUMBER CHECK ketat:

- SEMUA angka pada ringkasan wajib PERSIS berasal dari data — himpunan
  angka diizinkan = nilai numerik pada rows + row_count + angka yang user
  sendiri tulis di pertanyaannya. LLM DILARANG menghitung/membulatkan/
  menyingkat ("1,5 juta" ditolak karena "juta" tidak diekspansi).
- Pelanggaran -> SATU retry dengan umpan balik yang menyebut angka
  pelanggar; masih melanggar -> ringkasan dibuang (None, metode template).
  Ringkasan yang gagal check TIDAK PERNAH dikembalikan.

Fail-open total: presenter TIDAK PERNAH melempar exception ke pemanggil —
kegagalan bentuk apa pun (LLM down, JSON rusak, number check gagal 2x,
ai_config kosong) kembali ke metode "template": kasus trivial (rows kosong;
tepat 1 baris x 1 kolom numerik) tetap dapat ringkasan lokal, sisanya
ringkasan None. Keputusan: jawaban data (rows) tidak boleh gagal hanya
karena lapisan presentasinya gagal.

Format angka id-ID pada ringkasan dipahami ekstraktor: titik = pemisah
ribuan (pola \d{1,3}(\.\d{3})+, mis. "73.708" == 73708), koma = desimal
("3,5" == 3.5), "3.14" tetap desimal (bukan 314 ribuan — grup ribuan butuh
tepat 3 digit setelah titik).

llm_call_fn injectable: `async (system, user, ai_config) -> str`; default
panggil_llm_default (query_planner) — pola sama dengan planner panggilan #1.
Test memakai fake tanpa jaringan. ai_config falsy (resolve gagal di
pipeline) -> TANPA panggilan LLM: langsung jalur template.
"""
import json
import logging
import re
from decimal import Decimal

from app.services.query_planner import panggil_llm_default

logger = logging.getLogger(__name__)

# Coba 1x (panggilan pertama) + 1x retry dengan umpan balik — pola planner.
MAX_ATTEMPT = 2

# Maks baris data yang disertakan dalam prompt user (hemat token; row_count
# total tetap disebut agar LLM tidak mengira sampel = keseluruhan).
_MAX_BARIS_PROMPT = 20

# Ambang keanggotaan himpunan angka diizinkan: bandingkan relatif (float
# dari Decimal/konversi bisa kehilangan presisi pada angka besar).
_TOLERANSI_RELATIF = 1e-9

# Ambil maksimal 600 char output LLM saat dimasukkan ke prompt umpan balik
# (jaga token; pola _MAX_FEEDBACK_OUTPUT planner).
_MAX_FEEDBACK_OUTPUT = 600

_FENCE_RE = re.compile(r"```[a-zA-Z]*\s*(.*?)\s*```", re.DOTALL)

# Ekstraksi angka dari teks ringkasan/pertanyaan (id-ID). Urutan alternasi
# PENTING (kiri ke kanan, terpanjang/paling spesifik dulu):
#   1. ribuan titik  \d{1,3}(\.\d{3})+  + opsional desimal koma  -> "73.708",
#      "1.234.567", "1.234,56"  (butuh TEPAT 3 digit setelah tiap titik,
#      sehingga "3.14" TIDAK termasuk grup ini)
#   2. desimal koma/titik  \d+[.,]\d+  -> "3,5", "3.14"
#   3. integer  \d+  -> "12", "15%"
_GRUP_RIBUAN, _GRUP_DESIMAL, _GRUP_INT = "ribu", "des", "int"
_ANGKA_RE = re.compile(
    r"(?P<" + _GRUP_RIBUAN + r">\d{1,3}(?:\.\d{3})+(?:,\d+)?)"
    r"|(?P<" + _GRUP_DESIMAL + r">\d+[.,]\d+)"
    r"|(?P<" + _GRUP_INT + r">\d+)")


# ===========================================================================
# NUMBER CHECK — fungsi murni (tanpa I/O, mudah diuji terpisah)
# ===========================================================================
def ekstrak_angka(teks) -> list[float]:
    """Semua angka pada teks sebagai nilai numerik (konvensi id-ID).

    "73.708" -> 73708.0 (ribuan), "3,5" -> 3.5 (desimal koma),
    "3.14" -> 3.14 (desimal — grup ribuan butuh tepat 3 digit),
    "1.234,56" -> 1234.56, "15%" -> 15.0 (tanda % diabaikan).
    """
    if not teks:
        return []
    hasil: list[float] = []
    for m in _ANGKA_RE.finditer(str(teks)):
        if m.group(_GRUP_RIBUAN) is not None:
            s = m.group(_GRUP_RIBUAN).replace(".", "").replace(",", ".")
        else:
            s = (m.group(_GRUP_DESIMAL) if m.group(_GRUP_DESIMAL) is not None
                 else m.group(_GRUP_INT))
            s = s.replace(",", ".")
        try:
            hasil.append(float(s))
        except ValueError:  # tak diharapkan — regex sudah menjamin bentuk
            continue
    return hasil


def _angka_sama(a: float, b: float) -> bool:
    """Kesamaan nilai numerik dengan toleransi relatif kecil."""
    skala = max(abs(a), abs(b), 1.0)
    return abs(a - b) <= skala * _TOLERANSI_RELATIF


def _numerik(nilai) -> bool:
    """Nilai baris data terhitung angka (bool sengaja dikecualikan)."""
    return isinstance(nilai, (int, float, Decimal)) and not isinstance(
        nilai, bool)


def kumpulkan_angka_diizinkan(question, rows, row_count) -> list[float]:
    """Himpunan angka yang BOLEH muncul di ringkasan (fungsi murni).

    = angka pada pertanyaan asli (user sendiri yang menulisnya) + semua
    nilai numerik pada rows + row_count total.
    """
    diizinkan = list(ekstrak_angka(question or ""))
    try:
        if row_count is not None:
            diizinkan.append(float(row_count))
    except (TypeError, ValueError):
        pass
    for baris in rows or []:
        if not isinstance(baris, (list, tuple)):
            continue
        for nilai in baris:
            if _numerik(nilai):
                diizinkan.append(float(nilai))
    return diizinkan


def angka_melanggar(ringkasan, angka_diizinkan) -> list[float]:
    """Angka pada ringkasan yang TIDAK ada di himpunan diizinkan (murni)."""
    diizinkan: list[float] = []
    for a in angka_diizinkan or []:
        try:
            diizinkan.append(float(a))
        except (TypeError, ValueError):
            continue
    return [n for n in ekstrak_angka(ringkasan or "")
            if not any(_angka_sama(n, b) for b in diizinkan)]


def angka_lolos(ringkasan, angka_diizinkan) -> bool:
    """True bila SEMUA angka ringkasan persis berasal dari data diizinkan."""
    return not angka_melanggar(ringkasan, angka_diizinkan)


# ===========================================================================
# Prompt (pola planner: aturan mutlak bernomor + bentuk kontrak JSON)
# ===========================================================================
def _system_prompt() -> str:
    return (
        "Anda adalah penyaji ringkasan (presenter) untuk laporan database "
        "dealer mobil. Tugas Anda: membuat ringkasan singkat dari HASIL "
        "QUERY untuk menjawab pertanyaan user.\n\n"
        "ATURAN MUTLAK:\n"
        "1. Ringkasan MAKSIMAL 2 kalimat, bahasa Indonesia netral, tanpa "
        "markdown, tanpa penjelasan tambahan.\n"
        "2. SEMUA angka yang Anda tulis WAJIB PERSIS sama dengan angka pada "
        "data. DILARANG menghitung, membulatkan, mengonversi, atau "
        "menyingkat satuan (mis. \"1,5 juta\" atau \"sekitar 73 ribu\" "
        "DILARANG — tulis \"1.500.000\" / \"73.708\" persis seperti data; "
        "tulis ribuan dengan titik dan desimal dengan koma).\n"
        "3. Jangan menyebut angka apa pun yang tidak ada di data, termasuk "
        "persentase atau selisih hasil hitungan Anda sendiri.\n"
        "4. HANYA kembalikan objek JSON dengan bentuk persis:\n"
        "{\"ringkasan\": \"...\", \"saran\": [\"...\", \"...\", \"...\"]}\n"
        "\"saran\" berisi 2-3 pertanyaan lanjutan yang relevan. Tanpa "
        "komentar atau teks lain di luar JSON."
    )


def _user_prompt(question: str, columns, rows, row_count) -> str:
    """Prompt user: pertanyaan + nama kolom + maks 20 baris pertama + total."""
    baris_sampel = list(rows or [])[:_MAX_BARIS_PROMPT]
    # default=str: nilai baris bisa berisi date/Decimal/UUID (konversi yang
    # sama dengan pipeline; di sini hanya untuk tampilan prompt).
    return (
        "PERTANYAAN USER:\n" + (question or "").strip() + "\n\n"
        "NAMA KOLOM HASIL (urutan sama dengan setiap baris data):\n"
        + json.dumps(list(columns or []), ensure_ascii=False) + "\n\n"
        f"DATA ({len(baris_sampel)} baris pertama dari {row_count} baris "
        "total):\n"
        + json.dumps(baris_sampel, ensure_ascii=False, default=str) + "\n\n"
        f"TOTAL BARIS: {row_count}"
    )


# ===========================================================================
# Parsing & pembersihan output LLM
# ===========================================================================
def _buang_pembungkus(raw) -> str:
    """Lepas pembungkus non-JSON yang sering menyertai output LLM (fence ```
    atau satu kalimat pembuka) — pola sama dengan planner."""
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


def _parse_dan_bersihkan(raw) -> tuple[dict | None, list[str]]:
    """Output LLM -> ({"ringkasan", "saran"} | None, daftar error).

    saran: list string, dibuang yang kosong, dipotong maks 3 (tidak di-check
    angkanya — saran pertanyaan lanjutan bebas bentuknya).
    """
    teks = _buang_pembungkus(raw)
    try:
        data = json.loads(teks)
    except (ValueError, TypeError) as e:
        return None, [f"output bukan JSON valid: {e}"]
    if not isinstance(data, dict):
        return None, ["output bukan objek JSON"]
    ringkasan = data.get("ringkasan")
    if not isinstance(ringkasan, str) or not ringkasan.strip():
        return None, ["field 'ringkasan' wajib string tidak kosong"]
    mentah = data.get("saran", [])
    if not isinstance(mentah, list):
        return None, ["field 'saran' wajib array string"]
    saran = [s.strip() for s in mentah
             if isinstance(s, str) and s.strip()][:3]
    return {"ringkasan": ringkasan.strip(), "saran": saran}, []


# ===========================================================================
# Template trivial (tanpa LLM)
# ===========================================================================
def _tampil_nilai(nilai) -> str:
    """Tampilan nilai 1x1 — angka tetap persis dari data (tanpa pembulatan);
    float ber-nilai bulat eksak ditampilkan tanpa akhiran ".0" agar rapi."""
    if isinstance(nilai, Decimal):
        return str(nilai)
    if isinstance(nilai, float) and nilai.is_integer():
        return str(int(nilai))
    return str(nilai)


def _template_skip(rows) -> dict | None:
    """Kasus trivial yang cukup dilayani lokal tanpa LLM (atau None)."""
    if not rows:
        return {"ringkasan": None, "saran": [], "metode": "template"}
    if len(rows) == 1 and len(rows[0]) == 1 and _numerik(rows[0][0]):
        return {"ringkasan": f"Hasil: {_tampil_nilai(rows[0][0])}.",
                "saran": [], "metode": "template"}
    return None


# ===========================================================================
# buat_ringkasan — orkestrasi LLM #2 + number check + retry + fail-open
# ===========================================================================
async def buat_ringkasan(question, columns, rows, row_count, ai_config,
                         llm_call_fn=None) -> dict:
    """Hasil query -> {"ringkasan": str|None, "saran": [str], "metode"}.

    metode: "llm" (ringkasan LLM lolos number check) | "template" (kasus
    trivial / kegagalan apa pun). TIDAK PERNAH melempar exception — semua
    kegagalan fail-open ke metode "template" (bukti ringkasan yang gagal
    check tidak pernah dikembalikan).

    Args:
        question: pertanyaan user asli (angkanya ikut diizinkan).
        columns / rows / row_count: hasil eksekusi (rows sudah hasil konversi
            pipeline: Decimal->float, date->ISO str, ...).
        ai_config: config AI ter-resolve; falsy -> TANPA LLM (kasus trivial
            tetap dapat template, sisanya ringkasan None).
        llm_call_fn: injectable async (system, user, ai_config) -> str.
    """
    try:
        return await _buat_ringkasan(question, columns, rows, row_count,
                                     ai_config, llm_call_fn)
    except Exception as e:  # fail-open: presenter tidak menjatuhkan jawaban
        logger.error("presenter: gagal membentuk ringkasan: %s", e)
        return {"ringkasan": None, "saran": [], "metode": "template"}


async def _buat_ringkasan(question, columns, rows, row_count, ai_config,
                          llm_call_fn) -> dict:
    skip = _template_skip(rows)
    if skip is not None:
        return skip
    if not ai_config:
        # tanpa config AI (resolve gagal di pipeline) -> tanpa LLM
        return {"ringkasan": None, "saran": [], "metode": "template"}

    diizinkan = kumpulkan_angka_diizinkan(question, rows, row_count)
    llm = llm_call_fn or panggil_llm_default
    system = _system_prompt()
    user = _user_prompt(question, columns, rows, row_count)

    raw = await llm(system, user, ai_config)
    hasil, errors = _parse_dan_bersihkan(raw)
    if hasil is not None and angka_lolos(hasil["ringkasan"], diizinkan):
        return {"ringkasan": hasil["ringkasan"], "saran": hasil["saran"],
                "metode": "llm"}

    # --- retry 1x: umpan balik menyebut alasan (error parse ATAU angka
    # pelanggar) + output lama yang terpotong ---
    if hasil is not None:
        langgar = angka_melanggar(hasil["ringkasan"], diizinkan)
        errors = ["angka berikut TIDAK berasal dari data: "
                  + ", ".join(str(n) for n in langgar)]
    user2 = (
        user + "\n\nPERCOBAAN SEBELUMNYA DITOLAK VALIDATOR dengan alasan:\n"
        + "\n".join(f"- {e}" for e in errors[:10])
        + "\nOutput sebelumnya (bila ada):\n"
        + (raw or "")[:_MAX_FEEDBACK_OUTPUT]
        + "\nPerbaiki: tulis ulang ringkasan dengan HANYA angka yang persis "
          "muncul pada data, dan kembalikan HANYA JSON sesuai ATURAN MUTLAK."
    )
    raw2 = await llm(system, user2, ai_config)
    hasil2, _ = _parse_dan_bersihkan(raw2)
    if hasil2 is not None and angka_lolos(hasil2["ringkasan"], diizinkan):
        logger.info("presenter: lolos pada retry ke-1 (errors awal: %d)",
                    len(errors))
        return {"ringkasan": hasil2["ringkasan"], "saran": hasil2["saran"],
                "metode": "llm"}

    # Masih melanggar / tetap rusak -> BUANG ringkasan (jangan pakai yang
    # gagal check), kembali ke template tanpa ringkasan.
    logger.warning("presenter: ringkasan dibuang setelah retry (number "
                   "check / parse tetap gagal)")
    return {"ringkasan": None, "saran": [], "metode": "template"}
