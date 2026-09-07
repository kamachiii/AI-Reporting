"""Script Seeding & Sinkronisasi Knowledge Base 3S (Global KB vs Tenant KB).

1. Menambahkan 8 Golden Few-Shot Dealership Templates ke global_knowledge_base.
2. Vektorisasi 8 Golden Templates ke tenant_vector_kb (branch_code = 'GLOBAL').
3. Vektorisasi seluruh aturan Automotive Domain Thesaurus ke tenant_vector_kb.
4. Memperbarui knowledge_base JSONB pada tabel tenants untuk TST_01 (Allowlist 12 tabel, catatan kolom, relasi, glossary).
"""
import asyncio
import json
import logging
import time
import asyncpg
from app.core.config import settings
from app.services.automotive_thesaurus import ambil_semua_aturan_thesaurus
from app.services.vanna_pgvector import hitung_embedding, injeksi_thesaurus_ke_pgvector, simpan_vektor_item

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# 8 Golden Few-Shot Dealership Templates
GOLDEN_TEMPLATES = [
    {
        "question": "Bandingkan performa tiap divisi dalam tiap tahunnya",
        "category": "komparasi_performa_tahunan",
        "title": "Komparasi Performa Tahunan Operasional",
        "tables": ["untt_penjualan", "srvt_wo", "srvt_wodetail"],
        "sql": """SELECT 
    tahun,
    COALESCE(SUM(omzet_unit), 0) AS omzet_penjualan_unit,
    COALESCE(SUM(unit_terjual), 0) AS volume_unit_terjual,
    COALESCE(SUM(omzet_servis), 0) AS omzet_servis_bengkel,
    COALESCE(SUM(unit_servis), 0) AS volume_unit_entry,
    COALESCE(SUM(omzet_sparepart), 0) AS omzet_sparepart_bengkel
FROM (
    SELECT 
        EXTRACT(YEAR FROM tanggal)::INT AS tahun,
        SUM(hjakhir) AS omzet_unit,
        COUNT(nomor) AS unit_terjual,
        0::NUMERIC AS omzet_servis,
        0::BIGINT AS unit_servis,
        0::NUMERIC AS omzet_sparepart
    FROM untt_penjualan
    WHERE NOT COALESCE(batal, FALSE) AND NOT COALESCE(retur, FALSE)
    GROUP BY EXTRACT(YEAR FROM tanggal)::INT
    UNION ALL
    SELECT 
        EXTRACT(YEAR FROM tanggal)::INT AS tahun,
        0::NUMERIC AS omzet_unit,
        0::BIGINT AS unit_terjual,
        SUM(totalestimasibiaya) AS omzet_servis,
        COUNT(nomor) AS unit_servis,
        0::NUMERIC AS omzet_sparepart
    FROM srvt_wo
    WHERE NOT COALESCE(batal, FALSE)
    GROUP BY EXTRACT(YEAR FROM tanggal)::INT
    UNION ALL
    SELECT 
        EXTRACT(YEAR FROM w.tanggal)::INT AS tahun,
        0::NUMERIC AS omzet_unit,
        0::BIGINT AS unit_terjual,
        0::NUMERIC AS omzet_servis,
        0::BIGINT AS unit_servis,
        SUM(d.part) AS omzet_sparepart
    FROM srvt_wodetail d
    JOIN srvt_wo w ON d.nomor_wo = w.nomor
    WHERE NOT COALESCE(w.batal, FALSE) AND d.part > 0
    GROUP BY EXTRACT(YEAR FROM w.tanggal)::INT
) sub
GROUP BY tahun
ORDER BY tahun DESC;"""
    },
    {
        "question": "Tren penjualan unit dan omzet per bulan",
        "category": "penjualan_unit",
        "title": "Tren Omzet dan Volume Penjualan Unit Kendaraan Bulanan",
        "tables": ["untt_penjualan"],
        "sql": """SELECT 
    TO_CHAR(DATE_TRUNC('month', tanggal), 'YYYY-MM') AS bulan,
    COUNT(nomor) AS volume_unit,
    COALESCE(SUM(hjakhir), 0) AS total_omzet
FROM untt_penjualan
WHERE NOT COALESCE(batal, FALSE) AND NOT COALESCE(retur, FALSE)
GROUP BY DATE_TRUNC('month', tanggal)
ORDER BY DATE_TRUNC('month', tanggal) DESC
LIMIT 24;"""
    },
    {
        "question": "Unit entry dan pendapatan jasa servis bengkel per bulan",
        "category": "servis_bengkel",
        "title": "Tren Unit Entry dan Total Estimasi Biaya Servis Bengkel Bulanan",
        "tables": ["srvt_wo"],
        "sql": """SELECT 
    TO_CHAR(DATE_TRUNC('month', tanggal), 'YYYY-MM') AS bulan,
    COUNT(nomor) AS unit_entry,
    COALESCE(SUM(totalestimasibiaya), 0) AS total_estimasi_biaya
FROM srvt_wo
WHERE NOT COALESCE(batal, FALSE)
GROUP BY DATE_TRUNC('month', tanggal)
ORDER BY DATE_TRUNC('month', tanggal) DESC
LIMIT 24;"""
    },
    {
        "question": "Top 10 sparepart dengan nilai penjualan tertinggi di bengkel",
        "category": "suku_cadang_inventori",
        "title": "Peringkat 10 Suku Cadang Terlaris Berdasarkan Nilai Nominal Pemakaian WO",
        "tables": ["srvt_wodetail", "srvt_wo"],
        "sql": """SELECT 
    d.nama_tasklist AS nama_sparepart,
    COUNT(d.nomor_wo) AS frekuensi_pemakaian,
    COALESCE(SUM(d.part), 0) AS total_nilai_penjualan
FROM srvt_wodetail d
JOIN srvt_wo w ON d.nomor_wo = w.nomor
WHERE NOT COALESCE(w.batal, FALSE) AND d.part > 0
GROUP BY d.nama_tasklist
ORDER BY total_nilai_penjualan DESC
LIMIT 10;"""
    },
    {
        "question": "Top 10 customer dengan pembelian unit terbanyak",
        "category": "pelanggan_customer",
        "title": "Peringkat 10 Pelanggan dengan Pembelian Unit Kendaraan Terbanyak (2-Hop SPK)",
        "tables": ["untt_penjualan", "untt_pesanankendaraan", "glbm_customer"],
        "sql": """SELECT 
    c.nomor AS kode_customer,
    c.nama AS nama_customer,
    c.kota,
    COUNT(p.nomor) AS total_unit_dibeli,
    COALESCE(SUM(p.hjakhir), 0) AS total_pembelian
FROM untt_penjualan p
JOIN untt_pesanankendaraan spk ON p.nomor_pesanan = spk.nomor
JOIN glbm_customer c ON spk.nomor_customer = c.nomor
WHERE NOT COALESCE(p.batal, FALSE) AND NOT COALESCE(p.retur, FALSE)
GROUP BY c.nomor, c.nama, c.kota
ORDER BY total_pembelian DESC
LIMIT 10;"""
    },
    {
        "question": "Bandingkan pembelian unit kendaraan tahun 2025 dan 2026",
        "category": "pembelian_unit",
        "title": "Perbandingan Pembelian Stok Unit Kendaraan Tahun 2025 vs 2026",
        "tables": ["untt_pembelian"],
        "sql": """SELECT 
    EXTRACT(YEAR FROM tglinvoice)::INT AS tahun_invoice,
    COUNT(nomor) AS total_unit_dibeli,
    COALESCE(SUM(hpunit), 0) AS total_nilai_pembelian
FROM untt_pembelian
WHERE EXTRACT(YEAR FROM tglinvoice) IN (2025, 2026)
GROUP BY EXTRACT(YEAR FROM tglinvoice)::INT
ORDER BY tahun_invoice ASC;"""
    },
    {
        "question": "Stok unit kendaraan per tipe mobil",
        "category": "stok_unit",
        "title": "Jumlah Ketersediaan Stok Unit Kendaraan Ready Berdasarkan Tipe Mobil",
        "tables": ["untt_datakendaraan", "untm_tipe"],
        "sql": """SELECT 
    t.kode AS kode_tipe,
    t.nama AS nama_tipe,
    COUNT(k.norangka) AS total_unit_ready
FROM untt_datakendaraan k
JOIN untm_tipe t ON k.kode_tipe = t.kode
GROUP BY t.kode, t.nama
ORDER BY total_unit_ready DESC
LIMIT 20;"""
    },
    {
        "question": "Stok sparepart bengkel yang menipis",
        "category": "suku_cadang_inventori",
        "title": "Daftar Suku Cadang Bengkel dengan Sisa Stok Fisik Kritis (<= 5 Unit)",
        "tables": ["srvt_stockparts"],
        "sql": """SELECT 
    kode_parts,
    (stockawal + masuk - keluar) AS sisa_stok,
    cogs AS harga_pokok
FROM srvt_stockparts
WHERE (stockawal + masuk - keluar) <= 5 AND (stockawal + masuk - keluar) >= 0
ORDER BY sisa_stok ASC
LIMIT 25;"""
    }
]

