"""
F0.3 — Generator database tenant dummy (dealer mobil) untuk testing pipeline AI.

Membuat database 'dealer_dummy' di instance Postgres yang sama dengan core DB,
lalu mengisi 5 tabel dengan data realistis 12 bulan terakhir:
    kendaraan, pelanggan, penjualan, detail_penjualan, service_records

Pemakaian:
    python seed_tenant_dummy.py            # buat + seed bila belum ada data
    python seed_tenant_dummy.py --reset    # buang database lama, buat ulang dari nol

Setelah selesai, daftarkan kredensialnya di menu Admin > Database & Tenant
(host/port/user/password mengikuti CORE_DB_* di backend/.env; nama database
adalah TENANT_DUMMY_DB_NAME, default 'dealer_dummy').
"""
import argparse
import asyncio
import os
import random
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv

load_dotenv()

import asyncpg

DB_NAME = os.getenv("TENANT_DUMMY_DB_NAME", "dealer_dummy")
ADMIN_DB = "postgres"

random.seed(42)  # hasil reproducible

# (merek, model, harga pasaran IDR) — harga wajar pasar Indonesia
MODELS = [
    ("Toyota", "Avanza", 245_000_000), ("Toyota", "Calya", 158_000_000),
    ("Toyota", "Agya", 165_000_000), ("Toyota", "Rush", 282_000_000),
    ("Toyota", "Innova Zenix", 368_000_000), ("Toyota", "Fortuner", 512_000_000),
    ("Toyota", "Kijang Innova", 342_000_000), ("Toyota", "Veloz", 295_000_000),
    ("Daihatsu", "Xenia", 232_000_000), ("Daihatsu", "Sigra", 152_000_000),
    ("Daihatsu", "Terios", 258_000_000), ("Daihatsu", "Rocky", 246_000_000),
    ("Honda", "Brio", 168_000_000), ("Honda", "Jazz", 292_000_000),
    ("Honda", "HR-V", 318_000_000), ("Honda", "CR-V", 398_000_000),
    ("Honda", "BR-V", 262_000_000), ("Honda", "City Hatchback", 244_000_000),
    ("Mitsubishi", "Xpander", 258_000_000), ("Mitsubishi", "Pajero Sport", 498_000_000),
    ("Mitsubishi", "Xforce", 342_000_000), ("Suzuki", "Ertiga", 238_000_000),
    ("Suzuki", "Ignis", 198_000_000), ("Nissan", "Livina", 246_000_000),
]
WARNA = ["Putih", "Silver", "Hitam", "Abu-abu Metalik", "Merah", "Biru Metalik", "Coklat", "Krem"]
KOTA = ["Jakarta Selatan", "Jakarta Barat", "Jakarta Utara", "Tangerang", "Bekasi", "Depok", "Bogor", "Bandung"]
NAMA_DEPAN = ["Budi", "Siti", "Andi", "Rina", "Agus", "Dewi", "Hendra", "Maya", "Joko", "Lina",
              "Rudi", "Farah", "Tono", "Wati", "Bambang", "Sari", "Eko", "Nurul", "Dedi", "Yuni",
              "Fajar", "Ratna", "Gilang", "Intan", "Hadi", "Mega", "Reza", "Tika", "Wawan", "Zahra"]
NAMA_BELAKANG = ["Santoso", "Wijaya", "Pratama", "Saputra", "Hartono", "Kusuma", "Nugroho", "Halim",
                 "Setiawan", "Maulana", "Permana", "Salsabila", "Gunawan", "Lestari", "Ramadhan",
                 "Siregar", "Firmansyah", "Anggraini", "Purnama", "Handoko"]
