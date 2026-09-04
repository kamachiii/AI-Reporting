"""Vanna pgvector Engine: RAG Semantik Murni dengan PostgreSQL pgvector.

Mendukung:
1. Dual-Mode Embedding:
   - Lokal: all-MiniLM-L6-v2 (384 dimensi, offline, gratis)
   - Cloud API: OpenAI / Gemini Compatible Embedding via HTTP
2. Penyimpanan Vektor Terpadu:
   - Tabel tenant_vector_kb di database core PostgreSQL (port 5433).
   - Isolasi branch_code + entri GLOBAL (bebas kebocoran skema antar-cabang).
3. Instant Training (Few-Shot SQL Injection):
   - Menyimpan pasangan pertanyaan -> SQL ke vektor agar AI belajar seketika.
"""
import asyncio
import hashlib
import json
import logging
import os
import re
import time
from typing import Optional

import httpx

from app.services.automotive_thesaurus import (
    ambil_semua_aturan_thesaurus,
    deteksi_konteks_domain,
    susun_instruksi_domain,
)

logger = logging.getLogger(__name__)

# Singleton untuk model lokal agar tidak reload setiap query
_LOCAL_MODEL = None
_MODEL_LOCK = asyncio.Lock()


def _get_local_model():
    global _LOCAL_MODEL
    if _LOCAL_MODEL is None:
        from sentence_transformers import SentenceTransformer
        logger.info("Memuat model embedding lokal all-MiniLM-L6-v2 ke memori...")
        _LOCAL_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
    return _LOCAL_MODEL


async def hitung_embedding(
    text: str,
    provider: str = "local",
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model_name: Optional[str] = None
) -> list[float]:
    """Hitung vektor embedding dari teks menggunakan mode Lokal atau Cloud API."""
    if provider == "api" and api_key:
        # Panggilan Cloud API (OpenAI-compatible)
        url = (base_url or "https://api.openai.com/v1").rstrip("/") + "/embeddings"
        model = model_name or "text-embedding-3-small"
        headers = {"Authorization": f"Bearer {api_key}"}
        payload = {"input": text, "model": model}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, headers=headers, timeout=15.0)
            resp.raise_for_status()
            data = resp.json()
            return data["data"][0]["embedding"]
    else:
        # Mode Lokal all-MiniLM-L6-v2 (dijalankan di thread terpisah agar non-blocking)
        def _encode():
            model = _get_local_model()
            vec = model.encode(text)
            return vec.tolist()

        return await asyncio.to_thread(_encode)


async def simpan_vektor_item(
    core_pool,
    branch_code: str,
    item_type: str,
    content: str,
    embedding: list[float],
    metadata: Optional[dict] = None
) -> int:
    """Simpan atau perbarui entri vektor ke tenant_vector_kb."""
    meta_json = json.dumps(metadata or {})
    vec_str = "[" + ",".join(f"{x:.6f}" for x in embedding) + "]"
    
    query = """
        INSERT INTO tenant_vector_kb (branch_code, item_type, content, embedding, metadata, updated_at)
        VALUES ($1, $2, $3, $4::vector, $5::jsonb, CURRENT_TIMESTAMP)
        ON CONFLICT (branch_code, item_type, md5(content))
        DO UPDATE SET 
            embedding = EXCLUDED.embedding,
            metadata = EXCLUDED.metadata,
            updated_at = CURRENT_TIMESTAMP
        RETURNING id;
    """
    row = await core_pool.fetchrow(query, branch_code, item_type, content, vec_str, meta_json)
    return row["id"] if row else 0


async def cari_konteks_pgvector(
    core_pool,
    branch_code: str,
    question: str,
    limit: int = 8,
    embedding_provider: str = "local",
    api_key: Optional[str] = None
) -> tuple[str, list[str]]:
    """Cari tabel, contoh SQL, dan aturan bisnis domain relevan menggunakan semantic search pgvector."""
    # 0. Deteksi aturan domain otomotif & tabel utama terkait
    matched_rules = deteksi_konteks_domain(question)
    domain_instructions = susun_instruksi_domain(matched_rules)
    tables_found = []
    for r in matched_rules:
        for t in r.get("primary_tables", []):
            if t not in tables_found:
                tables_found.append(t)

    # 1. Hitung vektor pertanyaan
    query_vec = await hitung_embedding(question, provider=embedding_provider, api_key=api_key)
    vec_str = "[" + ",".join(f"{x:.6f}" for x in query_vec) + "]"

    # 2. Query Cosine Similarity di PostgreSQL pgvector
    search_sql = """
        SELECT content, item_type, metadata,
               1 - (embedding <=> $1::vector) AS similarity
        FROM tenant_vector_kb
        WHERE (branch_code = $2 OR branch_code = 'GLOBAL')
        ORDER BY embedding <=> $1::vector ASC
        LIMIT $3;
    """
    rows = await core_pool.fetch(search_sql, vec_str, branch_code, limit)

    contexts = []

    for r in rows:
        c = r.get("content", "") if hasattr(r, "get") else (r["content"] if "content" in r else "")
        if c:
            contexts.append(c)
            # Ekstrak nama tabel fisik
            m = re.search(r"Table\s+([a-zA-Z0-9_]+)", c, re.IGNORECASE)
            if m:
                tbl = m.group(1)
                if tbl not in tables_found:
                    tables_found.append(tbl)

    # Jika tabel DDL belum pernah di-sync ke tenant_vector_kb, fallback ke teks global_knowledge_base
    if not contexts:
        fb_rows = await core_pool.fetch(
            "SELECT content FROM global_knowledge_base "
            "WHERE content ILIKE '%penjualan%' OR content ILIKE '%pembelian%' "
            "LIMIT 5"
        )
        for r in fb_rows:
            c = r.get("content", "") if hasattr(r, "get") else (r["content"] if "content" in r else "")
            if c:
                contexts.append(c)

    # Ambil 2 contoh SQL terlatih paling relevan jika ada
    ex_sql = """
        SELECT content, metadata
        FROM tenant_vector_kb
        WHERE (branch_code = $1 OR branch_code = 'GLOBAL')
          AND item_type = 'sql_example'
        ORDER BY embedding <=> $2::vector ASC
        LIMIT 2;
    """
    ex_rows = await core_pool.fetch(ex_sql, branch_code, vec_str)
    for ex in ex_rows:
        raw_meta = ex.get("metadata") if hasattr(ex, "get") else (ex["metadata"] if "metadata" in ex else None)
        meta = raw_meta if isinstance(raw_meta, dict) else json.loads(raw_meta or "{}")
        q = meta.get("question", "") if isinstance(meta, dict) else ""
        sql_content = ex.get("content", "") if hasattr(ex, "get") else (ex["content"] if "content" in ex else "")
        contexts.append(f"Example question: {q}\nExample SQL: {sql_content}")

    # Susun konteks akhir: panduan domain bisnis otomotif di awal, diikuti oleh DDL & contoh SQL
    all_contexts = []
    if domain_instructions:
        all_contexts.append(domain_instructions)
    all_contexts.extend(contexts)

    return "\n\n".join(all_contexts), tables_found


