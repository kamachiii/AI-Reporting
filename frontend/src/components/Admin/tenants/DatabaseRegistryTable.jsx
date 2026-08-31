import { useEffect, useMemo } from 'react';
import { motion } from 'framer-motion';
import { CheckCircle, XCircle, Loader2, Wifi, Pencil, Trash2 } from 'lucide-react';
import PaginationBar from '../common/PaginationBar';
import EmptyState from '../common/EmptyState';

const PAGE_SIZE = 10; // sinkron dengan TenantConnectionsTable (ukuran halaman tabel admin)

/**
 * Tabel registry database (sub-tab "Database" di TenantsTab).
 * Presentational: menerima data + callback; filter, pagination, dan
 * render murni ada di sini — CRUD tetap di TenantsTab.
 */
export default function DatabaseRegistryTable({
  connections,
  tenants,
  debouncedSearch,
  dbPage,
  setDbPage,
  dbStatus,
  testingId,
  processingKey,
  onTest,
  onEdit,
  onDelete,
}) {
  const filteredDbs = useMemo(() => {
    if (!debouncedSearch) return connections;
    const q = debouncedSearch.toLowerCase();
    return connections.filter(c =>
      c.name.toLowerCase().includes(q) ||
      (c.db_host || '').toLowerCase().includes(q) ||
      (c.db_name || '').toLowerCase().includes(q));
  }, [connections, debouncedSearch]);

  const dbTotalPages = Math.max(1, Math.ceil(filteredDbs.length / PAGE_SIZE));
  useEffect(() => { if (dbPage > dbTotalPages) setDbPage(dbTotalPages); }, [dbPage, dbTotalPages]);
  const paginatedDbs = useMemo(
    () => filteredDbs.slice((dbPage - 1) * PAGE_SIZE, dbPage * PAGE_SIZE),
    [filteredDbs, dbPage]);

  const usedByMap = useMemo(() => {
    const m = {};
    tenants.forEach(t => { m[t.db_connection_id] = (m[t.db_connection_id] || 0) + 1; });
    return m;
  }, [tenants]);

  if (filteredDbs.length === 0) {
    return (
      <EmptyState variant="plug"
        title="Belum ada database terdaftar"
        description='Klik "Daftarkan Database" di kanan atas untuk mulai.' />
    );
  }

  return (
    <div className="bg-white rounded-xl border border-hairline overflow-hidden shadow-sm">
      <div className="overflow-auto max-h-[420px]">
        <table className="w-full text-left">
          <thead className="bg-surface-soft text-sm text-muted sticky top-0 z-10">
            <tr>
              <th className="p-3">Nama</th>
              <th className="p-3">Host</th>
              <th className="p-3">Database</th>
              <th className="p-3 w-24 text-center">Dipakai</th>
              <th className="p-3 w-20">Status</th>
              <th className="p-3 w-28">Koneksi</th>
              <th className="p-3 w-0 text-center">Aksi</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-hairline">
            {paginatedDbs.map((c, idx) => (
              <motion.tr key={c.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }}
                transition={{ delay: idx * 0.03 }} className="hover:bg-surface-soft/50">
                <td className="p-3 text-sm font-medium">{c.name}</td>
                <td className="p-3 text-sm text-muted">{c.db_host}:{c.db_port}</td>
                <td className="p-3 text-sm text-body">{c.db_name}</td>
                <td className="p-3 text-center text-sm text-muted">
                  {(usedByMap[c.id] ?? c.used_by ?? 0)} cabang
                </td>
                <td className="p-3">
                  {c.is_active ? (
                    <span className="inline-flex items-center gap-1.5 text-success text-xs font-medium">
                      <span className="w-1.5 h-1.5 rounded-full bg-success" /> Aktif
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 text-error text-xs font-medium">
                      <span className="w-1.5 h-1.5 rounded-full bg-error opacity-70" /> Nonaktif
                    </span>
                  )}
                </td>
                {(() => {
                  const st = dbStatus[String(c.id)];
                  return (
                    <td className="p-3" title={st?.message || ''}>
                      {!st || st.status === 'checking' ? (
                        <span className="inline-flex items-center text-muted text-xs">
                          <Loader2 size={12} className="mr-1.5 animate-spin" /> Menguji…
                        </span>
                      ) : st.status === 'connected' ? (
                        <span className="inline-flex items-center gap-1.5 text-success text-xs font-medium">
                          <CheckCircle size={13} /> Connected
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1.5 text-error text-xs font-medium">
                          <XCircle size={13} /> Disconnected
                        </span>
                      )}
                    </td>
                  );
                })()}
                <td className="p-3">
                  <div className="flex justify-end gap-0.5">
                    <button onClick={() => onTest(c)} disabled={testingId === c.id}
                      title="Test Koneksi" aria-label={`Test koneksi ${c.name}`}
                      className="p-1.5 text-muted hover:text-primary hover:bg-surface-soft rounded-md disabled:opacity-50">
                      {testingId === c.id ? <Loader2 size={15} className="animate-spin" /> : <Wifi size={15} />}
                    </button>
                    <button onClick={() => onEdit(c)}
                      title="Edit" aria-label={`Edit ${c.name}`}
                      className="p-1.5 text-muted hover:text-ink hover:bg-surface-soft rounded-md">
                      <Pencil size={15} />
                    </button>
                    <button onClick={() => onDelete(c)} disabled={processingKey === `db-${c.id}`}
                      title="Hapus" aria-label={`Hapus ${c.name}`}
                      className="p-1.5 text-muted hover:text-error hover:bg-error/5 rounded-md disabled:opacity-50">
                      {processingKey === `db-${c.id}` ? <Loader2 size={15} className="animate-spin" /> : <Trash2 size={15} />}
                    </button>
                  </div>
                </td>
              </motion.tr>
            ))}
          </tbody>
        </table>
      </div>
      <PaginationBar page={dbPage} totalPages={dbTotalPages} onChange={setDbPage}
        totalItems={filteredDbs.length} pageSize={PAGE_SIZE} />
    </div>
  );
}