"""Smart Automotive Domain Thesaurus & Business Rules Engine.

Menyediakan kamus istilah percakapan industri otomotif Indonesia (dealer & bengkel),
pemetaan sinonim ke skema tabel fisik database Otobitz (2.387 tabel), serta penegakan
aturan bisnis baku (misal: filter batal = 0 AND retur = 0).
"""
import re
from typing import Optional


# Kamus aturan domain otomotif terstruktur
AUTOMOTIVE_DOMAIN_RULES = [
    {
        "category": "penjualan_unit",
        "title": "Aturan Transaksi Penjualan Unit Kendaraan / Mobil",
        "keywords": [
            "omzet", "penjualan", "sales", "unit", "mobil", "terjual", "laku",
            "pendapatan", "revenue", "spk", "pesanan", "faktur", "do", "delivery order",
            "untt", "unit_jual", "deal", "leasing", "cash"
        ],
        "primary_tables": ["untt_penjualan", "untt_pesanankendaraan", "glbm_kendaraan", "glbm_customer", "vw_untt_penjualan"],
        "guidelines": [
            "Tabel utama transaksi penjualan unit adalah 'untt_penjualan' (atau view 'vw_untt_penjualan').",
            "Wajib memfilter transaksi sah (bukan retur atau batal): untt_penjualan.batal = false AND untt_penjualan.retur = false (kolom batal dan retur bertipe BOOLEAN di PostgreSQL).",
            "Untuk total omzet/nilai uang penjualan gunakan SUM(untt_penjualan.hjakhir) atau SUM(untt_penjualan.hargajual).",
            "Untuk jumlah unit kendaraan terjual gunakan COUNT(untt_penjualan.nomor).",
            "Kolom tanggal transaksi adalah untt_penjualan.tanggal.",
            "Relasi ke Surat Pesanan Kendaraan (SPK): untt_penjualan.nomor_pesanan = untt_pesanankendaraan.nomor.",
            "Relasi ke Customer: untt_pesanankendaraan.nomor_customer = glbm_customer.nomor."
        ]
    },
    {
        "category": "servis_bengkel",
        "title": "Aturan Transaksi Servis, Perawatan, & Bengkel (Aftersales)",
        "keywords": [
            "servis", "service", "bengkel", "perawatan", "perbaikan", "reparasi",
            "wo", "work order", "pk", "perintah kerja", "sa", "service advisor",
            "mekanik", "teknisi", "jasa", "womt", "srvt"
        ],
        "primary_tables": ["womt_wo", "womt_wopart", "womt_wojasa", "glbm_customer"],
        "guidelines": [
            "Tabel utama transaksi servis/work order bengkel adalah 'womt_wo'.",
            "Untuk rincian suku cadang servis gunakan 'womt_wopart', untuk ongkos jasa gunakan 'womt_wojasa'.",
            "Wajib menyaring transaksi work order yang valid (womt_wo.batal = false).",
            "Relasi WO ke detail: womt_wo.nomor = womt_wopart.nomor_wo dan womt_wo.nomor = womt_wojasa.nomor_wo."
        ]
    },
    {
        "category": "suku_cadang_inventori",
        "title": "Aturan Sparepart, Suku Cadang, & Inventori Gudang",
        "keywords": [
            "sparepart", "spare part", "suku cadang", "part", "onderdil", "oli",
            "pelumas", "item", "stok", "stock", "inventori", "gudang", "pembelian",
            "invt", "prtt"
        ],
        "primary_tables": ["invt_item", "invt_pembelian", "invt_stok"],
        "guidelines": [
            "Tabel master katalog sparepart adalah 'invt_item'.",
            "Tabel transaksi pengadaan/pembelian suku cadang dari supplier adalah 'invt_pembelian' (filter invt_pembelian.batal = false).",
            "Tabel posisi saldo dan kuantitas persediaan gudang adalah 'invt_stok'."
        ]
    },
    {
        "category": "pelanggan_customer",
        "title": "Aturan Master Data Pelanggan & Customer",
        "keywords": [
            "customer", "pelanggan", "konsumen", "pembeli", "klien",
            "pemilik", "top customer", "loyalitas", "glbm_customer"
        ],
        "primary_tables": ["glbm_customer", "untt_pesanankendaraan", "untt_penjualan"],
        "guidelines": [
            "Tabel master customer adalah 'glbm_customer' (kolom: nomor, nama, kota, telepon, alamat).",
            "PENTING: Tabel 'untt_penjualan' TIDAK memiliki kolom kode_customer langsung.",
            "Untuk menghubungkan penjualan ke customer gunakan alur 2-hop:",
            "  untt_penjualan.nomor_pesanan = untt_pesanankendaraan.nomor",
            "  JOIN untt_pesanankendaraan.nomor_customer = glbm_customer.nomor."
        ]
    },
    {
        "category": "periode_waktu",
        "title": "Aturan Periode Musiman & Kalender Akuntansi",
        "keywords": [
            "semester", "kuartal", "quarter", "q1", "q2", "q3", "q4",
            "tahunan", "bulanan", "ytd", "pertumbuhan", "perbandingan"
        ],
        "primary_tables": [],
        "guidelines": [
            "Semester 1 mencakup bulan 1 s/d 6 (EXTRACT(MONTH FROM tanggal) BETWEEN 1 AND 6).",
            "Semester 2 mencakup bulan 7 s/d 12 (EXTRACT(MONTH FROM tanggal) BETWEEN 7 AND 12).",
            "Kuartal 1 (Q1) = bulan 1-3, Kuartal 2 (Q2) = bulan 4-6, Kuartal 3 (Q3) = bulan 7-9, Kuartal 4 (Q4) = bulan 10-12.",
            "Untuk perbandingan tahun gunakan EXTRACT(YEAR FROM tanggal) atau DATE_TRUNC('year', tanggal)."
        ]
    }
]


def deteksi_konteks_domain(question: str) -> list[dict]:
    """Deteksi kategori dan aturan domain otomotif yang cocok dengan pertanyaan pengguna."""
    q_lower = question.lower()
    matched = []

    for rule in AUTOMOTIVE_DOMAIN_RULES:
        is_match = False
        for kw in rule["keywords"]:
            pattern = r'\b' + re.escape(kw) + r'\b'
            if re.search(pattern, q_lower):
                is_match = True
                break

        if is_match:
            matched.append(rule)

    if not matched:
        matched.append(AUTOMOTIVE_DOMAIN_RULES[0])

    return matched


def susun_instruksi_domain(matched_rules: list[dict]) -> str:
    """Susun teks panduan domain otomotif untuk diinjeksikan ke prompt Vanna AI."""
    lines = ["=== DOMAIN BUSINESS RULES & SCHEMA CONVENTIONS (AUTOMOTIVE DMS) ==="]
    
    for rule in matched_rules:
        lines.append(f"[{rule['title']}]")
        for g in rule["guidelines"]:
            lines.append(f"- {g}")
        lines.append("")

    return "\n".join(lines).strip()


def ambil_semua_aturan_thesaurus() -> list[dict]:
    """Ambil seluruh aturan domain untuk disimpan ke database vektor tenant_vector_kb."""
    entries = []
    for rule in AUTOMOTIVE_DOMAIN_RULES:
        content = f"Domain: Automotive DMS\nTitle: {rule['title']}\n"
        content += "Keywords: " + ", ".join(rule["keywords"]) + "\n"
        content += "Rules:\n" + "\n".join(f"- {g}" for g in rule["guidelines"])
        
        entries.append({
            "category": rule["category"],
            "title": rule["title"],
            "content": content.strip(),
            "tables": rule["primary_tables"]
        })
    return entries
