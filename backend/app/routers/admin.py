from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.core.database import get_core_pool
from app.core.security import require_admin_role, encrypt_credential, decrypt_credential
import asyncpg
import httpx
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin"])

# --- SCHEMA ---
class TenantCreate(BaseModel):
    branch_code: str
    db_host: str
    db_port: int = 5432
    db_name: str
    db_username: str
    db_password: str

class CompanyCreate(BaseModel):
    code: str
    name: str
    address: str = ""

class CompanyUpdate(BaseModel):
    name: str
    address: str = ""
    is_active: bool = True

class BranchCreate(BaseModel):
    code: str
    name: str
    company_code: str
    address: str = ""

class BranchUpdate(BaseModel):
    name: str
    address: str = ""
    is_active: bool = True

class AIConfigCreate(BaseModel):
    scope: str
    target_id: str = ""
    provider: str
    api_key: str
    model: str
    temperature: float = 0.7
    api_type: str = "openai"
    base_url: str = ""

class AIConfigUpdate(BaseModel):
    scope: str
    target_id: str = ""
    provider: str
    api_key: str = ""
    model: str
    temperature: float = 0.7
    api_type: str = "openai"
    base_url: str = ""

class AIConfigTestDraft(BaseModel):
    api_type: str
    base_url: str
    api_key: str = ""
    config_id: int | None = None

class FetchModelsRequest(BaseModel):
    provider: str
    api_key: str = ""
    api_type: str = "openai"
    base_url: str = ""
    config_id: int | None = None

# ==========================================
# 1. COMPANY & BRANCH ENDPOINTS
# ==========================================
@router.get("/companies")
async def get_companies(user: dict = Depends(require_admin_role)):
    try:
        pool = await get_core_pool()
        rows = await pool.fetch("SELECT code, name, address, is_active FROM companies")
        return [{"code": r["code"], "name": r["name"], "address": r["address"], "is_active": r["is_active"]} for r in rows]
    except Exception as e:
        logger.error(f"Error fetching companies: {e}")
        return []

