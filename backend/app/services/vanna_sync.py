"""Sinkronisasi Knowledge Base global dari Vanna API (F3).

Data dari Vanna (ChromaDB vector store: ~2400 dokumen teks deskripsi tabel
+ beberapa contoh question→SQL) di-fetch via REST API lalu di-upsert ke
tabel core `global_knowledge_base`.

Proses ini on-demand (dipicu admin via endpoint, bukan otomatis) dan
idempoten: menjalankan berkali-kali aman.
"""
import json
import logging
from urllib.parse import urljoin

import httpx

logger = logging.getLogger(__name__)

# Batch size saat fetch item dari Vanna API
_PAGE_SIZE = 100


class VannaSyncError(Exception):
    """Gagal sync dari Vanna API (login/fetch/parse)."""


async def _login_vanna(client: httpx.AsyncClient, base_url: str,
                       username: str, password: str) -> None:
    """Login ke Vanna API, simpan session cookie di client."""
    login_url = urljoin(base_url, "/login")
    data = {"username": username, "password": password}
    try:
        response = await client.post(login_url, data=data, timeout=10.0, follow_redirects=False)
        # Login form FastAPI/Starlette mengembalikan 303 See Other saat sukses (set cookie)
        if response.status_code not in (200, 302, 303):
            raise VannaSyncError(f"Login failed with status {response.status_code}")
    except httpx.HTTPError as e:
        logger.error(f"Gagal login ke Vanna API: {e}")
        raise VannaSyncError(f"Login failed: {e}")


async def _fetch_semua_items(client: httpx.AsyncClient, 
                             base_url: str) -> list[dict]:
    """Fetch semua KB items dari Vanna API (paginated)."""
    items_url = urljoin(base_url, "/api/kb/items")
    offset = 0
    all_items = []
    
    while True:
        try:
            params = {"limit": _PAGE_SIZE, "offset": offset}
            response = await client.get(items_url, params=params, timeout=30.0)
            response.raise_for_status()
            data = response.json()
            
            items = data.get("items", [])
            all_items.extend(items)
            
            if len(items) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE
        except httpx.HTTPError as e:
            logger.error(f"Gagal fetch items dari Vanna API: {e}")
            raise VannaSyncError(f"Fetch failed at offset {offset}: {e}")
        except ValueError as e:
            logger.error(f"Response bukan JSON valid: {e}")
            raise VannaSyncError(f"Invalid JSON response: {e}")

    return all_items


async def sync_dari_vanna(core_pool, vanna_url: str, 
                          username: str, password: str) -> dict:
    """Sync KB global dari Vanna API ke tabel global_knowledge_base.
    
    Returns: {total_fetched, inserted, updated, deleted, errors}
    """
    stats = {
        "total_fetched": 0,
        "inserted": 0,
        "updated": 0,
        "deleted": 0,
        "errors": 0
    }
    
    # 1. Login to Vanna API
    # 2. Fetch all items
    async with httpx.AsyncClient() as client:
        await _login_vanna(client, vanna_url, username, password)
        items = await _fetch_semua_items(client, vanna_url)
    
    stats["total_fetched"] = len(items)
    
    if not items:
        return stats
        
    external_ids_fetched = []
    
    async with core_pool.acquire() as conn:
        async with conn.transaction():
            # 3. For each item: upsert to global_knowledge_base
            for item in items:
                try:
                    external_id = item.get("id")
                    if not external_id:
                        logger.warning("Item dari Vanna tidak memiliki id")
                        stats["errors"] += 1
                        continue
                        
                    external_ids_fetched.append(str(external_id))
                    kind = item.get("kind")
                    content = item.get("content", "")
                    question = item.get("question") if kind == "example" else None
                    sql_example = item.get("sql") if kind == "example" else None
                    
                    metadata = {
                        "tool_name": item.get("tool_name"),
                        "timestamp": item.get("timestamp")
                    }
                    
                    upsert_query = """
                        INSERT INTO global_knowledge_base 
                            (external_id, kind, content, question, sql_example, metadata, updated_at)
                        VALUES 
                            ($1, $2, $3, $4, $5, $6, CURRENT_TIMESTAMP)
                        ON CONFLICT (external_id) DO UPDATE SET
                            kind = EXCLUDED.kind,
                            content = EXCLUDED.content,
                            question = EXCLUDED.question,
                            sql_example = EXCLUDED.sql_example,
                            metadata = EXCLUDED.metadata,
                            updated_at = CURRENT_TIMESTAMP
                        RETURNING (xmax = 0) AS is_inserted;
                    """
                    
                    result = await conn.fetchrow(
                        upsert_query,
                        str(external_id),
                        kind,
                        content,
                        question,
                        sql_example,
                        json.dumps(metadata)
                    )
                    
                    if result and result["is_inserted"]:
                        stats["inserted"] += 1
                    else:
                        stats["updated"] += 1
                        
                except Exception as e:
                    logger.error(f"Error upsert item {item.get('id')}: {e}")
                    stats["errors"] += 1
            
            # 4. Delete orphans (items in DB that no longer exist in Vanna)
            if external_ids_fetched:
                delete_query = """
                    DELETE FROM global_knowledge_base
                    WHERE external_id != ALL($1::text[])
                    RETURNING id;
                """
                deleted_rows = await conn.fetch(delete_query, external_ids_fetched)
                stats["deleted"] = len(deleted_rows)
                
    return stats
