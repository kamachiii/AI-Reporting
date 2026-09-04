import { ArrowUp, ArrowDown, ChevronsUpDown } from 'lucide-react';

/**
 * Ikon indikator sorting seragam untuk seluruh tabel admin.
 * - Netral (belum aktif): ChevronsUpDown text-muted
 * - Ascending: ArrowUp text-primary
 * - Descending: ArrowDown text-primary
 */
export default function SortIcon({ columnKey, sortConfig }) {
  if (!sortConfig || sortConfig.key !== columnKey) {
    return <ChevronsUpDown size={14} className="inline ml-1 text-muted" aria-hidden="true" />;
  }
  return sortConfig.direction === 'asc' ? (
    <ArrowUp size={14} className="inline ml-1 text-primary" aria-hidden="true" />
  ) : (
    <ArrowDown size={14} className="inline ml-1 text-primary" aria-hidden="true" />
  );
}
