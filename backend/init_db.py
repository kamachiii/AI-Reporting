import asyncio
import asyncpg
import os
import bcrypt
from dotenv import load_dotenv

load_dotenv()

async def init_db():
    dsn = f"postgresql://{os.getenv('CORE_DB_USER')}:{os.getenv('CORE_DB_PASSWORD')}@{os.getenv('CORE_DB_HOST')}:{os.getenv('CORE_DB_PORT')}/{os.getenv('CORE_DB_NAME')}"
    conn = await asyncpg.connect(dsn)
    try:
        # 1. Baca file DDL (hapus karakter \r agar kompatibel Windows)
        ddl_path = os.path.join(os.path.dirname(__file__), "sql", "2_DATABASE_DDL.sql")
        if os.path.exists(ddl_path):
            with open(ddl_path, "r", encoding="utf-8") as f:
                ddl = f.read()
            # Bersihkan dari karakter \r yang sering menyebabkan syntax error di Windows
            ddl = ddl.replace("\r", "")
            
            # Split per statement berdasarkan titik koma (;)
            statements = [stmt.strip() for stmt in ddl.split(";") if stmt.strip()]
            for stmt in statements:
                try:
                    await conn.execute(stmt)
                except Exception as e:
                    print(f"Warning: Gagal menjalankan statement: {stmt[:50]}... Error: {e}")
                    # Lewati error minor jika ada syntax yang tidak fatal (misal komentar)
            print("✅ Database schema created/ensured.")
        else:
            print("❌ DDL file not found. Make sure 2_DATABASE_DDL.sql exists in backend/sql/")
            return

        # 2. Cek apakah users sudah ada
        count = await conn.fetchval("SELECT COUNT(*) FROM users")
        if count == 0:
            print("⏳ Seeding initial data...")
            
            # Insert Company
            await conn.execute("""
                INSERT INTO companies (code, name) VALUES ($1, $2)
                ON CONFLICT (code) DO NOTHING
            """, "CMP_01", "AutoDealer Corp")
            
            # Insert Branches
            await conn.execute("""
                INSERT INTO branches (code, name, company_code) VALUES ($1, $2, $3)
                ON CONFLICT (code) DO NOTHING
            """, "JKT_01", "Jakarta", "CMP_01")
            await conn.execute("""
                INSERT INTO branches (code, name, company_code) VALUES ($1, $2, $3)
                ON CONFLICT (code) DO NOTHING
            """, "SBY_02", "Surabaya", "CMP_01")
            
            # Insert Admin
            admin_hash = bcrypt.hashpw("admin123".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            admin_id = await conn.fetchval("""
                INSERT INTO users (username, password_hash, email, role) VALUES ($1, $2, $3, $4)
                ON CONFLICT (username) DO NOTHING
                RETURNING id
            """, "admin", admin_hash, "admin@dms.com", "admin")
            if admin_id is None:
                admin_id = await conn.fetchval("SELECT id FROM users WHERE username = $1", "admin")
            
            # Insert User
            user_hash = bcrypt.hashpw("user123".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            user_id = await conn.fetchval("""
                INSERT INTO users (username, password_hash, email, role) VALUES ($1, $2, $3, $4)
                ON CONFLICT (username) DO NOTHING
                RETURNING id
            """, "user_jkt", user_hash, "user.jkt@dms.com", "user")
            if user_id is None:
                user_id = await conn.fetchval("SELECT id FROM users WHERE username = $1", "user_jkt")
            
            # Assign Branches
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