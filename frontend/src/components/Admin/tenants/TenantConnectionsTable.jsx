import { useState, useEffect, useMemo } from 'react';
import { motion } from 'framer-motion';
import { CheckCircle, XCircle, Loader2, RefreshCw, Trash2, BookOpen, Zap, Layers, Shield } from 'lucide-react';
import PaginationBar from '../common/PaginationBar';
import EmptyState from '../common/EmptyState';
import SortIcon from '../common/SortIcon';

const PAGE_SIZE = 10; // sinkron dengan DatabaseRegistryTable (ukuran halaman tabel admin)

/**
 * Tabel relasi cabang ↔ database (sub-tab "Koneksi" di TenantsTab).
 * Presentational: menerima data + callback; sorting, pagination & render murni di sini —
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
  tier2Busy,
  onRefreshSchema,
  onManageKb,
  onSetChatMode,
  onDisconnect,
}) {
  const [sortConfig, setSortConfig] = useState({ key: 'branch_code', direction: 'asc' });

  const handleSort = (key) => {
    let direction = 'asc';
    if (sortConfig.key === key && sortConfig.direction === 'asc') direction = 'desc';
    setSortConfig({ key, direction });
  };

  const filteredConns = useMemo(() => {
    if (!debouncedSearch) return tenants;
    const q = debouncedSearch.toLowerCase();
    return tenants.filter(t =>
      t.branch_code.toLowerCase().includes(q) ||
      (t.db_name_label || '').toLowerCase().includes(q));
  }, [tenants, debouncedSearch]);

  const sortedConns = useMemo(() => {
    const sorted = [...filteredConns];
    return sorted.sort((a, b) => {
      let aVal = a[sortConfig.key] ?? '';
      let bVal = b[sortConfig.key] ?? '';

      if (sortConfig.key === 'status') {
        aVal = dbStatus[String(a.db_connection_id)]?.status || '';
        bVal = dbStatus[String(b.db_connection_id)]?.status || '';
      }

      if (typeof aVal === 'string') aVal = aVal.toLowerCase();
      if (typeof bVal === 'string') bVal = bVal.toLowerCase();

      if (aVal < bVal) return sortConfig.direction === 'asc' ? -1 : 1;
      if (aVal > bVal) return sortConfig.direction === 'asc' ? 1 : -1;
      return 0;
    });
  }, [filteredConns, sortConfig, dbStatus]);

  const connTotalPages = Math.max(1, Math.ceil(sortedConns.length / PAGE_SIZE));
  useEffect(() => { if (connPage > connTotalPages) setConnPage(connTotalPages); }, [connPage, connTotalPages, setConnPage]);
  const paginatedConns = useMemo(
    () => sortedConns.slice((connPage - 1) * PAGE_SIZE, connPage * PAGE_SIZE),
    [sortedConns, connPage]);

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
              <th className="p-3 cursor-pointer select-none hover:text-ink" onClick={() => handleSort('branch_code')}>
                Cabang <SortIcon columnKey="branch_code" sortConfig={sortConfig} />
              </th>
              <th className="p-3 cursor-pointer select-none hover:text-ink" onClick={() => handleSort('db_name_label')}>
                Database <SortIcon columnKey="db_name_label" sortConfig={sortConfig} />
              </th>
              <th className="p-3 cursor-pointer select-none hover:text-ink" onClick={() => handleSort('db_host')}>
                Lokasi <SortIcon columnKey="db_host" sortConfig={sortConfig} />
              </th>
              <th className="p-3 w-36 cursor-pointer select-none hover:text-ink" onClick={() => handleSort('status')}>
                Status <SortIcon columnKey="status" sortConfig={sortConfig} />
              </th>
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
                  <div className="flex justify-end items-center gap-0.5">
                    {/* Mode AI Selector (Opsi 1: vanna | tier2 | tier1) */}
                    {(() => {
                      const curMode = t.chat_mode || (t.chat_tier2 ? 'tier2' : 'vanna');
                      return (
                        <div className="relative inline-flex items-center mr-2">
                          <span className="absolute left-2 pointer-events-none text-muted">
                            {curMode === 'vanna' ? (
                              <Zap size={11} />
                            ) : curMode === 'tier2' ? (
                              <Layers size={11} />
                            ) : (
                              <Shield size={11} />
                            )}
                          </span>
                          <select
                            value={curMode}
                            onChange={(e) => onSetChatMode && onSetChatMode(t, e.target.value)}
                            disabled={tier2Busy === t.branch_code}
                            aria-label={`Mode AI ${t.branch_code}`}
                            title="Pilih Mode Eksekusi AI untuk cabang ini"
                            className="text-xs py-1 pl-6 pr-2 rounded-md border border-hairline bg-canvas text-ink font-medium focus:outline-none focus:ring-1 focus:ring-primary/40 focus:border-primary/40 hover:border-hairline-strong cursor-pointer transition-colors"
                          >
                            <option value="vanna">Mode Vanna</option>
                            <option value="tier2">Tier 2 (Kompleks)</option>
                            <option value="tier1">Tier 1 (Standar)</option>
                          </select>
                          {tier2Busy === t.branch_code && (
                            <Loader2 size={12} className="animate-spin ml-1.5 text-primary" />
                          )}
                        </div>
                      );
                    })()}
                    <button onClick={() => onManageKb(t)} disabled={processingKey === t.branch_code}
                      title="Knowledge Base" aria-label={`Knowledge Base ${t.branch_code}`}
                      className="p-1.5 text-muted hover:text-primary hover:bg-surface-soft rounded-md disabled:opacity-50">
                      <BookOpen size={15} />
                    </button>
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