import asyncio
import json
import asyncpg
from app.core.config import settings
from app.services.tenant_pool import get_tenant_pool_manager
from app.services.chat_pipeline import resolve_tenant

async def main():
    conn = await asyncpg.connect(
        host=settings.core_db_host,
        port=settings.core_db_port,
        user=settings.core_db_user,
        password=settings.core_db_password,
        database=settings.core_db_name
    )

    print("=== ALL TENANTS IN CORE DB ===")
    t_list = await conn.fetch("SELECT id, branch_code FROM tenants")
    for t in t_list:
        print(f"  [{t['id']}] {t['branch_code']}")

    print("=== PGVECTOR / EMBEDDINGS TABLES ===")
    tables = await conn.fetch("""
        SELECT table_name FROM information_schema.tables 
        WHERE table_schema = 'public' AND (table_name ILIKE '%embed%' OR table_name ILIKE '%vec%' OR table_name ILIKE '%vanna%')
    """)
    for t in tables:
        tname = t['table_name']
        c = await conn.fetchval(f"SELECT count(*) FROM {tname}")
        print(f"Table {tname}: {c} rows")

    # Connect to tenant database TST_01
    print("\n=== CONNECTING TO TENANT DB TST_01 ===")
    tenant = await resolve_tenant(conn, "TST_01")
    pool_mgr = get_tenant_pool_manager()
    t_pool = await pool_mgr.get_pool(tenant)
    async with t_pool.acquire() as tconn:
        t_tables = await tconn.fetch("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        print(f"Total tables in tenant DB: {len(t_tables)}")
        
        # Look for key automotive tables: untt_ (unit), srvt_ (servis), prtt_ (part), glbm_ (global master), acct_ (accounting)
        categories = {}
        for t in t_tables:
            prefix = t['table_name'][:4].lower()
            categories[prefix] = categories.get(prefix, 0) + 1
        print("Table prefixes in tenant DB:", categories)

        queries = [
            ("Q1: Komparasi Divisi 3S", """
                SELECT 
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
                ORDER BY tahun DESC
            """),
            ("Q2: Tren Penjualan Unit", """
                SELECT 
                    TO_CHAR(DATE_TRUNC('month', tanggal), 'YYYY-MM') AS bulan,
                    COUNT(nomor) AS volume_unit,
                    COALESCE(SUM(hjakhir), 0) AS total_omzet
                FROM untt_penjualan
                WHERE NOT COALESCE(batal, FALSE) AND NOT COALESCE(retur, FALSE)
                GROUP BY DATE_TRUNC('month', tanggal)
                ORDER BY DATE_TRUNC('month', tanggal) DESC
                LIMIT 5
            """),
            ("Q3: Unit Entry & Biaya Servis", """
                SELECT 
                    TO_CHAR(DATE_TRUNC('month', tanggal), 'YYYY-MM') AS bulan,
                    COUNT(nomor) AS unit_entry,
                    COALESCE(SUM(totalestimasibiaya), 0) AS total_estimasi_biaya
                FROM srvt_wo
                WHERE NOT COALESCE(batal, FALSE)
                GROUP BY DATE_TRUNC('month', tanggal)
                ORDER BY DATE_TRUNC('month', tanggal) DESC
                LIMIT 5
            """),
            ("Q4: Top Sparepart Bengkel", """
                SELECT 
                    d.nama_tasklist AS nama_sparepart,
                    COUNT(d.nomor_wo) AS frekuensi_pemakaian,
                    COALESCE(SUM(d.part), 0) AS total_nilai_penjualan
                FROM srvt_wodetail d
                JOIN srvt_wo w ON d.nomor_wo = w.nomor
                WHERE NOT COALESCE(w.batal, FALSE) AND d.part > 0
                GROUP BY d.nama_tasklist
                ORDER BY total_nilai_penjualan DESC
                LIMIT 5
            """),
            ("Q5: Top Customer 2-Hop SPK", """
                SELECT 
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
                LIMIT 5
            """),
            ("Q6: Pembelian 2025 vs 2026", """
                SELECT 
                    EXTRACT(YEAR FROM tglinvoice)::INT AS tahun_invoice,
                    COUNT(nomor) AS total_unit_dibeli,
                    COALESCE(SUM(hpunit), 0) AS total_nilai_pembelian
                FROM untt_pembelian
                WHERE EXTRACT(YEAR FROM tglinvoice) IN (2025, 2026)
                GROUP BY EXTRACT(YEAR FROM tglinvoice)::INT
                ORDER BY tahun_invoice ASC
            """),
            ("Q7: Stok Unit per Tipe", """
                SELECT 
                    t.kode AS kode_tipe,
                    t.nama AS nama_tipe,
                    COUNT(k.norangka) AS total_unit_ready
                FROM untt_datakendaraan k
                JOIN untm_tipe t ON k.kode_tipe = t.kode
                GROUP BY t.kode, t.nama
                ORDER BY total_unit_ready DESC
                LIMIT 5
            """),
            ("Q8: Sisa Stok Sparepart Gudang", """
                SELECT 
                    kode_parts,
                    (stockawal + masuk - keluar) AS sisa_stok,
                    cogs AS harga_pokok
                FROM srvt_stockparts
                WHERE (stockawal + masuk - keluar) <= 5 AND (stockawal + masuk - keluar) >= 0
                ORDER BY sisa_stok ASC
                LIMIT 5
            """)
        ]

        print("\n=== TESTING 8 GOLDEN QUERIES ON TENANT DB ===")
        for label, q in queries:
            try:
                res = await tconn.fetch(q)
                print(f"[SUCCESS] {label}: {len(res)} baris kembali")
                if res:
                    print("   Contoh row 1:", dict(res[0]))
            except Exception as e:
                print(f"[FAILED] {label}: {e}")

if __name__ == "__main__":
    asyncio.run(main())