async def latih_pertanyaan_sql(
    core_pool,
    branch_code: str,
    question: str,
    sql: str,
    embedding_provider: str = "local",
    api_key: Optional[str] = None
) -> dict:
    """Latih AI seketika (Instant Training) dengan menyimpan contoh kueri ke pgvector."""
    # Vektor dihitung dari gabungan pertanyaan dan penjelasan SQL
    text_to_embed = f"Question: {question.strip()}\nSQL: {sql.strip()}"
    vec = await hitung_embedding(text_to_embed, provider=embedding_provider, api_key=api_key)
    
    item_id = await simpan_vektor_item(
        core_pool,
        branch_code=branch_code,
        item_type="sql_example",
        content=sql.strip(),
        embedding=vec,
        metadata={"question": question.strip(), "trained_at": time.time()}
    )
    return {
        "status": "success",
        "id": item_id,
        "branch_code": branch_code,
        "question": question,
        "sql": sql
    }


async def sync_global_kb_ke_pgvector(core_pool, batch_size: int = 64) -> dict:
    """Migrasi/sinkronisasi isi tabel global_knowledge_base ke tenant_vector_kb (batch)."""
    # Ambil item yang belum ada di tenant_vector_kb
    rows = await core_pool.fetch("""
        SELECT g.id, g.content, g.kind, g.question, g.sql_example
        FROM global_knowledge_base g
        LEFT JOIN tenant_vector_kb t 
          ON t.branch_code = 'GLOBAL' 
         AND t.item_type = CASE WHEN g.kind = 'example' THEN 'sql_example' ELSE 'ddl' END
         AND md5(t.content) = md5(COALESCE(g.sql_example, g.content))
        WHERE t.id IS NULL
        ORDER BY g.id ASC
    """)
    
    total = len(rows)
    if total == 0:
        return {"total": 0, "processed": 0, "message": "Semua data global sudah tersinkronisasi"}

    logger.info("Memulai sinkronisasi %d item global KB ke pgvector...", total)
    model = _get_local_model()
    processed = 0

    for i in range(0, total, batch_size):
        batch = rows[i:i+batch_size]
        texts_to_embed = []
        payloads = []

        for r in batch:
            if r["kind"] == "example" and r["sql_example"]:
                item_type = "sql_example"
                content = r["sql_example"].strip()
                embed_text = f"Question: {r['question']}\nSQL: {content}"
                metadata = {"question": r["question"]}
            else:
                item_type = "ddl"
                content = r["content"].strip()
                embed_text = content
                metadata = {"kind": r["kind"]}

            texts_to_embed.append(embed_text)
            payloads.append((item_type, content, metadata))

        # Encode batch
        vecs = await asyncio.to_thread(lambda: model.encode(texts_to_embed, batch_size=batch_size).tolist())

        # Simpan batch ke database
        for (item_type, content, meta), vec in zip(payloads, vecs):
            await simpan_vektor_item(
                core_pool,
                branch_code="GLOBAL",
                item_type=item_type,
                content=content,
                embedding=vec,
                metadata=meta
            )
            processed += 1

        logger.info("Progress sinkronisasi pgvector: %d / %d...", processed, total)

    return {"total": total, "processed": processed, "status": "completed"}


async def injeksi_thesaurus_ke_pgvector(core_pool, embedding_provider: str = "local") -> int:
    """Vektorisasi seluruh aturan kamus semantik domain otomotif ke tenant_vector_kb."""
    entries = ambil_semua_aturan_thesaurus()
    count = 0
    for entry in entries:
        vec = await hitung_embedding(entry["content"], provider=embedding_provider)
        await simpan_vektor_item(
            core_pool,
            branch_code="GLOBAL",
            item_type="domain_thesaurus",
            content=entry["content"],
            embedding=vec,
            metadata={"category": entry["category"], "title": entry["title"], "tables": entry["tables"]}
        )
        count += 1
    logger.info("Berhasil menginjeksi %d aturan domain thesaurus ke pgvector (GLOBAL)", count)
    return count