SALES = ["Rian Sales", "Dina Sales", "Bayu Sales", "Sinta Sales", "Arif Sales", "Melati Sales"]
TEKNISI = ["Mas Yono", "Bang Ruli", "Pak Slamet", "Mbah Darmo", "Koh Aan", "Deni Mekanik"]
JENIS_SERVICE = [
    ("Service rutin 10.000 km", 850_000, 1_800_000),
    ("Ganti oli + filter", 450_000, 950_000),
    ("Service rutin 20.000 km", 1_500_000, 3_200_000),
    ("Ganti kampas rem", 900_000, 2_400_000),
    ("Tune up mesin", 1_200_000, 2_800_000),
    ("Perbaikan AC", 750_000, 3_500_000),
]
METODE = [("kredit", 0.65), ("tunai", 0.35)]
KOMPONEN_TETAP = ("harga_kendaraan",)


def _rupiah_bulat(x, ke=50_000):
    return int(round(x / ke) * ke)


def _pilih_weighted(pasangan):
    r = random.random()
    akum = 0.0
    for nilai, bobot in pasangan:
        akum += bobot
        if r <= akum:
            return nilai
    return pasangan[-1][0]


DDL = """
CREATE TABLE IF NOT EXISTS kendaraan (
    id SERIAL PRIMARY KEY,
    nomor_rangka VARCHAR(32) UNIQUE NOT NULL,
    nomor_mesin VARCHAR(32) UNIQUE NOT NULL,
    merek VARCHAR(50) NOT NULL,
    model VARCHAR(50) NOT NULL,
    tahun INT NOT NULL,
    warna VARCHAR(30) NOT NULL,
    harga_jual BIGINT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'tersedia',
    tanggal_masuk DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS pelanggan (
    id SERIAL PRIMARY KEY,
    nama VARCHAR(120) NOT NULL,
    no_telepon VARCHAR(20) NOT NULL,
    email VARCHAR(120),
    alamat TEXT,
    kota VARCHAR(60) NOT NULL,
    tanggal_daftar DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS penjualan (
    id SERIAL PRIMARY KEY,
    tanggal DATE NOT NULL,
    pelanggan_id INT NOT NULL REFERENCES pelanggan(id),
    kendaraan_id INT NOT NULL UNIQUE REFERENCES kendaraan(id),
    harga_deal BIGINT NOT NULL,
    metode_pembayaran VARCHAR(20) NOT NULL,
    uang_muka BIGINT NOT NULL DEFAULT 0,
    tenor_bulan INT,
    nama_sales VARCHAR(60),
    catatan TEXT
);

CREATE TABLE IF NOT EXISTS detail_penjualan (
    id SERIAL PRIMARY KEY,
    penjualan_id INT NOT NULL REFERENCES penjualan(id) ON DELETE CASCADE,
    komponen VARCHAR(40) NOT NULL,
    jumlah BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS service_records (
    id SERIAL PRIMARY KEY,
    kendaraan_id INT NOT NULL REFERENCES kendaraan(id) ON DELETE CASCADE,
    pelanggan_id INT REFERENCES pelanggan(id),
    tanggal_service DATE NOT NULL,
    jenis_service VARCHAR(60) NOT NULL,
    biaya BIGINT NOT NULL,
    km INT NOT NULL,
    teknisi VARCHAR(60),
    keterangan TEXT
);

CREATE INDEX IF NOT EXISTS idx_penjualan_tanggal ON penjualan(tanggal);
CREATE INDEX IF NOT EXISTS idx_service_tanggal ON service_records(tanggal_service);
CREATE INDEX IF NOT EXISTS idx_detail_penjualan ON detail_penjualan(penjualan_id);
"""


