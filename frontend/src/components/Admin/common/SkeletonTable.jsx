/**
 * Skeleton loading berbentuk tabel — dipakai semua tab admin
 * saat data sedang dimuat. rows = jumlah baris placeholder.
 */
export default function SkeletonTable({ rows = 4, columns = 4 }) {
  const widths = ['w-1/6', 'w-1/4', 'w-1/4', 'w-1/6', 'w-1/6', 'w-1/5'];
  return (
    <div className="bg-white rounded-xl border border-hairline overflow-hidden shadow-sm p-4 space-y-3 animate-pulse">
      <div className="h-8 bg-surface-soft rounded w-1/4 mb-4" />
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex gap-4">
          {Array.from({ length: columns }).map((_, j) => (
            <div key={j} className={`h-6 bg-surface-soft rounded ${widths[j % widths.length]}`} />
          ))}
        </div>
      ))}
    </div>
  );
}
