import { ChevronLeft, ChevronRight } from 'lucide-react';

export default function PaginationBar({ page, totalPages, onChange, totalItems, pageSize }) {
  if (totalItems === 0) return null;
  const startItem = (page - 1) * pageSize + 1;
  const endItem = Math.min(page * pageSize, totalItems);

  return (
    <div className="flex items-center justify-between px-3 py-2.5 border-t border-hairline text-xs text-muted flex-wrap gap-2">
      <span>
        Menampilkan {startItem}-{endItem} dari {totalItems}
      </span>
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={() => onChange(page - 1)}
          disabled={page <= 1}
          className="p-1.5 rounded border border-hairline hover:bg-surface-soft disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          <ChevronLeft size={14} />
        </button>
        <span className="px-2 text-ink font-medium">
          {page} / {totalPages}
        </span>
        <button
          type="button"
          onClick={() => onChange(page + 1)}
          disabled={page >= totalPages}
          className="p-1.5 rounded border border-hairline hover:bg-surface-soft disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          <ChevronRight size={14} />
        </button>
      </div>
    </div>
  );
}