def _buat_kendaraan():
    hari_ini = date.today()
    baris = []
    for i in range(300):
        merek, model, harga = random.choice(MODELS)
        tahun = random.randint(2021, 2026)
        status = "terjual" if i < 240 else ("booking" if i < 260 else "tersedia")
        masuk = hari_ini - timedelta(days=random.randint(30, 700))
        rangka = f"MHKW{random.randint(40, 79)}PP{random.choice(['K','M','N'])}{random.randint(100000, 999999)}{i:03d}"
        mesin = f"1{random.randint(0, 5)}NR-FB{random.randint(1000000, 9999999)}{i:03d}"
        baris.append((rangka, mesin, merek, model, tahun, random.choice(WARNA), harga, status, masuk))
    random.shuffle(baris)
    # jaga urutan status tetap benar setelah shuffle: tetapkan ulang berdasar posisi
    hasil = []
    n_terjual, n_booking = 240, 20
    for idx, (rangka, mesin, merek, model, tahun, warna, harga, _, masuk) in enumerate(baris):
        status = "terjual" if idx < n_terjual else ("booking" if idx < n_terjual + n_booking else "tersedia")
        hasil.append((rangka, mesin, merek, model, tahun, warna, harga, status, masuk))
    return hasil


async def _db_ada(conn_admin, nama):
    return await conn_admin.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", nama)