# Definisi Tenant KB Terstruktur untuk TST_01
TENANT_KB_TST_01 = {
    "tabel_diizinkan": [
        "untt_penjualan",
        "untt_pembelian",
        "untt_pesanankendaraan",
        "untt_datakendaraan",
        "untm_tipe",
        "untm_model",
        "srvt_wo",
        "srvt_wodetail",
        "srvt_stockparts",
        "glbm_customer",
        "glbm_cabang",
        "vw_untt_penjualan"
    ],
    "tabel_dilarang": [],
    "kolom_dikecualikan": [],
    "catatan_kolom": {
        "untt_penjualan.nomor": "Nomor faktur penjualan kendaraan",
        "untt_penjualan.tanggal": "timestamp tanggal transaksi penjualan",
        "untt_penjualan.nomor_pesanan": "Nomor pesanan kendaraan / SPK yang mendasari transaksi penjualan",
        "untt_penjualan.batal": "boolean, filter penjualan sah: batal = false",
        "untt_penjualan.retur": "boolean, filter penjualan sah: retur = false",
        "untt_penjualan.hjakhir": "Total omzet / harga jual akhir kendaraan",
        "untt_penjualan.hjpokok": "Harga pokok penjualan kendaraan",
        "untt_penjualan.hargajual": "Harga jual bruto kendaraan",
        "untt_penjualan.diskon": "Nilai potongan diskon penjualan unit",
        "untt_pembelian.nomor": "Nomor faktur pembelian unit kendaraan",
        "untt_pembelian.hpdpp": "Harga beli kendaraan sebelum pajak / DPP (Dasar Pengenaan Pajak)",
        "untt_pembelian.hpppn": "Nilai PPN pembelian unit kendaraan",
        "untt_pembelian.hpunit": "Harga total pembelian unit kendaraan (total harga beli setelah DPP + PPN)",
        "untt_pembelian.tanggal": "Tanggal pembelian unit kendaraan (tipe timestamp)",
        "untt_pembelian.tglinvoice": "Tanggal invoice/transaksi pembelian kendaraan (tipe timestamp, kolom utama untuk filter waktu pembelian/transaksi)",
        "untt_pesanankendaraan.nomor": "Nomor SPK / Surat Pesanan Kendaraan",
        "untt_pesanankendaraan.nomor_customer": "Nomor referensi customer yang memesan unit kendaraan",
        "untt_pesanankendaraan.batal": "boolean, filter SPK sah: batal = false",
        "untt_datakendaraan.norangka": "Nomor rangka kendaraan / VIN",
        "untt_datakendaraan.kode_tipe": "Kode tipe kendaraan (FK ke untm_tipe.kode)",
        "untt_datakendaraan.thnpembuatan": "Tahun perakitan/pembuatan unit kendaraan (tipe varchar string tahun seperti '2025'/'2026', BUKAN tanggal transaksi)",
        "untm_tipe.kode": "kode tipe kendaraan (misal: 3K6A)",
        "untm_tipe.nama": "nama lengkap tipe kendaraan (misal: WR-V 1.5 E MT)",
        "untm_tipe.aktif": "boolean, tipe aktif jika aktif = true",
        "untm_model.kode": "kode model kendaraan",
        "untm_model.nama": "nama model kendaraan (misal: BR-V, HR-V, CR-V, BRIO)",
        "srvt_wo.nomor": "Nomor Work Order (PKB) servis bengkel",
        "srvt_wo.tanggal": "timestamp tanggal masuk kendaraan / buka WO servis",
        "srvt_wo.nomor_customer": "Nomor referensi customer yang servis kendaraan (FK ke glbm_customer.nomor)",
        "srvt_wo.nopolisi": "Nomor polisi kendaraan yang diservis",
        "srvt_wo.norangka": "Nomor rangka kendaraan yang diservis (FK ke untt_datakendaraan.norangka)",
        "srvt_wo.totalestimasibiaya": "Nilai total estimasi biaya servis / faktur WO bengkel",
        "srvt_wo.batal": "boolean, filter work order bengkel yang valid: batal = false",
        "srvt_wodetail.nomor_wo": "Nomor WO referensi ke srvt_wo.nomor",
        "srvt_wodetail.nama_tasklist": "Nama pekerjaan perbaikan, keluhan, atau nama suku cadang yang dipasang",
        "srvt_wodetail.jasa": "Nilai moneter ongkos jasa servis bengkel (SUM(jasa) WHERE jasa > 0)",
        "srvt_wodetail.part": "Nilai moneter pemakaian suku cadang bengkel (SUM(part) WHERE part > 0)",
        "srvt_wodetail.bahan": "Nilai moneter pemakaian bahan (oli, cat, grease) di bengkel",
        "srvt_stockparts.kode_parts": "Kode unik suku cadang di gudang bengkel",
        "srvt_stockparts.stockawal": "Jumlah stok awal suku cadang periode berjalan",
        "srvt_stockparts.masuk": "Jumlah penerimaan/masuk suku cadang ke gudang",
        "srvt_stockparts.keluar": "Jumlah pengeluaran/terjual suku cadang dari gudang",
        "srvt_stockparts.cogs": "Harga pokok penjualan (HPP) / cost of goods sold per unit sparepart",
        "glbm_customer.nomor": "Nomor ID customer unik",
        "glbm_customer.nama": "Nama lengkap customer / perusahaan",
        "glbm_customer.kota": "Kota domisili customer",
        "glbm_cabang.kode": "Kode cabang dealer",
        "glbm_cabang.nama": "Nama cabang dealer",
        "vw_untt_penjualan.nomor": "Nomor faktur / penjualan unit kendaraan",
        "vw_untt_penjualan.namacustomer": "Nama customer pembeli unit kendaraan"
    },
    "relasi_tabel": [
        {
            "tabel": "untt_penjualan",
            "kolom": "nomor_pesanan",
            "merujuk_tabel": "untt_pesanankendaraan",
            "merujuk_kolom": "nomor"
        },
        {
            "tabel": "untt_pesanankendaraan",
            "kolom": "nomor_customer",
            "merujuk_tabel": "glbm_customer",
            "merujuk_kolom": "nomor"
        },
        {
            "tabel": "untt_penjualan",
            "kolom": "norangka",
            "merujuk_tabel": "untt_datakendaraan",
            "merujuk_kolom": "norangka"
        },
        {
            "tabel": "untt_pembelian",
            "kolom": "norangka",
            "merujuk_tabel": "untt_datakendaraan",
            "merujuk_kolom": "norangka"
        },
        {
            "tabel": "untt_datakendaraan",
            "kolom": "kode_tipe",
            "merujuk_tabel": "untm_tipe",
            "merujuk_kolom": "kode"
        },
        {
            "tabel": "untm_tipe",
            "kolom": "kode_model",
            "merujuk_tabel": "untm_model",
            "merujuk_kolom": "kode"
        },
        {
            "tabel": "srvt_wo",
            "kolom": "nomor_customer",
            "merujuk_tabel": "glbm_customer",
            "merujuk_kolom": "nomor"
        },
        {
            "tabel": "srvt_wo",
            "kolom": "norangka",
            "merujuk_tabel": "untt_datakendaraan",
            "merujuk_kolom": "norangka"
        },
        {
            "tabel": "srvt_wodetail",
            "kolom": "nomor_wo",
            "merujuk_tabel": "srvt_wo",
            "merujuk_kolom": "nomor"
        },
        {
            "tabel": "untt_penjualan",
            "kolom": "kode_cabang",
            "merujuk_tabel": "glbm_cabang",
            "merujuk_kolom": "kode"
        },
        {
            "tabel": "srvt_wo",
            "kolom": "kode_cabang",
            "merujuk_tabel": "glbm_cabang",
            "merujuk_kolom": "kode"
        }
    ],
    "glossary": [
        {
            "istilah": "performa divisi",
            "arti": "Performa operasional gabungan: Penjualan Unit (untt_penjualan), Servis Bengkel (srvt_wo), dan Suku Cadang Bengkel (srvt_wodetail.part > 0)"
        },
        {
            "istilah": "unit entry",
            "arti": "Jumlah kunjungan servis / unit mobil masuk bengkel: COUNT(srvt_wo.nomor) WHERE batal = false"
        },
        {
            "istilah": "omzet jasa servis",
            "arti": "Total pendapatan jasa servis bengkel: SUM(srvt_wodetail.jasa) atau SUM(srvt_wo.totalestimasibiaya)"
        },
        {
            "istilah": "penjualan sparepart bengkel",
            "arti": "Total penjualan sparepart pada pekerjaan bengkel: SUM(srvt_wodetail.part) WHERE part > 0"
        },
        {
            "istilah": "sisa stok sparepart",
            "arti": "Sisa fisik sparepart di gudang: (stockawal + masuk - keluar) dari srvt_stockparts"
        },
        {
            "istilah": "harga total pembelian",
            "arti": "untt_pembelian.hpunit (nilai total DPP + PPN)"
        },
        {
            "istilah": "harga beli sebelum pajak",
            "arti": "untt_pembelian.hpdpp"
        },
        {
            "istilah": "customer penjualan",
            "arti": "Data customer pembeli unit terhubung melalui untt_penjualan.nomor_pesanan -> untt_pesanankendaraan.nomor, lalu untt_pesanankendaraan.nomor_customer -> glbm_customer.nomor, atau view vw_untt_penjualan.namacustomer"
        }
    ],
    "nilai_map": {},
    "contoh_tanya": [
        "Bandingkan performa tiap divisi dalam tiap tahunnya",
        "Tren penjualan unit dan omzet per bulan",
        "Unit entry dan pendapatan jasa servis bengkel per bulan",
        "Top 10 sparepart dengan nilai penjualan tertinggi di bengkel",
        "Top 10 customer dengan pembelian unit terbanyak",
        "Bandingkan pembelian unit kendaraan tahun 2025 dan 2026",
        "Stok unit kendaraan per tipe mobil",
        "Stok sparepart bengkel yang menipis"
    ]
}


