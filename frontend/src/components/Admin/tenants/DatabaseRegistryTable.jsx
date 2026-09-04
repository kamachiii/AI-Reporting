import { useState, useEffect, useMemo } from 'react';
import { motion } from 'framer-motion';
import { CheckCircle, XCircle, Loader2, Wifi, Pencil, Trash2 } from 'lucide-react';
import PaginationBar from '../common/PaginationBar';
import EmptyState from '../common/EmptyState';
import SortIcon from '../common/SortIcon';

const PAGE_SIZE = 10; // sinkron dengan TenantConnectionsTable (ukuran halaman tabel admin)

/**
 * Tabel registry database (sub-tab "Database" di TenantsTab).
 * Presentational: menerima data + callback; filter, sorting, pagination, dan
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
  const [sortConfig, setSortConfig] = useState({ key: 'name', direction: 'asc' });

  const handleSort = (key) => {
    let direction = 'asc';
    if (sortConfig.key === key && sortConfig.direction === 'asc') direction = 'desc';
    setSortConfig({ key, direction });
  };

  const usedByMap = useMemo(() => {
    const m = {};
    tenants.forEach(t => { m[t.db_connection_id] = (m[t.db_connection_id] || 0) + 1; });
    return m;
  }, [tenants]);

  const filteredDbs = useMemo(() => {
    if (!debouncedSearch) return connections;
    const q = debouncedSearch.toLowerCase();
    return connections.filter(c =>
      c.name.toLowerCase().includes(q) ||
      (c.db_host || '').toLowerCase().includes(q) ||
      (c.db_name || '').toLowerCase().includes(q));
  }, [connections, debouncedSearch]);

  const sortedDbs = useMemo(() => {
    const sorted = [...filteredDbs];
    return sorted.sort((a, b) => {
      let aVal = a[sortConfig.key] ?? '';
      let bVal = b[sortConfig.key] ?? '';

      if (sortConfig.key === 'used_by') {
        aVal = usedByMap[a.id] ?? a.used_by ?? 0;
        bVal = usedByMap[b.id] ?? b.used_by ?? 0;
        return sortConfig.direction === 'asc' ? aVal - bVal : bVal - aVal;
      }
      if (sortConfig.key === 'is_active') {
        const av = a.is_active ? 1 : 0;
        const bv = b.is_active ? 1 : 0;
        return sortConfig.direction === 'asc' ? av - bv : bv - av;
      }
      if (sortConfig.key === 'connection') {
        aVal = dbStatus[String(a.id)]?.status || '';
        bVal = dbStatus[String(b.id)]?.status || '';
      }

      if (typeof aVal === 'string') aVal = aVal.toLowerCase();
      if (typeof bVal === 'string') bVal = bVal.toLowerCase();

      if (aVal < bVal) return sortConfig.direction === 'asc' ? -1 : 1;
      if (aVal > bVal) return sortConfig.direction === 'asc' ? 1 : -1;
      return 0;
    });
  }, [filteredDbs, sortConfig, usedByMap, dbStatus]);

  const dbTotalPages = Math.max(1, Math.ceil(sortedDbs.length / PAGE_SIZE));
  useEffect(() => { if (dbPage > dbTotalPages) setDbPage(dbTotalPages); }, [dbPage, dbTotalPages, setDbPage]);
  const paginatedDbs = useMemo(
    () => sortedDbs.slice((dbPage - 1) * PAGE_SIZE, dbPage * PAGE_SIZE),
    [sortedDbs, dbPage]);

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
              <th className="p-3 cursor-pointer select-none hover:text-ink" onClick={() => handleSort('name')}>
                Nama <SortIcon columnKey="name" sortConfig={sortConfig} />
              </th>
              <th className="p-3 cursor-pointer select-none hover:text-ink" onClick={() => handleSort('db_host')}>
                Host <SortIcon columnKey="db_host" sortConfig={sortConfig} />
              </th>
              <th className="p-3 cursor-pointer select-none hover:text-ink" onClick={() => handleSort('db_name')}>
                Database <SortIcon columnKey="db_name" sortConfig={sortConfig} />
              </th>
              <th className="p-3 w-28 text-center cursor-pointer select-none hover:text-ink" onClick={() => handleSort('used_by')}>
                Dipakai <SortIcon columnKey="used_by" sortConfig={sortConfig} />
              </th>
              <th className="p-3 w-24 cursor-pointer select-none hover:text-ink" onClick={() => handleSort('is_active')}>
                Status <SortIcon columnKey="is_active" sortConfig={sortConfig} />
              </th>
              <th className="p-3 w-32 cursor-pointer select-none hover:text-ink" onClick={() => handleSort('connection')}>
                Koneksi <SortIcon columnKey="connection" sortConfig={sortConfig} />
              </th>
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