async def main(reset: bool):
    host = os.getenv("CORE_DB_HOST", "localhost")
    port = int(os.getenv("CORE_DB_PORT", "5433"))
    user = os.getenv("CORE_DB_USER", "postgres")
    password = os.getenv("CORE_DB_PASSWORD", "postgres")

    conn_admin = await asyncpg.connect(
        host=host, port=port, user=user, password=password, database=ADMIN_DB)
    try:
        ada = await _db_ada(conn_admin, DB_NAME)
        if ada and not reset:
            print(f"Database '{DB_NAME}' sudah ada. Gunakan --reset untuk membuat ulang.")
            return
        if ada:
            print(f"Menghapus database lama '{DB_NAME}' ...")
            await conn_admin.execute(f'DROP DATABASE "{DB_NAME}" WITH (FORCE)')
        print(f"Membuat database '{DB_NAME}' ...")
        await conn_admin.execute(f'CREATE DATABASE "{DB_NAME}"')
    finally:
        await conn_admin.close()

    conn = await asyncpg.connect(host=host, port=port, user=user, password=password, database=DB_NAME)
    try:
        print("Membuat skema (5 tabel) ...")
        await conn.execute(DDL)

        # --- kendaraan ---
        kendaraan = _buat_kendaraan()
        await conn.executemany(
            """INSERT INTO kendaraan
               (nomor_rangka, nomor_mesin, merek, model, tahun, warna, harga_jual, status, tanggal_masuk)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)""", kendaraan)
        terjual = await conn.fetch(
            "SELECT id, harga_jual, tanggal_masuk FROM kendaraan WHERE status = 'terjual' ORDER BY id")

        # --- pelanggan ---
        hari_ini = date.today()
        pelanggan = []
        for i in range(80):
            nama = f"{random.choice(NAMA_DEPAN)} {random.choice(NAMA_BELAKANG)}"
            kota = random.choice(KOTA)
            pelanggan.append((
                nama, f"08{random.randint(11, 99)}{random.randint(10000000, 99999999)}",
                f"{nama.lower().replace(' ', '.')}@example.com",
                f"Jl. {random.choice(NAMA_BELAKANG)} No. {random.randint(1, 120)}, {kota}",
                kota, hari_ini - timedelta(days=random.randint(30, 720)),
            ))
        await conn.executemany(
            """INSERT INTO pelanggan (nama, no_telepon, email, alamat, kota, tanggal_daftar)
               VALUES ($1,$2,$3,$4,$5,$6)""", pelanggan)
        id_pelanggan = [r["id"] for r in await conn.fetch("SELECT id FROM pelanggan ORDER BY id")]

        # --- penjualan (1 kendaraan terjual = 1 transaksi) ---
        penjualan_rows = []
        for k in terjual:
            tanggal = k["tanggal_masuk"] + timedelta(days=random.randint(5, 60))
            if tanggal > hari_ini:
                tanggal = hari_ini - timedelta(days=random.randint(1, 20))
            deal = _rupiah_bulat(k["harga_jual"] * random.uniform(0.93, 1.0), 100_000)
            metode = _pilih_weighted(METODE)
            if metode == "kredit":
                dp = _rupiah_bulat(deal * random.uniform(0.2, 0.35))
                tenor = random.choice([12, 24, 36, 48, 60])
            else:
                dp, tenor = deal, None
            penjualan_rows.append((
                tanggal, random.choice(id_pelanggan), k["id"], deal, metode, dp, tenor,
                random.choice(SALES),
                random.choice([None, "Cash keras", "Trade-in unit lama", "Referral bengkel", None]),
            ))
        await conn.executemany(
            """INSERT INTO penjualan
               (tanggal, pelanggan_id, kendaraan_id, harga_deal, metode_pembayaran,
                uang_muka, tenor_bulan, nama_sales, catatan)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)""", penjualan_rows)
        penjualan_db = await conn.fetch(
            "SELECT id, tanggal, harga_deal, kendaraan_id, pelanggan_id FROM penjualan ORDER BY id")

        # --- detail_penjualan ---
        detail = []
        for p in penjualan_db:
            detail.append((p["id"], "harga_kendaraan", p["harga_deal"]))
            if random.random() < 0.6:
                detail.append((p["id"], "ppn", _rupiah_bulat(p["harga_deal"] * 0.1, 10_000)))
            detail.append((p["id"], "biaya_admin", random.choice([500_000, 1_000_000, 1_500_000, 2_000_000, 2_500_000])))
            if random.random() < 0.5:
                detail.append((p["id"], "aksesoris", _rupiah_bulat(random.uniform(500_000, 6_000_000))))
            if random.random() < 0.6:
                detail.append((p["id"], "asuransi", _rupiah_bulat(random.uniform(5_000_000, 18_000_000), 100_000)))
        await conn.executemany(
            "INSERT INTO detail_penjualan (penjualan_id, komponen, jumlah) VALUES ($1,$2,$3)", detail)

        # --- service_records ---
        services = []
        for p in penjualan_db:
            for _ in range(random.choices([0, 1, 2], weights=[35, 45, 20])[0]):
                jenis, bmin, bmax = random.choice(JENIS_SERVICE)
                tgl = p["tanggal"] + timedelta(days=random.randint(25, 330))
                if tgl > hari_ini:
                    continue
                services.append((
                    p["kendaraan_id"], p["pelanggan_id"], tgl,
                    jenis, _rupiah_bulat(random.uniform(bmin, bmax), 10_000),
                    random.randint(1_000, 45_000), random.choice(TEKNISI),
                    random.choice([None, "Unit garansi", "Pelanggan hasil penjualan", None]),
                ))
        if services:
            await conn.executemany(
                """INSERT INTO service_records
                   (kendaraan_id, pelanggan_id, tanggal_service, jenis_service, biaya, km, teknisi, keterangan)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8)""", services)

        # --- ringkasan ---
        stat = []
        for tabel in ("kendaraan", "pelanggan", "penjualan", "detail_penjualan", "service_records"):
            n = await conn.fetchval(f"SELECT COUNT(*) FROM {tabel}")
            stat.append((tabel, n))
        total_omzet = await conn.fetchval(
            "SELECT COALESCE(SUM(harga_deal),0) FROM penjualan WHERE tanggal >= CURRENT_DATE - INTERVAL '1 month'")
        print("\nSeed selesai. Ringkasan:")
        for tabel, n in stat:
            print(f"  {tabel:<18} {n:>6} baris")
        print(f"  omzet penjualan 30 hari terakhir: Rp {total_omzet:,.0f}".replace(",", "."))
        print(f"\nDaftarkan di admin: host={host} port={port} db={DB_NAME} user={user}")
    finally:
        await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generator DB tenant dummy (F0.3)")
    parser.add_argument("--reset", action="store_true", help="buang database lama & buat ulang")
    args = parser.parse_args()
    asyncio.run(main(args.reset))
