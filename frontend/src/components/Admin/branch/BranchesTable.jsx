import { createPortal } from 'react-dom';
import { motion } from 'framer-motion';
import {
  CheckCircle, XCircle, Loader2, Trash2, Pencil,
  Link, MoreVertical, Database, Wifi, Eye, Power,
  ArrowUp, ArrowDown, ChevronsUpDown
} from 'lucide-react';
import { notify } from '../../../utils/notification';
import EmptyState from '../common/EmptyState';
import PaginationBar from '../common/PaginationBar';

function SortIcon({ columnKey, sortConfig }) {
  if (sortConfig.key !== columnKey) {
    return <ChevronsUpDown size={14} className="inline ml-1 text-muted" />;
  }
  return sortConfig.direction === 'asc'
    ? <ArrowUp size={14} className="inline ml-1 text-primary" />
    : <ArrowDown size={14} className="inline ml-1 text-primary" />;
}

/**
 * Sub-tabel cabang.
 * Kolom: Status cabang (badge pasif) + Database (nama registry yang dipilih
 * + status koneksi nyata). Aksi: hubungkan DB, dropdown (detail/edit/status/
 * hapus). Toggle status cabang memakai endpoint khusus + konfirmasi di tab.
 */
export default function BranchesTable({
  paginatedBranches, filteredBranches, companiesByCode,
  connectionStatus, tenantData, dbConnectionsById,
  page, totalPages, onPageChange, pageSize,
  sortConfig, onSort,
  processingCode, tableContainerRef,
  onTestConnection, onConnectDb,
  onViewDetail, onEditBranch, onDeleteBranch,
  onToggleStatusRequest,
  dropdownOpen, setDropdownOpen, dropdownPos, setDropdownPos,
}) {
  return (
    <div className="space-y-4">

      {paginatedBranches.length === 0 ? (
        <EmptyState
          variant="plug"
          title={'Belum ada cabang'}
          description='Klik "Tambah Cabang" di kanan atas untuk mendaftarkan cabang pertama. Cabang terhubung database lewat panel Database Terdaftar di bawah.'
        />
      ) : (
        <div className="bg-white rounded-xl border border-hairline overflow-hidden shadow-sm">
          <div ref={tableContainerRef} className="overflow-auto max-h-[420px]">
            <table className="w-full text-left">
              <thead className="bg-surface-soft text-sm text-muted sticky top-0 z-10">
                <tr>
                  <th className="p-3 w-24 cursor-pointer select-none hover:text-ink" onClick={() => onSort('code')}>
                    Kode <SortIcon columnKey="code" sortConfig={sortConfig} />
                  </th>
                  <th className="p-3 cursor-pointer select-none hover:text-ink" onClick={() => onSort('name')}>
                    Nama Cabang <SortIcon columnKey="name" sortConfig={sortConfig} />
                  </th>
                  <th className="p-3 cursor-pointer select-none hover:text-ink" onClick={() => onSort('company_code')}>
                    Perusahaan <SortIcon columnKey="company_code" sortConfig={sortConfig} />
                  </th>
                  <th className="p-3 w-28 cursor-pointer select-none hover:text-ink" onClick={() => onSort('status_branch')}>
                    Status <SortIcon columnKey="status_branch" sortConfig={sortConfig} />
                  </th>
                  <th className="p-3 cursor-pointer select-none hover:text-ink min-w-[180px]" onClick={() => onSort('db')}>
                    Database <SortIcon columnKey="db" sortConfig={sortConfig} />
                  </th>
                  <th className="p-3 w-0 text-center">Aksi</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-hairline">
                {paginatedBranches.map((b, idx) => {
                  const isProcessing = processingCode === b.code;
                  const tenant = tenantData[b.code];
                  const dbLabel = tenant ? (dbConnectionsById[tenant.db_connection_id]?.name || tenant.db_name_label || `#${tenant.db_connection_id}`) : null;
                  const connState = connectionStatus[b.code]; // connected | disconnected | checking | undefined

                  const isDropdownOpen = dropdownOpen === b.code;
                  const toggleDropdown = () => setDropdownOpen(isDropdownOpen ? null : b.code);

                  return (
                    <motion.tr key={b.code} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: idx * 0.03 }} className="hover:bg-surface-soft/50 transition-colors relative">
                      <td className="p-3 font-medium text-sm">{b.code}</td>
                      <td className="p-3 text-body text-sm">{b.name}</td>
                      <td className="p-3 text-muted text-sm">{companiesByCode[b.company_code]?.name || b.company_code}</td>

                      {/* Status cabang: badge pasif */}
                      <td className="p-3">
                        {isProcessing ? (
                          <span className="inline-flex items-center gap-1.5 text-muted text-xs"><Loader2 size={13} className="animate-spin" /> Memproses…</span>
                        ) : b.is_active ? (
                          <span className="inline-flex items-center gap-1.5 text-success text-xs font-medium">
                            <span className="w-1.5 h-1.5 rounded-full bg-success" /> Aktif
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1.5 text-error text-xs font-medium">
                            <span className="w-1.5 h-1.5 rounded-full bg-error opacity-70" /> Nonaktif
                          </span>
                        )}
                      </td>

                      {/* Database: nama pilihan + status koneksi nyata */}
                      <td className="p-3">
                        {tenant ? (
                          <div className="flex flex-col gap-0.5">
                            <span className="text-sm text-body font-medium">{dbLabel}</span>
                            {connState === 'checking' || !connState ? (
                              <span className="inline-flex items-center text-muted text-xs">
                                <Loader2 size={11} className="mr-1 animate-spin" /> Menguji…
                              </span>
                            ) : connState === 'connected' ? (
                              <span className="inline-flex items-center text-success text-xs">
                                <CheckCircle size={12} className="mr-1" /> Connected
                              </span>
                            ) : (
                              <span className="inline-flex items-center text-error text-xs">
                                <XCircle size={12} className="mr-1" /> Disconnected
                              </span>
                            )}
                          </div>
                        ) : (
                          <button onClick={() => onConnectDb(b)} disabled={isProcessing}
                            className="inline-flex items-center gap-1.5 text-xs text-primary border border-primary/30 rounded-md px-2 py-1 hover:bg-primary/5 transition-colors disabled:opacity-50">
                            <Link size={12} /> Hubungkan Database
                          </button>
                        )}
                      </td>

                      {/* Kolom aksi */}
                      <td className="p-3">
                        <div className="flex justify-end">
                          {tenant && (
                            <>
                              <button
                                onClick={async () => {
                                  const result = await onTestConnection(b.code);
                                  if (result.status === 'connected') notify.success('Koneksi berhasil!');
                                  else notify.error(`Koneksi gagal: ${result.message || ''}`);
                                }}
                                disabled={isProcessing}
                                className="p-1.5 text-muted hover:text-primary hover:bg-surface-soft rounded-md transition-colors disabled:opacity-50"
                                title="Test Koneksi"
                              >
                                <Wifi size={16} />
                              </button>
                              <button
                                onClick={() => onConnectDb(b)}
                                disabled={isProcessing}
                                className="p-1.5 text-muted hover:text-primary hover:bg-surface-soft rounded-md transition-colors disabled:opacity-50"
                                title="Ganti Database"
                              >
                                <Database size={16} />
                              </button>
                            </>
                          )}

                          {/* Dropdown aksi sekunder (portal ke body) */}
                          <div className="relative dropdown-trigger">
                            <button
                              onClick={(e) => {
                                const rect = e.currentTarget.getBoundingClientRect();
                                setDropdownPos({
                                  top: rect.bottom + window.scrollY,
                                  left: rect.right - 180 + window.scrollX,
                                });
                                toggleDropdown();
                              }}
                              className="dropdown-trigger p-1.5 text-muted hover:text-ink hover:bg-surface-soft rounded-md transition-colors"
                            >
                              <MoreVertical size={16} />
                            </button>

                            {isDropdownOpen && createPortal(
                              <div
                                className="fixed z-[9999] w-48 bg-white rounded-md shadow-lg border border-hairline py-1"
                                style={{ top: dropdownPos.top, left: dropdownPos.left }}
                              >
                                <button
                                  onMouseDown={(e) => {
                                    e.preventDefault();
                                    setDropdownOpen(null);
                                    setTimeout(() => onViewDetail(b), 50);
                                  }}
                                  className="flex items-center gap-2 w-full px-4 py-2 text-xs text-ink hover:bg-surface-soft transition-colors text-left"
                                >
                                  <Eye size={14} /> Lihat Detail
                                </button>

                                <button
                                  onMouseDown={(e) => {
                                    e.preventDefault();
                                    setDropdownOpen(null);
                                    setTimeout(() => onEditBranch(b), 50);
                                  }}
                                  className="flex items-center gap-2 w-full px-4 py-2 text-xs text-ink hover:bg-surface-soft transition-colors text-left"
                                >
                                  <Pencil size={14} /> Edit Cabang
                                </button>

                                <button
                                  onMouseDown={(e) => {
                                    e.preventDefault();
                                    setDropdownOpen(null);
                                    setTimeout(() => onToggleStatusRequest(b), 50);
                                  }}
                                  className="flex items-center gap-2 w-full px-4 py-2 text-xs hover:bg-surface-soft transition-colors text-left"
                                >
                                  <Power size={14} className={b.is_active ? 'text-error' : 'text-success'} />
                                  {b.is_active
                                    ? <span className="text-error">Nonaktifkan Cabang…</span>
                                    : <span className="text-success">Aktifkan Cabang…</span>}
                                </button>

                                <button
                                  onMouseDown={(e) => {
                                    e.preventDefault();
                                    setDropdownOpen(null);
                                    setTimeout(() => onDeleteBranch(b.code), 50);
                                  }}
                                  className="flex items-center gap-2 w-full px-4 py-2 text-xs text-error hover:bg-error/5 transition-colors text-left"
                                >
                                  <Trash2 size={14} /> Hapus Cabang…
                                </button>
                              </div>,
                              document.body
                            )}
                          </div>
                        </div>
                      </td>
                    </motion.tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <PaginationBar page={page} totalPages={totalPages} onChange={onPageChange} totalItems={filteredBranches.length} pageSize={pageSize} />
        </div>
      )}
    </div>
  );
}
