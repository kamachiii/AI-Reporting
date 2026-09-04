"""clarification_engine.py — Deteksi ambiguitas pertanyaan domain dealer otomotif.

Komponen ini mendeteksi kueri yang multi-tafsir (misal: "penjualan" tanpa menyebut
unit mobil atau sparepart) secara instan (0 token, 0 ms) dan menghasilkan
opsi klarifikasi terstruktur sebelum kueri dieksekusi ke database.
"""

from typing import Optional, Dict, Any, List
import re


def _sisipkan_qualifier(original_q: str, trigger_word: str, replacement_phrase: str) -> str:
    """Ganti kata umum dengan frasa yang sudah spesifik."""
    pattern = re.compile(rf"\b{re.escape(trigger_word)}\b", re.IGNORECASE)
    if pattern.search(original_q):
        return pattern.sub(replacement_phrase, original_q, count=1)
    return f"{original_q.strip()} ({replacement_phrase})"


# Kamus domain untuk ambiguitas dealer
AMBIGUITY_RULES: List[Dict[str, Any]] = [
    {
        "category": "penjualan",
        "trigger_patterns": [
            r"\b(?:penjualan|omzet|omset|terjual|laku|pendapatan)\b",
            r"\b(?:berapa|total|data|rekap|ringkasan)\s+(?:penjualan|omzet|omset|pendapatan)\b",
        ],
        # Jika salah satu qualifier ini ada, pertanyaan SUDAH SPESIFIK (tidak butuh klarifikasi)
        "qualifiers": [
            "unit", "mobil", "motor", "kendaraan", "chassis", "norangka", "tipe mobil", "model mobil",
            "part", "sparepart", "suku cadang", "aksesoris", "oli", "ban",
            "servis", "bengkel", "jasa", "mekanik", "wo", "pkb"
        ],
        "message": (
            "Pertanyaan Anda mengenai penjualan dapat mencakup beberapa divisi bisnis dealer. "
            "Divisi mana yang ingin Anda analisis?"
        ),
        "options_builder": lambda q: [
            {
                "id": "unit",
                "icon": "Car",
                "label": "Penjualan Unit Mobil",
                "deskripsi": "Data transaksi unit kendaraan (mobil baru/bekas)",
                "prompt": _sisipkan_qualifier(q, "penjualan", "penjualan unit mobil"),
            },
            {
                "id": "part",
                "icon": "Wrench",
                "label": "Penjualan Sparepart / Suku Cadang",
                "deskripsi": "Data transaksi penjualan suku cadang dan aksesoris",
                "prompt": _sisipkan_qualifier(q, "penjualan", "penjualan suku cadang sparepart"),
            },
            {
                "id": "all",
                "icon": "Layers",
                "label": "Total Gabungan (Unit & Sparepart)",
                "deskripsi": "Total omzet keseluruhan divisi unit dan suku cadang",
                "prompt": _sisipkan_qualifier(q, "penjualan", "total omzet gabungan unit mobil dan sparepart"),
            },
        ]
    },
    {
        "category": "stok",
        "trigger_patterns": [
            r"\b(?:stok|stock|persediaan|sisa|gudang|inventory)\b",
            r"\b(?:berapa|total|data|sisa)\s+(?:stok|persediaan|unit)\b",
        ],
        "qualifiers": [
            "mobil", "motor", "kendaraan", "chassis", "norangka", "vin",
            "part", "sparepart", "suku cadang", "oli", "filter", "ban"
        ],
        "message": (
            "Pertanyaan mengenai stok dapat merujuk pada stok fisik unit kendaraan atau stok suku cadang di gudang. "
            "Stok mana yang ingin Anda periksa?"
        ),
        "options_builder": lambda q: [
            {
                "id": "stok_unit",
                "icon": "Car",
                "label": "Stok Unit Kendaraan",
                "deskripsi": "Persediaan unit mobil/motor siap jual di dealer",
                "prompt": _sisipkan_qualifier(q, "stok", "stok unit mobil"),
            },
            {
                "id": "stok_part",
                "icon": "Wrench",
                "label": "Stok Sparepart & Suku Cadang",
                "deskripsi": "Persediaan komponen, aksesoris, dan suku cadang gudang",
                "prompt": _sisipkan_qualifier(q, "stok", "stok suku cadang sparepart"),
            },
        ]
    },
    {
        "category": "pembelian",
        "trigger_patterns": [
            r"\b(?:pembelian|pengadaan|kulakan|beli)\b",
            r"\b(?:berapa|total|data)\s+(?:pembelian|pengadaan)\b",
        ],
        "qualifiers": [
            "unit", "mobil", "motor", "kendaraan", "atpm", "distributor",
            "part", "sparepart", "suku cadang", "vendor"
        ],
        "message": (
            "Dealer memiliki pembelian unit kendaraan dari distributor dan pembelian suku cadang dari vendor. "
            "Data pembelian mana yang Anda butuhkan?"
        ),
        "options_builder": lambda q: [
            {
                "id": "beli_unit",
                "icon": "Car",
                "label": "Pembelian Unit Kendaraan",
                "deskripsi": "Pengadaan unit mobil/motor dari pihak ATPM atau distributor",
                "prompt": _sisipkan_qualifier(q, "pembelian", "pembelian unit mobil"),
            },
            {
                "id": "beli_part",
                "icon": "Wrench",
                "label": "Pembelian Sparepart",
                "deskripsi": "Pengadaan suku cadang dan aksesoris dealer",
                "prompt": _sisipkan_qualifier(q, "pembelian", "pembelian suku cadang sparepart"),
            },
        ]
    },
]


def cek_ambiguitas_pertanyaan(question: str) -> Optional[Dict[str, Any]]:
    """Deteksi apakah pertanyaan pengguna memerlukan klarifikasi domain.
    
    Returns:
        Dict berisi { 'category', 'message', 'options' } jika ambigu,
        atau None jika pertanyaan sudah cukup spesifik.
    """
    q_lower = (question or "").strip().lower()
    if not q_lower or len(q_lower) < 4:
        return None

    for rule in AMBIGUITY_RULES:
        # 1. Cek apakah cocok dengan pola pemicu ambiguitas
        is_triggered = any(re.search(p, q_lower) for p in rule["trigger_patterns"])
        if not is_triggered:
            continue

        # 2. Cek apakah pengguna SUDAH menyertakan kata penjelas (qualifier)
        has_qualifier = any(re.search(rf"\b{re.escape(q)}\b", q_lower) for q in rule["qualifiers"])
        if has_qualifier:
            # Sudah spesifik, tidak perlu klarifikasi!
            continue

        # 3. Terbukti ambigu! Susun daftar opsi klarifikasi
        options = rule["options_builder"](question)
        return {
            "category": rule["category"],
            "message": rule["message"],
            "options": options,
        }

    return None