async def seed_global_kb(conn):
    logger.info("=== 1. MENYIMPAN 8 GOLDEN TEMPLATES KE global_knowledge_base ===")
    for item in GOLDEN_TEMPLATES:
        q = item["question"]
        sql = item["sql"].strip()
        meta = json.dumps({
            "category": item["category"],
            "title": item["title"],
            "tables": item["tables"]
        })
        content = f"Question: {q}\nSQL: {sql}"

        # Periksa apakah sudah ada berdasarkan pertanyaan
        existing = await conn.fetchrow(
            "SELECT id FROM global_knowledge_base WHERE kind = 'example' AND question = $1",
            q
        )
        if existing:
            await conn.execute(
                """
                UPDATE global_knowledge_base
                SET content = $1, sql_example = $2, metadata = $3::jsonb, updated_at = CURRENT_TIMESTAMP
                WHERE id = $4
                """,
                content, sql, meta, existing["id"]
            )
            logger.info("Diperbarui: [%d] %s", existing["id"], q)
        else:
            new_id = await conn.fetchval(
                """
                INSERT INTO global_knowledge_base (kind, content, question, sql_example, metadata, created_at, updated_at)
                VALUES ('example', $1, $2, $3, $4::jsonb, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                RETURNING id
                """,
                content, q, sql, meta
            )
            logger.info("Ditambahkan: [%d] %s", new_id, q)


