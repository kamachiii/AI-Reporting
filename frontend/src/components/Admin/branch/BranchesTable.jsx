import { createPortal } from 'react-dom';
import { motion } from 'framer-motion';
import {
  Plus, CheckCircle, XCircle, Trash2, Pencil,
  Link, Unlink, MoreVertical, Database, Wifi,
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
 * Sub-tabel cabang dengan integrasi tenant DB (status koneksi nyata,
 * aksi hubungkan/putuskan/edit database via dropdown portal).
 * Presentasional: data & handler dari props.
 */
export default function BranchesTable({
  paginatedBranches, totalCount, filteredCount, companiesByCode,
  connectionStatus, tenantData,
  page, totalPages, onPageChange, pageSize,
  sortConfig, onSort,
  processingCode, tableContainerRef,
  onTestConnection, onDisconnect, onConnectDb, onEditTenant,
  onEditBranch, onDeleteBranch, onAddBranch,
  dropdownOpen, setDropdownOpen, dropdownPos, setDropdownPos,
}) {
  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <span className="text-xs text-muted">Menampilkan {filteredCount} dari {totalCount}</span>
        <button onClick={onAddBranch} className="flex items-center gap-2 px-3 py-1.5 bg-primary text-white rounded-md text-xs hover:bg-primary-active">
          <Plus size={14} /> Tambah Cabang
        </button>
      </div>

      {filteredCount === 0 ? (
        <EmptyState
          variant="plug"
          title={totalCount === 0 ? 'Belum ada cabang' : 'Tidak ada hasil'}
          description={
            totalCount === 0
              ? 'Klik "Tambah Cabang" untuk mendaftarkan cabang pertama.'
              : 'Coba kata kunci lain.'
          }
        />
      ) : (
        <div className="bg-white rounded-xl border border-hairline overflow-hidden shadow-sm">
          <div ref={tableContainerRef} className="overflow-x-auto">
            <table className="w-full text-left">
              <thead className="bg-surface-soft text-sm text-muted">
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
                  <th className="p-3 w-28 cursor-pointer select-none hover:text-ink" onClick={() => onSort('status')}>
                    Status DB <SortIcon columnKey="status" sortConfig={sortConfig} />
                  </th>
                  <th className="p-3">Host / Port</th>
                  <th className="p-3 w-0 text-center">Aksi</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-hairline">
                {paginatedBranches.map((b, idx) => {
                  const isProcessing = processingCode === b.code;
                  const status = connectionStatus[b.code] || 'disconnected';
                  const tenant = tenantData[b.code];
                  const isConnected = status === 'connected';
                  const isDropdownOpen = dropdownOpen === b.code;
                  const toggleDropdown = () => setDropdownOpen(isDropdownOpen ? null : b.code);

                  return (
                    <motion.tr key={b.code} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: idx * 0.03 }} className="hover:bg-surface-soft/50 transition-colors relative">
                      <td className="p-3 font-medium text-sm">{b.code}</td>
                      <td className="p-3 text-body text-sm">{b.name}</td>
                      <td className="p-3 text-muted text-sm">{companiesByCode[b.company_code]?.name || b.company_code}</td>
                      <td className="p-3">
                        <span className={`inline-flex items-center text-xs font-medium ${isConnected ? 'text-success' : 'text-error'}`}>
                          {isConnected ? <CheckCircle size={14} className="mr-1" /> : <XCircle size={14} className="mr-1" />}
                          {isConnected ? 'Connected' : 'Disconnected'}
                        </span>
                      </td>
                      <td className="p-3 text-sm text-body">{tenant ? `${tenant.db_host}:${tenant.db_port}` : '-'}</td>

                      {/* Kolom aksi */}
                      <td className="p-3">
                        <div className="flex justify-end">
                          {isConnected ? (
                            <>
                              <button
                                onClick={async () => {
                                  const testPayload = { ...tenant };
                                  delete testPayload.db_password;
                                  const result = await onTestConnection(b.code, testPayload);
                                  if (result.status === 'connected') {
                                    notify.success('Koneksi berhasil!');
                                  } else {
                                    notify.error(`Koneksi gagal: ${result.message || ''}`);
                                  }
                                }}
                                disabled={isProcessing}
                                className="p-1.5 text-muted hover:text-primary hover:bg-surface-soft rounded-md transition-colors disabled:opacity-50"
                                title="Test Koneksi"
                              >
                                <Wifi size={16} />
                              </button>
                              <button
                                onClick={() => onDisconnect(b.code)}
                                disabled={isProcessing}
                                className="p-1.5 text-muted hover:text-error hover:bg-error/5 rounded-md transition-colors disabled:opacity-50"
                                title="Putus Koneksi"
                              >
                                <Unlink size={16} />
                              </button>
                            </>
                          ) : (
                            <button
                              onClick={() => onConnectDb(b)}
                              disabled={isProcessing}
                              className="p-1.5 text-primary hover:bg-primary/5 rounded-md transition-colors disabled:opacity-50"
                              title="Hubungkan Database"
                            >
                              <Link size={16} />
                            </button>
                          )}

                          {/* Dropdown aksi sekunder (portal ke body) */}
                          <div className="relative dropdown-trigger">
                            <button
                              onClick={(e) => {
                                const rect = e.currentTarget.getBoundingClientRect();
                                setDropdownPos({
                                  top: rect.bottom + window.scrollY,
                                  left: rect.right - 160 + window.scrollX,
                                });
                                toggleDropdown();
                              }}
                              className="dropdown-trigger p-1.5 text-muted hover:text-ink hover:bg-surface-soft rounded-md transition-colors"
                            >
                              <MoreVertical size={16} />
                            </button>

                            {isDropdownOpen && createPortal(
                              <div
                                className="fixed z-[9999] w-40 bg-white rounded-md shadow-lg border border-hairline py-1"
                                style={{ top: dropdownPos.top, left: dropdownPos.left }}
                              >
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

                                {isConnected && (
                                  <button
                                    onMouseDown={(e) => {
                                      e.preventDefault();
                                      setDropdownOpen(null);
                                      setTimeout(() => onEditTenant(b.code), 50);
                                    }}
                                    className="flex items-center gap-2 w-full px-4 py-2 text-xs text-ink hover:bg-surface-soft transition-colors text-left"
                                  >
                                    <Database size={14} /> Edit Database
                                  </button>
                                )}

                                <button
                                  onMouseDown={(e) => {
                                    e.preventDefault();
                                    setDropdownOpen(null);
                                    setTimeout(() => onDeleteBranch(b.code), 50);
                                  }}
                                  className="flex items-center gap-2 w-full px-4 py-2 text-xs text-error hover:bg-error/5 transition-colors text-left"
                                >
                                  <Trash2 size={14} /> Hapus Cabang
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
          <PaginationBar page={page} totalPages={totalPages} onChange={onPageChange} totalItems={filteredCount} pageSize={pageSize} />
        </div>
      )}
    </div>
  );
}
