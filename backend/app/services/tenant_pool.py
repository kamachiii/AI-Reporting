"""F2.4 — Tenant Pool Manager: interface TUNGGAL koneksi ke DB tenant.

Desain v1 §5: pool asyncpg per `db_connection_id`, LRU maks 8 tenant, BUKAN
connect-per-query (membuat koneksi baru per query menghabiskan waktu ~100 ms
dan menghantam DB tenant saat trafik naik).

Aturan pemakaian (wajib):
- Semua koneksi ke tenant DB HARUS lewat `TenantPoolManager.get_pool()` —
  tidak ada asyncpg.connect/create_pool langsung ke tenant di kode lain.
- Kredensial di `db_connections.db_password` tersimpan terenkripsi Fernet
  (dienkripsi saat onboarding tenant oleh router admin) — didekripsi di sini
  SEBELUM dibuatkan pool, tidak pernah di-log.
- Pool dibuat dengan min_size=0 agar tidak menahan koneksi idle ke DB tenant
  yang mungkin hanya sesekali dipakai; max_size kecil (2) karena pemakaian
  per-cabang relatif kecil (dev/PKL single-instance).
- Siklus hidup: LRU evict saat jumlah pool > `max_pools`; pool yang idle
  melebihi `idle_timeout_seconds` ditutup lazily saat get_pool berikutnya
  (tanpa background task — cukup untuk single-instance dev/PKL).
- Rotasi kredensial tenant perlu `close_all()` (cache dikunci per id, bukan
  per isi kredensial — keputusan sederhana v1).

Pengujian: `connector` di-inject sehingga test tidak butuh DB nyata
(lihat tests/test_tenant_pool.py).
"""
import asyncio
import logging
import time
from collections import OrderedDict

import asyncpg

from app.core.security import decrypt_credential

logger = logging.getLogger(__name__)

# Batas default (v1 §5): LRU maks 8 tenant, pool kecil per tenant.
DEFAULT_MAX_POOLS = 8
DEFAULT_POOL_MAX_SIZE = 2
DEFAULT_IDLE_TIMEOUT_SECONDS = 600.0


class TenantPoolError(Exception):
    """Kegagalan menyediakan pool tenant (kredensial/is_active/dekripsi)."""


async def _buat_pool_asyncpg(*, host, port, database, user, password, max_size):
    """Connector default — satu-satunya tempat create_pool ke tenant DB."""
    return await asyncpg.create_pool(
        host=host, port=port, database=database, user=user, password=password,
        min_size=0, max_size=max_size)


