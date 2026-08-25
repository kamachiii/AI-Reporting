import { motion } from 'framer-motion';
import {
  Plus, Loader2, Trash2, Pencil, ToggleRight, ToggleLeft,
  ArrowUp, ArrowDown, ChevronsUpDown
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
 * Sub-tabel perusahaan. Murni presentasional: semua data & handler
 * datang dari props (sumber: useCompanyBranchData + handler di tab).
 */
export default function CompaniesTable({
  paginatedCompanies, totalCount, filteredCount,
  page, totalPages, onPageChange, pageSize,
  sortConfig, onSort,
  processingCode, onToggle, onEdit, onDelete, onAdd,
}) {
  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <span className="text-xs text-muted">Menampilkan {filteredCount} dari {totalCount}</span>
        <button onClick={onAdd} className="flex items-center gap-2 px-3 py-1.5 bg-primary text-white rounded-md text-xs hover:bg-primary-active">
          <Plus size={14} /> Tambah Perusahaan
        </button>
      </div>

      {filteredCount === 0 ? (
        <EmptyState
          variant="box"
          title={totalCount === 0 ? 'Belum ada perusahaan' : 'Tidak ada hasil'}
          description={
            totalCount === 0
              ? 'Klik "Tambah Perusahaan" untuk mendaftarkan perusahaan pertama.'
              : 'Coba kata kunci lain.'
          }
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
                  <th className="p-3 w-24 cursor-pointer select-none hover:text-ink" onClick={() => onSort('is_active')}>
                    Status <SortIcon columnKey="is_active" sortConfig={sortConfig} />
                  </th>
                  <th className="p-3 w-24">Aksi</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-hairline">
                {paginatedCompanies.map((c, idx) => (
                  <motion.tr key={c.code} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: idx * 0.03 }} className="hover:bg-surface-soft/50 transition-colors">
                    <td className="p-3 font-medium text-sm">{c.code}</td>
                    <td className="p-3 text-body text-sm">{c.name}</td>
                    <td className="p-3 text-muted text-sm">{c.address || '-'}</td>
                    <td className="p-3">
                      <button onClick={() => onToggle(c)} disabled={processingCode === c.code} className="flex items-center gap-1 text-xs font-medium hover:opacity-80 disabled:opacity-50">
                        {processingCode === c.code ? <Loader2 size={16} className="animate-spin" /> : c.is_active ? <><ToggleRight size={18} className="text-success" /> Aktif</> : <><ToggleLeft size={18} className="text-error" /> Nonaktif</>}
                      </button>
                    </td>
                    <td className="p-3 flex gap-2">
                      <button onClick={() => onEdit(c)} className="text-muted hover:text-ink"><Pencil size={16} /></button>
                      <button onClick={() => onDelete(c.code)} className="text-muted hover:text-error"><Trash2 size={16} /></button>
                    </td>
                  </motion.tr>
                ))}
              </tbody>
            </table>
          </div>
          <PaginationBar page={page} totalPages={totalPages} onChange={onPageChange} totalItems={filteredCount} pageSize={pageSize} />
        </div>
      )}
    </div>
  );
}
