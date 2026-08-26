import { useState } from 'react';
import { createPortal } from 'react-dom';
import { motion } from 'framer-motion';
import {
  Loader2, Trash2, Pencil, Eye,
  ArrowUp, ArrowDown, ChevronsUpDown, MoreVertical, Power
} from 'lucide-react';
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
 * Sub-tabel perusahaan.
 * Status = badge pasif (informasi saja). Aksi aktif/nonaktif pindah ke
 * dropdown ⋮ dengan konfirmasi di level tab — tidak ada lagi toggle
 * satu-klik yang mengubah banyak cabang sekaligus.
 */
export default function CompaniesTable({
  paginatedCompanies, filteredCount,
  page, totalPages, onPageChange, pageSize,
  sortConfig, onSort,
  processingCode, onToggleRequest, onEdit, onDelete, onViewDetail,
}) {
  const [menuOpenCode, setMenuOpenCode] = useState(null);
  const [menuPos, setMenuPos] = useState({ top: 0, left: 0 });

  const openMenu = (e, code) => {
    const rect = e.currentTarget.getBoundingClientRect();
    setMenuPos({ top: rect.bottom + window.scrollY, left: rect.right - 180 + window.scrollX });
    setMenuOpenCode(menuOpenCode === code ? null : code);
  };

  const closeMenu = () => setMenuOpenCode(null);

  return (
    <div className="space-y-4">

      {filteredCount === 0 ? (
        <EmptyState
          variant="box"
          title={'Belum ada perusahaan'}
          description='Klik "Tambah Perusahaan" di kanan atas untuk mendaftarkan perusahaan pertama.'
        />
      ) : (
        <div className="bg-white rounded-xl border border-hairline overflow-hidden shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead className="bg-surface-soft text-sm text-muted">
                <tr>
                  <th className="p-3 w-24 cursor-pointer select-none hover:text-ink" onClick={() => onSort('code')}>
                    Kode <SortIcon columnKey="code" sortConfig={sortConfig} />
                  </th>
                  <th className="p-3 cursor-pointer select-none hover:text-ink" onClick={() => onSort('name')}>
                    Nama <SortIcon columnKey="name" sortConfig={sortConfig} />
                  </th>
                  <th className="p-3">Alamat</th>
                  <th className="p-3 w-28 cursor-pointer select-none hover:text-ink" onClick={() => onSort('is_active')}>
                    Status <SortIcon columnKey="is_active" sortConfig={sortConfig} />
                  </th>
                  <th className="p-3 w-28">Aksi</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-hairline">
                {paginatedCompanies.map((c, idx) => {
                  const isProcessing = processingCode === c.code;
                  const isMenuOpen = menuOpenCode === c.code;
                  return (
                    <motion.tr key={c.code} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: idx * 0.03 }} className="hover:bg-surface-soft/50 transition-colors">
                      <td className="p-3 font-medium text-sm">{c.code}</td>
                      <td className="p-3 text-body text-sm">{c.name}</td>
                      <td className="p-3 text-muted text-sm">{c.address || '-'}</td>
                      {/* Status = badge pasif */}
                      <td className="p-3">
                        {isProcessing ? (
                          <span className="inline-flex items-center gap-1.5 text-muted text-xs"><Loader2 size={14} className="animate-spin" /> Memproses…</span>
                        ) : c.is_active ? (
                          <span className="inline-flex items-center gap-1.5 text-success text-xs font-medium">
                            <span className="w-1.5 h-1.5 rounded-full bg-success" /> Aktif
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1.5 text-error text-xs font-medium">
                            <span className="w-1.5 h-1.5 rounded-full bg-error opacity-70" /> Nonaktif
                          </span>
                        )}
                      </td>
                      <td className="p-3">
                        <div className="flex items-center gap-1">
                          <button onClick={() => onViewDetail(c)} disabled={isProcessing}
                            className="p-1.5 text-muted hover:text-primary rounded-md transition-colors disabled:opacity-50" title="Lihat Detail">
                            <Eye size={16} />
                          </button>
                          <button onClick={() => onEdit(c)} disabled={isProcessing}
                            className="p-1.5 text-muted hover:text-ink rounded-md transition-colors disabled:opacity-50" title="Edit">
                            <Pencil size={15} />
                          </button>

                          {/* Dropdown aksi sekunder */}
                          <div className="relative company-menu-trigger">
                            <button onClick={(e) => openMenu(e, c.code)} disabled={isProcessing}
                              className="p-1.5 text-muted hover:text-ink rounded-md transition-colors disabled:opacity-50" title="Aksi Lainnya">
                              <MoreVertical size={15} />
                            </button>

                            {isMenuOpen && createPortal(
                              <>
                                {/* penutup klik-luar */}
                                <div className="fixed inset-0 z-[9998]" onMouseDown={closeMenu} />
                                <div className="fixed z-[9999] w-44 bg-white rounded-md shadow-lg border border-hairline py-1"
                                  style={{ top: menuPos.top, left: menuPos.left }}>
                                  <button
                                    onClick={() => { closeMenu(); onToggleRequest(c); }}
                                    className="flex items-center gap-2 w-full px-4 py-2 text-xs hover:bg-surface-soft transition-colors text-left"
                                  >
                                    {c.is_active
                                      ? <><Power size={14} className="text-error" /> <span className="text-error">Nonaktifkan…</span></>
                                      : <><Power size={14} className="text-success" /> <span className="text-success">Aktifkan…</span></>}
                                  </button>
                                  <button
                                    onClick={() => { closeMenu(); onDelete(c.code); }}
                                    className="flex items-center gap-2 w-full px-4 py-2 text-xs text-error hover:bg-error/5 transition-colors text-left"
                                  >
                                    <Trash2 size={14} /> Hapus…
                                  </button>
                                </div>
                              </>,
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
