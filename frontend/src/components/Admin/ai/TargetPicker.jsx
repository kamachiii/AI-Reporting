import { useState, useMemo, useRef, useEffect } from 'react';
import { Search, Check, ChevronDown } from 'lucide-react';

/**
 * Autocomplete pemilih target untuk AI config scope tenant/user.
 * - options: [{ value: 'JKT_01', label: 'JKT_01 — Jakarta', sub: 'Detail opsional' }]
 * - Ketik untuk menyaring (search-as-you-type); maks 8 saran ditampilkan.
 * - Nilai terkunci ke pilihan valid (tidak bisa submit nilai bebas).
 */
const MAX_SUGGESTIONS = 8;

export default function TargetPicker({ value, onChange, options, placeholder = 'Cari dan pilih...', id }) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const wrapRef = useRef(null);

  const selected = options.find((o) => o.value === value) || null;

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options.slice(0, MAX_SUGGESTIONS);
    return options
      .filter((o) =>
        o.label.toLowerCase().includes(q) ||
        (o.sub || '').toLowerCase().includes(q))
      .slice(0, MAX_SUGGESTIONS);
  }, [options, query]);

  // tutup saat klik di luar
  useEffect(() => {
    const onDoc = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  const pick = (opt) => {
    onChange(opt.value);
    setQuery('');
    setOpen(false);
  };

  return (
    <div className="relative" ref={wrapRef}>
      <button type="button" id={id}
        onClick={() => setOpen((v) => !v)}
        className="w-full px-3 py-2 border border-hairline rounded-md bg-canvas text-sm text-left hover:bg-surface-soft transition-colors flex justify-between items-center">
        <span className={selected ? 'text-ink truncate' : 'text-muted truncate'}>
          {selected ? selected.label : placeholder}
        </span>
        <ChevronDown size={14} className="text-muted shrink-0" />
      </button>

      {open && (
        <div className="absolute z-30 mt-1 w-full bg-white rounded-md shadow-lg border border-hairline overflow-hidden">
          <div className="p-2 border-b border-hairline">
            <div className="relative">
              <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted" />
              <input
                type="text"
                autoFocus
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Ketik untuk menyaring..."
                className="w-full pl-8 pr-2 py-1.5 text-sm border border-hairline rounded-md bg-canvas focus:outline-none focus:ring-1 focus:ring-primary/40"
              />
            </div>
          </div>
          <div className="max-h-56 overflow-y-auto">
            {filtered.length === 0 ? (
              <p className="px-3 py-4 text-sm text-muted text-center">Tidak ada yang cocok.</p>
            ) : (
              filtered.map((o) => (
                <button key={o.value} type="button"
                  onClick={() => pick(o)}
                  className={`w-full px-3 py-2 text-left text-sm hover:bg-surface-soft transition-colors flex items-center gap-2 ${
                    o.value === value ? 'bg-primary/5' : ''}`}>
                  <span className="flex-1 min-w-0">
                    <span className="block text-ink truncate">{o.label}</span>
                    {o.sub && <span className="block text-[11px] text-muted truncate">{o.sub}</span>}
                  </span>
                  {o.value === value && <Check size={14} className="text-success shrink-0" />}
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