async def vectorize_golden_templates(conn):
    logger.info("=== 2. VEKTORISASI 8 GOLDEN TEMPLATES KE tenant_vector_kb (GLOBAL) ===")
    for item in GOLDEN_TEMPLATES:
        q = item["question"]
        sql = item["sql"].strip()
        text_to_embed = f"Question: {q}\nSQL: {sql}"
        
        vec = await hitung_embedding(text_to_embed, provider="local")
        v_id = await simpan_vektor_item(
            conn,
            branch_code="GLOBAL",
            item_type="sql_example",
            content=sql,
            embedding=vec,
            metadata={
                "question": q,
                "category": item["category"],
                "title": item["title"],
                "tables": item["tables"],
                "trained_at": time.time()
            }
        )
        logger.info("Vektor tersimpan: [%d] for question '%s'", v_id, q)


async def vectorize_thesaurus(conn):
    logger.info("=== 3. VEKTORISASI ATURAN AUTOMOTIVE THESAURUS KE tenant_vector_kb (GLOBAL) ===")
    count = await injeksi_thesaurus_ke_pgvector(conn, embedding_provider="local")
    logger.info("Total aturan thesaurus tervektorisasi: %d", count)


async def update_tenant_kb_tst01(conn):
    logger.info("=== 4. MEMPERBARUI TENANT KB UNTUK TST_01 PADA TABEL tenants ===")
    kb_json = json.dumps(TENANT_KB_TST_01)
    await conn.execute(
        """
        UPDATE tenants
        SET knowledge_base = $1::jsonb, updated_at = CURRENT_TIMESTAMP
        WHERE branch_code = 'TST_01'
        """,
        kb_json
    )
    logger.info("Berhasil memperbarui tenant KB TST_01 (Allowlist 12 tabel, catatan kolom, relasi, glossary)")


async def main():
    conn = await asyncpg.connect(
        host=settings.core_db_host,
        port=settings.core_db_port,
        user=settings.core_db_user,
        password=settings.core_db_password,
        database=settings.core_db_name
    )
    try:
        await seed_global_kb(conn)
        await vectorize_golden_templates(conn)
        await vectorize_thesaurus(conn)
        await update_tenant_kb_tst01(conn)
        logger.info("=== SEMUA PROSES SEEDING & SINKRONISASI KB 3S SELESAI DENGAN SUKSES! ===")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