class TenantPoolManager:
    """Cache pool asyncpg per db_connection_id dengan kebijakan LRU."""

    def __init__(self, *, max_pools: int = DEFAULT_MAX_POOLS,
                 pool_max_size: int = DEFAULT_POOL_MAX_SIZE,
                 idle_timeout_seconds: float = DEFAULT_IDLE_TIMEOUT_SECONDS,
                 connector=None):
        if max_pools < 1:
            raise ValueError("max_pools minimal 1")
        self._max_pools = max_pools
        self._pool_max_size = pool_max_size
        self._idle_timeout = idle_timeout_seconds
        self._connector = connector or _buat_pool_asyncpg
        # OrderedDict: urutan = LRU (paling akhir = paling baru dipakai)
        self._pools: OrderedDict[int, dict] = OrderedDict()
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # API utama
    # ------------------------------------------------------------------
    async def get_pool(self, db_conn_row) -> asyncpg.Pool:
        """Ambil pool untuk satu baris `db_connections` (buat bila belum ada).

        Args:
            db_conn_row: baris/dict berisi minimal
                {db_host, db_port, db_name, db_username, db_password} plus
                kunci id: 'id' (baris db_connections) ATAU
                'db_connection_id' (baris join tenants+db_connections ala
                chat_pipeline) — keduanya diterima karena ini interface
                tunggal pemanggil lintas modul. Boleh asyncpg Record.

        Returns:
            Pool asyncpg (atau apapun yang dikembalikan connector ter-inject).

        Raises:
            TenantPoolError: baris tidak lengkap, koneksi/tidak aktif,
                kredensial gagal didekripsi, atau connector gagal.
        """
        row = dict(db_conn_row)
        cid = row.get("id", row.get("db_connection_id"))
        if cid is None:
            raise TenantPoolError(
                "db_connection tanpa 'id'/'db_connection_id' — tidak bisa di-cache")
        if row.get("is_active", True) is False:
            raise TenantPoolError(f"db_connection {cid} tidak aktif")

        async with self._lock:
            entri = self._pools.get(cid)
            if entri is not None:
                # Cache hit: perbarui posisi LRU + waktu pakai.
                entri["terakhir"] = time.monotonic()
                self._pools.move_to_end(cid)
                await self._tutup_idle_lama()
                return entri["pool"]

            pool = await self._buat_pool(row, cid)
            self._pools[cid] = {"pool": pool, "terakhir": time.monotonic()}
            logger.info("tenant_pool: pool dibuat untuk db_connection %s (total %d)",
                        cid, len(self._pools))
            await self._evict_lru()
            await self._tutup_idle_lama()
            return pool

    async def close_all(self) -> None:
        """Tutup SEMUA pool (dipanggil saat shutdown app / rotasi kredensial)."""
        async with self._lock:
            for cid, entri in self._pools.items():
                try:
                    await entri["pool"].close()
                except Exception as e:  # jangan gagalkan sisa penutupan
                    logger.warning("tenant_pool: gagal menutup pool %s: %s", cid, e)
            self._pools.clear()
            logger.info("tenant_pool: semua pool ditutup")

    @property
    def jumlah_pool(self) -> int:
        """Jumlah pool ter-cache (untuk metrik/test)."""
        return len(self._pools)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    async def _buat_pool(self, row: dict, cid) -> None:
        password = self._dekripsi_password(row)
        try:
            return await self._connector(
                host=row["db_host"], port=int(row["db_port"]),
                database=row["db_name"], user=row["db_username"],
                password=password, max_size=self._pool_max_size)
        except KeyError as e:
            raise TenantPoolError(f"db_connection {cid} tidak lengkap: kolom {e} hilang") from e
        except Exception as e:
            raise TenantPoolError(
                f"gagal membuat pool untuk db_connection {cid}: {e}") from e

    @staticmethod
    def _dekripsi_password(row: dict) -> str:
        """Kredensial db_connections tersimpan Fernet-encrypted (lihat
        encrypt_credential saat onboarding). Kegagalan dekripsi = error jelas,
        bukan fallback diam-diam (jangan pernah mencoba password mentah)."""
        tersimpan = row.get("db_password")
        if not tersimpan:
            raise TenantPoolError(
                f"db_connection {row.get('id')} tidak punya db_password")
        try:
            return decrypt_credential(tersimpan)
        except Exception as e:
            raise TenantPoolError(
                "kredensial tidak dapat didekripsi (periksa FERNET_KEY)") from e

    async def _evict_lru(self) -> None:
        """Buang pool paling lama tidak dipakai sampai jumlah <= max_pools."""
        while len(self._pools) > self._max_pools:
            cid_lama, entri = self._pools.popitem(last=False)
            logger.info("tenant_pool: LRU evict db_connection %s", cid_lama)
            try:
                await entri["pool"].close()
            except Exception as e:
                logger.warning("tenant_pool: gagal menutup pool %s (evict): %s",
                               cid_lama, e)

    async def _tutup_idle_lama(self) -> None:
        """Tutup pool yang melebihi idle timeout (lazy sweep, tanpa timer)."""
        now = time.monotonic()
        for cid in [cid for cid, e in self._pools.items()
                    if now - e["terakhir"] > self._idle_timeout]:
            entri = self._pools.pop(cid)
            logger.info("tenant_pool: idle timeout, tutup db_connection %s", cid)
            try:
                await entri["pool"].close()
            except Exception as e:
                logger.warning("tenant_pool: gagal menutup pool %s (idle): %s", cid, e)


# ----------------------------------------------------------------------
# Singleton module-level (pola get_core_pool di app.core.database) —
# interface tunggal yang dipakai seluruh backend untuk koneksi tenant.
# ----------------------------------------------------------------------
_tenant_pool_manager: TenantPoolManager | None = None


def get_tenant_pool_manager() -> TenantPoolManager:
    global _tenant_pool_manager
    if _tenant_pool_manager is None:
        _tenant_pool_manager = TenantPoolManager()
    return _tenant_pool_manager
