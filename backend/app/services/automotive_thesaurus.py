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
            "mekanik", "teknisi", "jasa", "srvt", "general repair", "body paint",
            "unit entry"
        ],
        "primary_tables": ["srvt_wo", "srvt_wodetail", "glbm_customer"],
        "guidelines": [
            "Tabel utama transaksi servis/work order bengkel adalah 'srvt_wo' (kolom: nomor, tanggal, nomor_customer, nopolisi, norangka, totalestimasibiaya, penerima, nama_foreman, batal, bodypaint, booking).",
            "Tabel rincian pekerjaan dan ongkos jasa servis adalah 'srvt_wodetail' (kolom: nomor_wo, nama_tasklist, jasa, part, bahan, kode_mekanik).",
            "Wajib menyaring transaksi work order yang valid (srvt_wo.batal = false).",
            "Untuk menghitung total unit entry / jumlah kunjungan servis gunakan COUNT(srvt_wo.nomor).",
            "Relasi WO ke detail: srvt_wo.nomor = srvt_wodetail.nomor_wo.",
            "Relasi WO ke customer: srvt_wo.nomor_customer = glbm_customer.nomor."
        ]
    },
    {
        "category": "komparasi_performa_tahunan",
        "title": "Aturan Komparasi Performa & Tren Operasional Tahunan",
        "keywords": [
            "peforma", "performa", "komparasi", "tahunan", "kinerja", "tren tahunan",
            "performa tahunan", "rekap tahunan", "divisi", "tiap divisi", "antar divisi"
        ],
        "primary_tables": ["untt_penjualan", "srvt_wo", "srvt_wodetail", "srvt_stockparts"],
        "guidelines": [
            "Untuk pertanyaan yang meminta perbandingan performa tahunan atau komparasi antar fungsi/divisi:",
            "  - Sajikan data dalam satu kueri terpadu yang menggabungkan metrik utama per tahun (EXTRACT(YEAR FROM tanggal)).",
            "  - Metrik penjualan unit: dari 'untt_penjualan' (omzet: SUM(hjakhir), unit: COUNT(nomor), filter batal = false AND retur = false).",
            "  - Metrik servis bengkel: dari 'srvt_wo' (omzet: SUM(totalestimasibiaya), kunjungan: COUNT(nomor), filter batal = false).",
            "  - Metrik suku cadang: dari 'srvt_wodetail' (penjualan part: SUM(part) WHERE part > 0).",
            "Hasil disajikan langsung sebagai satu tabel komparasi tahunan yang rapi dan mudah dibaca."
        ]
    },
    {
        "category": "suku_cadang_inventori",
        "title": "Aturan Sparepart, Suku Cadang, & Inventori Gudang",
        "keywords": [
            "sparepart", "spare part", "suku cadang", "part", "onderdil", "oli",
            "pelumas", "item", "stok", "stock", "inventori", "gudang", "pembelian",
            "invt", "prtt", "partcounter", "pembebananpart"
        ],
        "primary_tables": ["srvm_parts", "srvt_stockparts", "srvt_partcounterfakturdetail", "srvt_wodetail", "invt_item"],
        "guidelines": [
            "Tabel master katalog suku cadang / sparepart adalah 'srvm_parts' (kolom: kode, nama, hargajual, hargabeli, cogs, lokasi, minstock, maxstock, status). Kolom nama suku cadang adalah 'nama' (BUKAN namapart atau nama_part).",
            "Tabel transaksi penjualan sparepart counter adalah 'srvt_partcounterfakturdetail' (kolom: nomor_faktur, kode_parts, qty, harga, subtotal).",
            "Tabel pemakaian suku cadang pada pekerjaan bengkel (Work Order) adalah 'srvt_wodetail' (kolom: part untuk nilai nominal uang sparepart, filter part > 0).",
            "Tabel stok fisik suku cadang gudang bengkel adalah 'srvt_stockparts' (kolom: kode_parts, stockawal, masuk, keluar, booking, cogs). Rumus menghitung sisa stok fisik sparepart di gudang adalah: stockawal + masuk - keluar (BUKAN kolom saldoakhir).",
            "Untuk menyajikan nama sparepart saat menganalisis stok fisik gudang, hubungkan tabel: srvt_stockparts.kode_parts = srvm_parts.kode."
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
    },
    {
        "category": "spk_dan_pemesanan",
        "title": "Aturan Surat Pemesanan Kendaraan (SPK) & Batal SPK",
        "keywords": [
            "spk", "surat pesanan", "taking spk", "batal spk", "outstanding spk",
            "pesanan kendaraan", "booking fee", "untt_pesanankendaraan"
        ],
        "primary_tables": ["untt_pesanankendaraan", "untt_penjualan", "glbm_customer"],
        "guidelines": [
            "Tabel utama SPK / pemesanan kendaraan adalah 'untt_pesanankendaraan'.",
            "Untuk mengambil volume SPK masuk (Taking SPK) gunakan COUNT(untt_pesanankendaraan.nomor).",
            "Untuk SPK Batal filter untt_pesanankendaraan.batal = true.",
            "Untuk SPK Sah / Valid filter untt_pesanankendaraan.batal = false.",
            "Untuk Outstanding SPK (SPK belum terbit faktur jual) gunakan NOT EXISTS atau LEFT JOIN ke untt_penjualan di mana untt_penjualan.nomor IS NULL."
        ]
    },
    {
        "category": "bengkel_gr_bp_dan_sa",
        "title": "Aturan Bengkel GR vs BP & Produktivitas Service Advisor (SA)",
        "keywords": [
            "gr", "general repair", "bp", "body repair", "body paint", "unit entry",
            "sa", "service advisor", "batal wo", "faktur servis", "womt_wo"
        ],
        "primary_tables": ["womt_wo", "womt_wopart", "womt_wojasa"],
        "guidelines": [
            "Unit entry mengukur jumlah unit kendaraan masuk servis: COUNT(womt_wo.nomor).",
            "Tipe servis dipilah melalui jenis/kategori WO (GR untuk General Repair, BP untuk Body & Paint).",
            "Produktivitas Service Advisor (SA) dikelompokkan berdasarkan kolom womt_wo.kode_sa atau womt_wo.nama_sa.",
            "Batal Work Order (WO) diidentifikasi dengan womt_wo.batal = true.",
            "Rata-rata revenue per faktur servis dihitung: SUM(nilai_total) / COUNT(nomor)."
        ]
    },
    {
        "category": "ar_ap_aging_keuangan",
        "title": "Aturan Piutang (AR), Hutang (AP), dan Margin Profit Dealer",
        "keywords": [
            "ar", "piutang", "aging", "leasing", "ar leasing", "ar tunai",
            "ap", "hutang", "supplier", "hpp", "profit", "diskon", "discount", "margin"
        ],
        "primary_tables": ["untt_penjualan", "womt_wo", "invt_pembelian"],
        "guidelines": [
            "Perhitungan Profit Penjualan Unit = untt_penjualan.hjakhir - COALESCE(untt_penjualan.hpp, 0).",
            "Dampak Diskon Penjualan Unit dihitung dari kolom untt_penjualan.diskon atau (untt_penjualan.hargajual - untt_penjualan.hjakhir).",
            "AR Leasing mengukur piutang ke institusi pembiayaan rekanan (Leasing A, B, C).",
            "AP (Account Payable) mengukur hutang pembelian suku cadang (parts), bahan bengkel (oli/cat), dan ongkos pekerjaan luar (OPL) ke vendor/supplier."
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
