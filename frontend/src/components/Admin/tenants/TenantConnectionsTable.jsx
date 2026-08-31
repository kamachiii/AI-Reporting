import { useEffect, useMemo } from 'react';
import { motion } from 'framer-motion';
import { CheckCircle, XCircle, Loader2, RefreshCw, Trash2 } from 'lucide-react';
import PaginationBar from '../common/PaginationBar';
import EmptyState from '../common/EmptyState';

const PAGE_SIZE = 10; // sinkron dengan DatabaseRegistryTable (ukuran halaman tabel admin)

/**
 * Tabel relasi cabang ↔ database (sub-tab "Koneksi" di TenantsTab).
 * Presentational: menerima data + callback; pagination & render murni di sini —
 * aksi (refresh skema, putus koneksi) tetap di TenantsTab.
 */
export default function TenantConnectionsTable({
  tenants,
  debouncedSearch,
  connPage,
  setConnPage,
  dbStatus,
  introspecting,
  processingKey,
  onRefreshSchema,
  onDisconnect,
}) {
  const filteredConns = useMemo(() => {
    if (!debouncedSearch) return tenants;
    const q = debouncedSearch.toLowerCase();
    return tenants.filter(t =>
      t.branch_code.toLowerCase().includes(q) ||
      (t.db_name_label || '').toLowerCase().includes(q));
  }, [tenants, debouncedSearch]);

  const connTotalPages = Math.max(1, Math.ceil(filteredConns.length / PAGE_SIZE));
  useEffect(() => { if (connPage > connTotalPages) setConnPage(connTotalPages); }, [connPage, connTotalPages, setConnPage]);
  const paginatedConns = useMemo(
    () => filteredConns.slice((connPage - 1) * PAGE_SIZE, connPage * PAGE_SIZE),
    [filteredConns, connPage]);

  if (filteredConns.length === 0) {
    return (
      <EmptyState variant="plug"
        title="Belum ada koneksi"
        description='Klik "Hubungkan" di kanan atas untuk menghubungkan cabang ke database.' />
    );
  }

  return (
    <div className="bg-white rounded-xl border border-hairline overflow-hidden shadow-sm">
      <div className="overflow-auto max-h-[420px]">
        <table className="w-full text-left">
          <thead className="bg-surface-soft text-sm text-muted sticky top-0 z-10">
            <tr>
              <th className="p-3">Cabang</th>
              <th className="p-3">Database</th>
              <th className="p-3">Lokasi</th>
              <th className="p-3 w-32">Status</th>
              <th className="p-3 w-0 text-center">Aksi</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-hairline">
            {paginatedConns.map((t, idx) => (
              <motion.tr key={t.branch_code} initial={{ opacity: 0 }} animate={{ opacity: 1 }}
                transition={{ delay: idx * 0.03 }} className="hover:bg-surface-soft/50">
                <td className="p-3 text-sm font-medium">{t.branch_code}</td>
                <td className="p-3 text-sm text-body">{t.db_name_label}</td>
                <td className="p-3 text-sm text-muted">{t.db_host}:{t.db_port}</td>
                <td className="p-3">
                  {(() => {
                    const st = dbStatus[String(t.db_connection_id)];
                    if (!st || st.status === 'checking') {
                      return (
                        <span className="inline-flex items-center text-muted text-xs">
                          <Loader2 size={12} className="mr-1.5 animate-spin" /> Menguji…
                        </span>
                      );
                    }
                    return st.status === 'connected' ? (
                      <span className="inline-flex items-center gap-1.5 text-success text-xs font-medium">
                        <CheckCircle size={13} /> Connected
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 text-error text-xs font-medium">
                        <XCircle size={13} /> Disconnected
                      </span>
                    );
                  })()}
                </td>
                <td className="p-3">
                  <div className="flex justify-end gap-0.5">
                    <button onClick={() => onRefreshSchema(t)} disabled={introspecting === t.branch_code}
                      title="Perbarui Skema" aria-label={`Perbarui skema ${t.branch_code}`}
                      className="p-1.5 text-muted hover:text-primary hover:bg-surface-soft rounded-md disabled:opacity-50">
                      {introspecting === t.branch_code ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}
                    </button>
                    <button onClick={() => onDisconnect(t)} disabled={processingKey === t.branch_code}
                      title="Putuskan" aria-label={`Putuskan ${t.branch_code}`}
                      className="p-1.5 text-muted hover:text-error hover:bg-error/5 rounded-md disabled:opacity-50">
                      {processingKey === t.branch_code ? <Loader2 size={15} className="animate-spin" /> : <Trash2 size={15} />}
                    </button>
                  </div>
                </td>
              </motion.tr>
            ))}
          </tbody>
        </table>
      </div>
      <PaginationBar page={connPage} totalPages={connTotalPages} onChange={setConnPage}
        totalItems={filteredConns.length} pageSize={PAGE_SIZE} />
    </div>
  );
}