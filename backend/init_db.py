import asyncio
import asyncpg
import os
import bcrypt
from dotenv import load_dotenv

load_dotenv()

MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "sql", "migrations")


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
        path = os.path.join(MIGRATIONS_DIR, fname)
        with open(path, "r", encoding="utf-8") as f:
            sql = f.read().replace("\r", "")

        print(f"  applying migration: {fname} ...")
        try:
            async with conn.transaction():
                for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
                    await conn.execute(stmt)
                await conn.execute(
                    "INSERT INTO _migrations (filename) VALUES ($1)", fname
                )
        except Exception as e:
            print(f"  ❌ migration {fname} gagal: {e}")
            raise


async def init_db():
    dsn = f"postgresql://{os.getenv('CORE_DB_USER')}:{os.getenv('CORE_DB_PASSWORD')}@{os.getenv('CORE_DB_HOST')}:{os.getenv('CORE_DB_PORT')}/{os.getenv('CORE_DB_NAME')}"
    conn = await asyncpg.connect(dsn)
    try:
        # 1. Baca file DDL dasar (hapus karakter \r agar kompatibel Windows)
        ddl_path = os.path.join(os.path.dirname(__file__), "sql", "1_SCHEMA_BASE.sql")
        if os.path.exists(ddl_path):
            with open(ddl_path, "r", encoding="utf-8") as f:
                ddl = f.read().replace("\r", "")
            statements = [stmt.strip() for stmt in ddl.split(";") if stmt.strip()]
            for stmt in statements:
                try:
                    await conn.execute(stmt)
                except Exception as e:
                    # DDL dasar bersifat idempotent-by-drop; error minor dilewati
                    print(f"Warning: Gagal menjalankan statement: {stmt[:50]}... Error: {e}")
            print("✅ Database schema created/ensured.")
        else:
            print("❌ 1_SCHEMA_BASE.sql tidak ditemukan di backend/sql/")
            return

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

            await conn.execute("""
                INSERT INTO user_branches (user_id, branches_code) VALUES ($1, $2)
                ON CONFLICT (user_id, branches_code) DO NOTHING
            """, admin_id, "JKT_01")
            await conn.execute("""
                INSERT INTO user_branches (user_id, branches_code) VALUES ($1, $2)
                ON CONFLICT (user_id, branches_code) DO NOTHING
            """, admin_id, "SBY_02")
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
