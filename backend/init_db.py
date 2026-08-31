import asyncio
import asyncpg
import os
import re
import bcrypt
import subprocess
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "sql", "migrations")


def _is_comment_only(stmt: str) -> bool:
    """True jika statement hanya berisi komentar SQL (tanpa perintah).

    asyncpg 0.30 mem-bug AttributeError saat mengeksekusi statement
    yang hasilnya kosong (komentar murni) — kita lewati saja.
    """
    no_strings = re.sub(r"'[^']*'", "''", stmt)
    lines = [line.strip() for line in no_strings.splitlines()]
    return all(line == "" or line.startswith("--") for line in lines)


async def run_migrations(conn):
    """
    Jalankan semua file .sql di sql/migrations/ secara terurut.
    Idempotent: file dengan nama yang sama tidak dijalankan dua kali
    (dilacak lewat tabel _migrations).
    """
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            filename VARCHAR(255) PRIMARY KEY,
            applied_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )
    """)
    applied = {r["filename"] for r in await conn.fetch("SELECT filename FROM _migrations")}

    if not os.path.isdir(MIGRATIONS_DIR):
        return

    for fname in sorted(os.listdir(MIGRATIONS_DIR)):
        if not fname.endswith(".sql") or fname in applied:
            continue
        # File *_rollback.sql hanya dokumentasi rollback manual — TIDAK boleh
        # ter-apply otomatis, isinya justru membatalkan migration induknya
        # (mis. 005_knowledge_base_rollback.sql drop kolom buatan 005).
        if fname.endswith("_rollback.sql"):
            continue
        path = os.path.join(MIGRATIONS_DIR, fname)
        with open(path, "r", encoding="utf-8") as f:
            sql = f.read().replace("\r\n", "\n")

        print(f"  applying migration: {fname} ...")
        try:
            async with conn.transaction():
                for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
                    if _is_comment_only(stmt):
                        continue  # asyncpg bug pada statement tanpa hasil
                    await conn.execute(stmt)
                await conn.execute(
                    "INSERT INTO _migrations (filename) VALUES ($1)", fname
                )
        except Exception as e:
            print(f"  ❌ migration {fname} gagal: {e}")
            raise


async def init_db():
    dsn = f"postgresql://{os.getenv('CORE_DB_USER')}:{os.getenv('CORE_DB_PASSWORD')}@{os.getenv('CORE_DB_HOST')}:{os.getenv('CORE_DB_PORT')}/{os.getenv('CORE_DB_NAME')}"

    # 0. Auto-backup (jaring penyelamat) — dump database SEBELUM menyentuh apa pun.
    #    Insiden 2026-08-31: DDL lama DROP-CREATE semua tabel di DB live tanpa backup.
    db_name = os.getenv('CORE_DB_NAME', 'ai-dms')
    backup_dir = os.path.join(os.path.dirname(__file__), "backups")
    os.makedirs(backup_dir, exist_ok=True)
    dump_path = os.path.join(backup_dir, f"{db_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql")
    env = os.environ.copy()
    env["PGPASSWORD"] = os.getenv('CORE_DB_PASSWORD', '')
    dump_cmd = [
        "docker", "exec", "dms_pg", "pg_dump",
        "-U", os.getenv('CORE_DB_USER', 'postgres'), "-d", db_name,
    ]
    try:
        dump = subprocess.run(dump_cmd, capture_output=True, text=True, timeout=120, env=env)
        if dump.returncode == 0 and dump.stdout.strip():
            with open(dump_path, "w", encoding="utf-8") as f:
                f.write(dump.stdout)
            print(f"💾 Backup tersimpan: {dump_path} ({len(dump.stdout)//1024} KB)")
        else:
            print(f"⚠️  Backup gagal (rc={dump.returncode}): {dump.stderr[:120]}")
            print("   DILANJUTKAN TANPA BACKUP — periksa sebelum melanjutkan.")
    except FileNotFoundError:
        print("⚠️  docker/pg_dump tidak tersedia — backup dilewati (mode dev murni?).")

    conn = await asyncpg.connect(dsn)
    try:
        # 1. Baca file DDL dasar (hapus karakter CR agar kompatibel Windows)
        ddl_path = os.path.join(os.path.dirname(__file__), "sql", "1_SCHEMA_BASE.sql")
        if os.path.exists(ddl_path):
            with open(ddl_path, "r", encoding="utf-8") as f:
                ddl = f.read().replace("\r", "")
            statements = [stmt.strip() for stmt in ddl.split(";") if stmt.strip()]
            for stmt in statements:
                try:
                    await conn.execute(stmt)
                except Exception as e:
                    # DDL kini IF NOT EXISTS (idempotent-safe); error minor dilewati
                    print(f"Warning: Gagal menjalankan statement: {stmt[:50]}... Error: {e}")
            print("✅ Database schema created/ensured (tanpa menghapus data).")
        else:
            print("❌ 1_SCHEMA_BASE.sql tidak ditemukan di backend/sql/")
            return

        # 1b. Jaga invarian "tercatat = benar-benar diterapkan":
        #     buang record migration yang tabel targetnya tidak ada (sisa DDL lama),
        #     sehingga migration relevan dijalankan ulang, bukan di-skip.
        #     (Insiden 2026-08-31: migration 003 tercatat applied sejak 26 Agu
        #      padahal tabel di-rebuild DDL lama → fitur registry tidak pernah aktif.)
        migrations_table_exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables WHERE table_name = '_migrations'
            )
        """)
        stale = 0
        if migrations_table_exists:
            stale = await conn.fetchval("""
                SELECT COUNT(*) FROM _migrations m
                WHERE m.filename IN ('003_db_connection_registry.sql')
                  AND NOT EXISTS (
                      SELECT 1 FROM information_schema.columns
                      WHERE table_name = 'tenants' AND column_name = 'db_connection_id'
                  )
            """)
        if stale:
            await conn.execute("DELETE FROM _migrations WHERE filename = '003_db_connection_registry.sql'")
            print("♻️  Record migration 003 basi dibuang — akan dijalankan ulang.")

        # 2. Migrasi inkremental (terlacak & idempotent)
        print("⏳ Menjalankan migrasi...")
        await run_migrations(conn)
        print("✅ Migrasi selesai.")

        # 3. Cek apakah users sudah ada
        count = await conn.fetchval("SELECT COUNT(*) FROM users")
        if count == 0:
            print("⏳ Seeding initial data...")

            await conn.execute("""
                INSERT INTO companies (code, name) VALUES ($1, $2)
                ON CONFLICT (code) DO NOTHING
            """, "CMP_01", "AutoDealer Corp")

            await conn.execute("""
                INSERT INTO branches (code, name, company_code) VALUES ($1, $2, $3)
                ON CONFLICT (code) DO NOTHING
            """, "JKT_01", "Jakarta", "CMP_01")
            await conn.execute("""
                INSERT INTO branches (code, name, company_code) VALUES ($1, $2, $3)
                ON CONFLICT (code) DO NOTHING
            """, "SBY_02", "Surabaya", "CMP_01")

            admin_hash = bcrypt.hashpw("admin123".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            admin_id = await conn.fetchval("""
                INSERT INTO users (username, password_hash, email, role) VALUES ($1, $2, $3, $4)
                ON CONFLICT (username) DO NOTHING
                RETURNING id
            """, "admin", admin_hash, "admin@dms.com", "admin")
            if admin_id is None:
                admin_id = await conn.fetchval("SELECT id FROM users WHERE username = $1", "admin")

            user_hash = bcrypt.hashpw("user123".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            user_id = await conn.fetchval("""
                INSERT INTO users (username, password_hash, email, role) VALUES ($1, $2, $3, $4)
                ON CONFLICT (username) DO NOTHING
                RETURNING id
            """, "user_jkt", user_hash, "user.jkt@dms.com", "user")
            if user_id is None:
                user_id = await conn.fetchval("SELECT id FROM users WHERE username = $1", "user_jkt")

            # Keputusan domain (2026-08-31): admin = pengatur sistem (orang FBS),
            # TIDAK punya penugasan cabang. Cabang hanya untuk role user.
            await conn.execute("""
                INSERT INTO user_branches (user_id, branches_code) VALUES ($1, $2)
                ON CONFLICT (user_id, branches_code) DO NOTHING
            """, user_id, "JKT_01")

            print("✅ Seeding complete! Users: admin/admin123, user_jkt/user123")
        else:
            print("✅ Database already seeded. Skipping.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(init_db())