@router.post("/companies")
async def create_company(payload: CompanyCreate, user: dict = Depends(require_admin_role)):
    try:
        pool = await get_core_pool()
        await pool.execute("INSERT INTO companies (code, name, address) VALUES ($1, $2, $3)", payload.code, payload.name, payload.address)
        return {"message": "Perusahaan berhasil ditambahkan"}
    except asyncpg.exceptions.UniqueViolationError:
        raise HTTPException(status_code=400, detail="Kode perusahaan sudah digunakan")
    except Exception as e:
        logger.error(f"Error creating company: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.put("/companies/{code}")
async def update_company(code: str, payload: CompanyUpdate, user: dict = Depends(require_admin_role)):
    """
    Update perusahaan (transaksional).
    - Nonaktifkan  -> semua cabang ikut nonaktif.
    - Aktifkan     -> cabang diaktifkan kembali (simetris), sehingga status
      cabang tidak tertinggal 'mati' permanen seperti bug sebelumnya.
    """
    try:
        pool = await get_core_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                exists = await conn.fetchval("SELECT 1 FROM companies WHERE code=$1", code)
                if not exists:
                    raise HTTPException(status_code=404, detail="Perusahaan tidak ditemukan")
                await conn.execute(
                    "UPDATE companies SET name=$1, address=$2, is_active=$3 WHERE code=$4",
                    payload.name, payload.address, payload.is_active, code
                )
                if not payload.is_active:
                    await conn.execute("UPDATE branches SET is_active=false WHERE company_code=$1", code)
                else:
                    await conn.execute("UPDATE branches SET is_active=true WHERE company_code=$1", code)
        return {"message": "Perusahaan berhasil diperbarui"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating company: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.delete("/companies/{code}")
async def delete_company(code: str, user: dict = Depends(require_admin_role)):
    """
    Hapus perusahaan + seluruh cabangnya secara transaksional.
    Menolak penghapusan jika masih ada tenant (koneksi database) yang
    terpasang pada cabang manapun, agar tidak crash dengan FK RESTRICT.
    """
    try:
        pool = await get_core_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                exists = await conn.fetchval("SELECT 1 FROM companies WHERE code=$1", code)
                if not exists:
                    raise HTTPException(status_code=404, detail="Perusahaan tidak ditemukan")
                tenant_count = await conn.fetchval("""
                    SELECT COUNT(*) FROM tenants t
                    JOIN branches b ON t.branch_code = b.code
                    WHERE b.company_code = $1
                """, code)
                if tenant_count and int(tenant_count) > 0:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Tidak dapat menghapus: {tenant_count} konfigurasi database (tenant) masih terhubung. Hapus tenant pada menu Database & Tenant terlebih dahulu."
                    )
                # Bersihkan assignment user->cabang dulu (sudah CASCADE, tapi eksplisit lebih aman)
                await conn.execute("""
                    DELETE FROM user_branches WHERE branches_code IN (
                        SELECT code FROM branches WHERE company_code = $1
                    )
                """, code)
                await conn.execute("DELETE FROM branches WHERE company_code = $1", code)
                await conn.execute("DELETE FROM companies WHERE code = $1", code)
        return {"message": "Perusahaan berhasil dihapus"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting company: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/branches")
async def get_branches(user: dict = Depends(require_admin_role)):
    try:
        pool = await get_core_pool()
        rows = await pool.fetch("SELECT b.code, b.name, b.company_code, b.address, b.is_active FROM branches b")
        return [{"code": r["code"], "name": r["name"], "company_code": r["company_code"], "address": r["address"], "is_active": r["is_active"]} for r in rows]
    except Exception as e:
        logger.error(f"Error fetching branches: {e}")
        return []

@router.post("/branches")
async def create_branch(payload: BranchCreate, user: dict = Depends(require_admin_role)):
    try:
        pool = await get_core_pool()
        await pool.execute("INSERT INTO branches (code, name, company_code, address) VALUES ($1, $2, $3, $4)", payload.code, payload.name, payload.company_code, payload.address)
        return {"message": "Cabang berhasil ditambahkan"}
    except asyncpg.exceptions.UniqueViolationError:
        raise HTTPException(status_code=400, detail="Kode cabang sudah digunakan")
    except Exception as e:
        logger.error(f"Error creating branch: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.put("/branches/{code}")
async def update_branch(code: str, payload: BranchUpdate, user: dict = Depends(require_admin_role)):
    try:
        pool = await get_core_pool()
        await pool.execute("UPDATE branches SET name=$1, address=$2, is_active=$3 WHERE code=$4", payload.name, payload.address, payload.is_active, code)
        return {"message": "Cabang berhasil diperbarui"}
    except Exception as e:
        logger.error(f"Error updating branch: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.delete("/branches/{code}")
async def delete_branch(code: str, user: dict = Depends(require_admin_role)):
    try:
        pool = await get_core_pool()
        tenant_exists = await pool.fetchval("SELECT 1 FROM tenants WHERE branch_code = $1", code)
        if tenant_exists:
            raise HTTPException(
                status_code=400,
                detail="Tidak dapat menghapus: cabang ini masih memiliki konfigurasi database (tenant). Hapus tenant terlebih dahulu."
            )
        await pool.execute("DELETE FROM branches WHERE code=$1", code)
        return {"message": "Cabang berhasil dihapus"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting branch: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/branches-with-tenants")
async def get_branches_with_tenants(user: dict = Depends(require_admin_role)):
    try:
        pool = await get_core_pool()
        rows = await pool.fetch("""
            SELECT 
                b.code, b.name, b.company_code, b.address, b.is_active,
                t.db_host, t.db_port, t.db_name, t.db_username
            FROM branches b
            LEFT JOIN tenants t ON b.code = t.branch_code
        """)
        return [{"code": r["code"], "name": r["name"], "company_code": r["company_code"], "address": r["address"], "is_active": r["is_active"], "db_host": r["db_host"], "db_port": r["db_port"], "db_name": r["db_name"], "db_username": r["db_username"]} for r in rows]
    except Exception as e:
        logger.error(f"Error fetching branches with tenants: {e}")
        return []

# ==========================================
# 2. TENANTS (DATABASE) ENDPOINTS
# ==========================================
@router.get("/tenants")
async def get_tenants(user: dict = Depends(require_admin_role)):
    """
    Daftar semua tenant. Dipakai frontend via api.getTenants().
    Password TIDAK dikirim balik (hanya metadata koneksi).
    """
    try:
        pool = await get_core_pool()
        rows = await pool.fetch("""
            SELECT branch_code, db_host, db_port, db_name, db_username, is_active
            FROM tenants
            ORDER BY branch_code
        """)
        return [
            {
                "branch_code": r["branch_code"],
                "db_host": r["db_host"],
                "db_port": r["db_port"],
                "db_name": r["db_name"],
                "db_username": r["db_username"],
                "is_active": r["is_active"],
            } for r in rows
        ]
    except Exception as e:
        logger.error(f"Error fetching tenants: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/tenants/{branch_code}")
async def get_tenant_by_branch(branch_code: str, user: dict = Depends(require_admin_role)):
    """
    Mengambil detail konfigurasi database untuk satu cabang tertentu.
    Digunakan saat modal edit database terbuka dan saat merender status di tabel.
    """
    try:
        pool = await get_core_pool()
        row = await pool.fetchrow(
            "SELECT db_host, db_port, db_name, db_username FROM tenants WHERE branch_code = $1",
            branch_code
        )
        if not row:
            return None
        return {
            "db_host": row["db_host"],
            "db_port": row["db_port"],
            "db_name": row["db_name"],
            "db_username": row["db_username"]
        }
    except Exception as e:
        logger.error(f"Error fetching tenant for branch {branch_code}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/tenants")
async def create_tenant(payload: TenantCreate, user: dict = Depends(require_admin_role)):
    try:
        pool = await get_core_pool()
        encrypted_pass = encrypt_credential(payload.db_password)
        await pool.execute("""
            INSERT INTO tenants (branch_code, db_host, db_port, db_name, db_username, db_password)
            VALUES ($1, $2, $3, $4, $5, $6)
        """, payload.branch_code, payload.db_host, payload.db_port, payload.db_name, payload.db_username, encrypted_pass)
        return {"message": "Tenant berhasil ditambahkan"}
    except asyncpg.exceptions.UniqueViolationError:
        raise HTTPException(status_code=400, detail="Kode cabang ini sudah memiliki konfigurasi tenant")
    except Exception as e:
        logger.error(f"Error creating tenant: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/tenants/{branch_code}/test-connection")
async def test_tenant_connection(branch_code: str, user: dict = Depends(require_admin_role)):
    try:
        pool = await get_core_pool()
        row = await pool.fetchrow("SELECT db_host, db_port, db_name, db_username, db_password FROM tenants WHERE branch_code = $1", branch_code)
        if not row:
            raise HTTPException(status_code=404, detail="Tenant tidak ditemukan")
        decrypted_pass = decrypt_credential(row["db_password"])
        conn = await asyncpg.connect(
            host=row["db_host"], port=row["db_port"], database=row["db_name"],
            user=row["db_username"], password=decrypted_pass, timeout=5.0
        )
        await conn.close()
        return {"status": "connected", "message": "Koneksi berhasil"}
    except Exception as e:
        logger.error(f"Test connection failed for {branch_code}: {e}")
        return {"status": "disconnected", "message": f"Gagal koneksi: {str(e)}"}

@router.post("/tenants/test-draft")
async def test_tenant_draft_connection(payload: TenantCreate, user: dict = Depends(require_admin_role)):
    """
    Menguji koneksi ke database tenant TANPA menyimpannya ke database.
    Ini digunakan saat admin mengetes konfigurasi sebelum menyimpan (mode Create).
    """
    try:
        conn = await asyncpg.connect(
            host=payload.db_host,
            port=payload.db_port,
            database=payload.db_name,
            user=payload.db_username,
            password=payload.db_password,
            timeout=5.0
        )
        await conn.close()
        return {"status": "connected", "message": "Koneksi berhasil!"}
    except Exception as e:
        logger.error(f"Test draft connection failed: {e}")
        return {"status": "disconnected", "message": f"Gagal koneksi: {str(e)}"}

@router.put("/tenants/{branch_code}")
async def update_tenant(branch_code: str, payload: TenantCreate, user: dict = Depends(require_admin_role)):
    """
    Mengupdate konfigurasi database untuk cabang tertentu.
    Jika password kosong, tidak diupdate.
    """
    try:
        pool = await get_core_pool()
        # Cek apakah tenant sudah ada
        existing = await pool.fetchrow("SELECT 1 FROM tenants WHERE branch_code = $1", branch_code)
        if not existing:
            raise HTTPException(status_code=404, detail="Tenant tidak ditemukan")
        
        # Siapkan password (hanya update jika ada isi)
        if payload.db_password and payload.db_password.strip():
            encrypted_pass = encrypt_credential(payload.db_password)
            await pool.execute("""
                UPDATE tenants 
                SET db_host = $1, db_port = $2, db_name = $3, db_username = $4, db_password = $5
                WHERE branch_code = $6
            """, payload.db_host, payload.db_port, payload.db_name, payload.db_username, encrypted_pass, branch_code)
        else:
            # Update tanpa password
            await pool.execute("""
                UPDATE tenants 
                SET db_host = $1, db_port = $2, db_name = $3, db_username = $4
                WHERE branch_code = $5
            """, payload.db_host, payload.db_port, payload.db_name, payload.db_username, branch_code)
        return {"message": "Tenant berhasil diperbarui"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating tenant for branch {branch_code}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.delete("/tenants/{branch_code}")
async def delete_tenant(branch_code: str, user: dict = Depends(require_admin_role)):
    """
    Menghapus konfigurasi tenant (memutus koneksi database).
    """
    try:
        pool = await get_core_pool()
        await pool.execute("DELETE FROM tenants WHERE branch_code = $1", branch_code)
        return {"message": "Tenant berhasil dihapus"}
    except Exception as e:
        logger.error(f"Error deleting tenant for branch {branch_code}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

# ==========================================
# 3. AI CONFIGS & FETCH MODELS (PERBAIKAN UTAMA)
# ==========================================

# --- Helper untuk memparsing provider dari nama model ---
def get_provider_label(model_id: str, user_provider: str) -> str:
    """Menentukan provider label berdasarkan nama model."""
    first_part = model_id.split('-')[0] if '-' in model_id else model_id
    mapping = {
        "deepseek": "DeepSeek",
        "qwen": "Qwen",
        "mistral": "Mistral",
        "claude": "Claude",
        "gpt": "OpenAI",
        "llama": "Meta Llama",
        "gemini": "Google Gemini",
        "stepfun": "StepFun"
    }
    return mapping.get(first_part.lower(), user_provider)

@router.get("/ai-configs")
async def get_ai_configs(user: dict = Depends(require_admin_role)):
    try:
        pool = await get_core_pool()
        rows = await pool.fetch("""
            SELECT id, scope, target_id, provider, model, temperature, api_type, base_url
            FROM ai_configs
        """)
        return [
            {
                "id": r["id"],
                "scope": r["scope"],
                "target_id": r["target_id"],
                "provider": r["provider"],
                "model": r["model"],
                "temperature": r["temperature"],
                "api_type": r["api_type"],
                "base_url": r["base_url"]
            } for r in rows
        ]
    except Exception as e:
        logger.error(f"Error fetching AI configs: {e}")
        return []

@router.post("/ai-configs")
async def create_ai_config(payload: AIConfigCreate, user: dict = Depends(require_admin_role)):
    try:
        pool = await get_core_pool()
        encrypted_key = encrypt_credential(payload.api_key)
        target_id_val = payload.target_id if payload.target_id else None
        await pool.execute("""
            INSERT INTO ai_configs (scope, target_id, provider, model, api_key, temperature, api_type, base_url)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """, payload.scope, target_id_val, payload.provider, payload.model, encrypted_key, payload.temperature, payload.api_type, payload.base_url)
        return {"message": "Konfigurasi AI berhasil disimpan"}
    except Exception as e:
        logger.error(f"Error creating AI config: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.put("/ai-configs/{config_id}")
async def update_ai_config(config_id: int, payload: AIConfigUpdate, user: dict = Depends(require_admin_role)):
    try:
        pool = await get_core_pool()
        target_id_val = payload.target_id if payload.target_id else None
        
        if payload.api_key and payload.api_key.strip():
            encrypted_key = encrypt_credential(payload.api_key)
            await pool.execute("""
                UPDATE ai_configs 
                SET scope = $1, target_id = $2, provider = $3, model = $4, 
                    temperature = $5, api_type = $6, base_url = $7, api_key = $8
                WHERE id = $9
            """, payload.scope, target_id_val, payload.provider, payload.model, 
                payload.temperature, payload.api_type, payload.base_url, encrypted_key, config_id)
        else:
            # Update tanpa API Key
            await pool.execute("""
                UPDATE ai_configs 
                SET scope = $1, target_id = $2, provider = $3, model = $4, 
                    temperature = $5, api_type = $6, base_url = $7
                WHERE id = $8
            """, payload.scope, target_id_val, payload.provider, payload.model, 
                payload.temperature, payload.api_type, payload.base_url, config_id)
        return {"message": "Konfigurasi berhasil diperbarui"}
    except HTTPException:
        raise
    except asyncpg.exceptions.UniqueViolationError:
        raise HTTPException(status_code=400, detail="Konfigurasi dengan scope & target ini sudah ada")
    except Exception as e:
        logger.error(f"Error updating AI config {config_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.delete("/ai-configs/{config_id}")
async def delete_ai_config(config_id: int, user: dict = Depends(require_admin_role)):
    try:
        pool = await get_core_pool()
        await pool.execute("DELETE FROM ai_configs WHERE id = $1", config_id)
        return {"message": "Konfigurasi berhasil dihapus"}
    except Exception as e:
        logger.error(f"Error deleting AI config: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/ai-configs/{config_id}/test")
async def test_ai_config(config_id: int, user: dict = Depends(require_admin_role)):
    pool = await get_core_pool()
    row = await pool.fetchrow("SELECT api_type, base_url, api_key FROM ai_configs WHERE id = $1", config_id)
    if not row:
        raise HTTPException(status_code=404, detail="Config tidak ditemukan")
    
    api_type = row["api_type"]
    base_url = row["base_url"]
    api_key = row["api_key"]
    decrypted_key = decrypt_credential(api_key)
    
    url = ""
    headers = {}
    if api_type == "openai":
        url = f"{base_url}/models"
        headers = {"Authorization": f"Bearer {decrypted_key}"}
    elif api_type == "anthropic":
        return {"status": "connected", "message": "Anthropic tidak mendukung test otomatis"}
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                return {"status": "connected", "message": "Koneksi berhasil"}
            else:
                return {"status": "disconnected", "message": f"Gagal: {resp.status_code}"}
    except Exception as e:
        return {"status": "disconnected", "message": str(e)}

@router.post("/ai-providers/models")
async def fetch_models_from_provider(payload: FetchModelsRequest, user: dict = Depends(require_admin_role)):
    pool = await get_core_pool()
    final_api_key = payload.api_key
    if not final_api_key and payload.config_id:
        row = await pool.fetchrow("SELECT api_key FROM ai_configs WHERE id = $1", payload.config_id)
        if row:
            final_api_key = decrypt_credential(row["api_key"])
        else:
            raise HTTPException(status_code=404, detail="Konfigurasi tidak ditemukan")
    elif not final_api_key and not payload.config_id:
        raise HTTPException(status_code=400, detail="API Key wajib diisi untuk mode tambah baru")

    headers = {}
    url = ""
    if payload.api_type == "openai":
        headers = {"Authorization": f"Bearer {final_api_key}"}
        base = payload.base_url if payload.base_url else "https://api.openai.com/v1"
        url = f"{base}/models"
    elif payload.api_type == "anthropic":
        return {"provider": payload.provider, "models": []}
    else:
        raise HTTPException(status_code=400, detail="api_type tidak dikenali")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=f"Gagal fetch dari provider: {resp.text}")
            data = resp.json()
            raw_models = [item["id"] for item in data.get("data", [])]
            
            formatted_models = [
                {
                    "id": m,
                    "label": m.replace("-", " ").title(),
                    "provider": get_provider_label(m, payload.provider) # <-- PARSING PROVIDER DI SINI
                }
                for m in raw_models
            ]
            return {"provider": payload.provider, "models": formatted_models}
    except Exception as e:
        logger.error(f"Error fetching models: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/ai-configs/test-draft")
async def test_ai_config_draft(payload: AIConfigTestDraft, user: dict = Depends(require_admin_role)):
    pool = await get_core_pool()
    final_api_key = payload.api_key
    if not final_api_key and payload.config_id:
        row = await pool.fetchrow("SELECT api_key FROM ai_configs WHERE id = $1", payload.config_id)
        if row:
            final_api_key = decrypt_credential(row["api_key"])
        else:
            raise HTTPException(status_code=404, detail="Konfigurasi tidak ditemukan")
    elif not final_api_key and not payload.config_id:
        raise HTTPException(status_code=400, detail="API Key wajib diisi untuk mode tambah baru")

    url = ""
    headers = {}
    try:
        if payload.api_type == "openai":
            url = f"{payload.base_url}/models"
            headers = {"Authorization": f"Bearer {final_api_key}"}
        elif payload.api_type == "anthropic":
            return {"status": "connected", "message": "Koneksi diasumsikan berhasil (manual model)."}
        else:
            return {"status": "disconnected", "message": "Tipe API tidak didukung"}

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                return {"status": "connected", "message": "Koneksi berhasil!"}
            else:
                return {"status": "disconnected", "message": f"Gagal: {resp.status_code}"}
    except Exception as e:
        return {"status": "disconnected", "message": f"Error: {str(e)}"}