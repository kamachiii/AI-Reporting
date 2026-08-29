import { useState, useEffect, Fragment } from 'react';
import { motion } from 'framer-motion';
import { api } from '../../services/api';
import { notify } from '../../utils/notification';
import { RefreshCw, Search, CheckCircle, XCircle, Clock, X, ChevronDown } from 'lucide-react';
import EmptyState from './common/EmptyState';
import PaginationBar from './common/PaginationBar';
import SkeletonTable from './common/SkeletonTable';

const PAGE_SIZE = 20;

// asyncpg mengembalikan jsonb sebagai string — pretty-print dengan aman
const prettyJson = (v) => {
  if (v == null) return '-';
  try {
    const obj = typeof v === 'string' ? JSON.parse(v) : v;
    return JSON.stringify(obj, null, 2);
  } catch {
    return String(v);
  }
};

export default function AuditLogTab() {
  const [logs, setLogs] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  // Pencarian server-side: hanya dikirim ke API saat Enter (searchQuery), bukan tiap ketikan
  const [searchQuery, setSearchQuery] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  // Baris log yang sedang di-expand (lihat SQL rencana/hasil + error)
  const [expandedId, setExpandedId] = useState(null);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const fetchLogs = async (opts = {}) => {
    const p = opts.page ?? page;
    setLoading(true);
    try {
      const params = { page: p, per_page: PAGE_SIZE };
      if (statusFilter) params.status = statusFilter;
      if (dateFrom) params.date_from = dateFrom;
      if (dateTo) params.date_to = dateTo;
      if (searchQuery) params.q = searchQuery;
      const data = await api.getAuditLogs(params);
      setLogs(data.data || []);
      setTotal(data.total || 0);
    } catch {
      notify.error('Gagal memuat log aktivitas');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchLogs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, statusFilter, dateFrom, dateTo, searchQuery]);

  const handleRefresh = async () => {
    setRefreshing(true);
    await fetchLogs();
  };

  const handleSearchKey = (e) => {
    if (e.key === 'Enter') {
      setSearchQuery(searchTerm.trim());
      setPage(1);
    }
  };

  const formatDate = (iso) => {
    if (!iso) return '-';
    try {
      const d = new Date(iso);
      return d.toLocaleString('id-ID', {
        day: '2-digit', month: 'short', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
      });
    } catch {
      return '-';
    }
  };

  const statusBadge = (s) => {
    const base = 'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium';
    if (s === 'success') return <span className={`${base} bg-success/10 text-success`}><CheckCircle size={12} /> Sukses</span>;
    if (s === 'error' || s === 'failed') return <span className={`${base} bg-error/10 text-error`}><XCircle size={12} /> Gagal</span>;
    return <span className={`${base} bg-surface-soft text-muted`}><Clock size={12} /> {s || 'Unknown'}</span>;
  };

  const clearFilters = () => {
    setStatusFilter('');
    setDateFrom('');
    setDateTo('');
    setSearchTerm('');
    setSearchQuery('');
    setPage(1);
  };

  const hasFilters = statusFilter || dateFrom || dateTo || searchTerm;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3">
          <h2 className="font-serif text-lg text-ink">Audit Log</h2>
          <span className="text-xs text-muted bg-surface-soft px-2 py-1 rounded-full">
            {total} entri
          </span>
        </div>
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          className="px-3 py-1.5 rounded-md border border-hairline text-sm hover:bg-surface-soft transition-colors flex items-center gap-1.5 disabled:opacity-50"
        >
          <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-2 flex-wrap bg-surface-soft/50 border border-hairline rounded-lg p-2">
        <div className="relative flex-1 min-w-[160px]">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted" />
          <input
            id="audit-search"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            onKeyDown={handleSearchKey}
            aria-label="Cari log aktivitas"
            placeholder="Cari user, cabang, atau pertanyaan... (Enter)"
            className="w-full pl-8 pr-8 py-1.5 text-sm bg-canvas border border-hairline rounded-md focus:outline-none focus:ring-1 focus:ring-accent/40"
          />
          {searchTerm && (
            <button
              type="button"
              aria-label="Bersihkan pencarian"
              onClick={() => { setSearchTerm(''); setSearchQuery(''); }}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted hover:text-ink"
            >
              <X size={14} />
            </button>
          )}
        </div>

        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
          className="px-2 py-1.5 text-sm bg-canvas border border-hairline rounded-md focus:outline-none"
        >
          <option value="">Semua status</option>
          <option value="success">Sukses</option>
          <option value="error">Gagal</option>
        </select>

        <div className="flex items-center gap-1.5">
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => { setDateFrom(e.target.value); setPage(1); }}
            className="px-2 py-1.5 text-sm bg-canvas border border-hairline rounded-md"
            title="Dari tanggal (YYYY-MM-DD)"
            aria-label="Dari tanggal"
          />
          <span className="text-muted text-sm">–</span>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => { setDateTo(e.target.value); setPage(1); }}
            className="px-2 py-1.5 text-sm bg-canvas border border-hairline rounded-md"
            title="Sampai tanggal (YYYY-MM-DD)"
            aria-label="Sampai tanggal"
          />
        </div>

        {hasFilters && (
          <button
            onClick={clearFilters}
            className="px-2 py-1.5 text-sm text-muted hover:text-ink transition-colors"
          >
            Reset
          </button>
        )}
      </div>

      {/* Tabel */}
      <div className="border border-hairline rounded-lg overflow-hidden bg-canvas">
        {loading ? (
          <SkeletonTable rows={8} columns={5} />
        ) : logs.length === 0 ? (
          <EmptyState
            title={hasFilters ? 'Tidak ada log yang cocok' : 'Belum ada aktivitas'}
            description={hasFilters ? 'Coba ubah kata kunci atau filter.' : 'Log query AI akan muncul di sini saat user mengajukan pertanyaan.'}
          />
        ) : (
          <div className="overflow-auto max-h-[420px]">
            <table className="w-full text-sm">
              <thead className="bg-surface-soft sticky top-0 z-10">
                <tr className="text-left text-xs uppercase tracking-wider text-muted border-b border-hairline">
                  <th className="px-2 py-2 w-8"><span className="sr-only">Detail</span></th>
                  <th className="px-3 py-2">Waktu</th>
                  <th className="px-3 py-2">User</th>
                  <th className="px-3 py-2">Cabang</th>
                  <th className="px-3 py-2">Pertanyaan</th>
                  <th className="px-3 py-2">Durasi</th>
                  <th className="px-3 py-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((l) => (
                  <Fragment key={l.id}>
                  <motion.tr
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    className="border-b border-hairline/60 hover:bg-surface-soft/40"
                  >
                    <td className="px-2 py-2 align-middle">
                      <button
                        onClick={() => setExpandedId(expandedId === l.id ? null : l.id)}
                        aria-label={expandedId === l.id ? 'Tutup detail log' : 'Lihat detail log'}
                        aria-expanded={expandedId === l.id}
                        className="p-1 text-muted hover:text-ink rounded-md transition-colors"
                      >
                        <ChevronDown size={14} className={`transition-transform ${expandedId === l.id ? 'rotate-180' : ''}`} />
                      </button>
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap text-muted">{formatDate(l.created_at)}</td>
                    <td className="px-3 py-2">{l.user_name || `#${l.user_id}` || '-'}</td>
                    <td className="px-3 py-2 font-mono text-xs">{l.branch_code}</td>
                    <td className="px-3 py-2 max-w-[260px]">
                      <div className="truncate" title={l.prompt_text || ''}>
                        {l.prompt_text || '-'}
                      </div>
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap text-muted">
                      {l.execution_time_ms != null ? `${l.execution_time_ms} ms` : '-'}
                    </td>
                    <td className="px-3 py-2">{statusBadge(l.status)}</td>
                  </motion.tr>

                  {/* Baris detail: SQL, rencana JSON, error — inti tab monitoring */}
                  {expandedId === l.id && (
                    <tr className="bg-surface-soft/30">
                      <td colSpan={7} className="px-4 py-3">
                        <div className="grid grid-cols-1 gap-2.5 text-xs">
                          <div>
                            <span className="text-muted uppercase tracking-wide">Pertanyaan</span>
                            <p className="text-body whitespace-pre-wrap mt-0.5">{l.prompt_text || '-'}</p>
                          </div>
                          <div>
                            <span className="text-muted uppercase tracking-wide">SQL yang dihasilkan</span>
                            <pre className="mt-0.5 bg-canvas border border-hairline rounded-md p-2 overflow-x-auto font-mono text-[11px] text-body whitespace-pre-wrap">
                              {l.generated_sql || '-'}
                            </pre>
                          </div>
                          <div>
                            <span className="text-muted uppercase tracking-wide">Rencana JSON (AI)</span>
                            <pre className="mt-0.5 bg-canvas border border-hairline rounded-md p-2 overflow-x-auto font-mono text-[11px] text-body max-h-40 overflow-y-auto">
                              {prettyJson(l.ai_json_filter)}
                            </pre>
                          </div>
                          {l.error_message && (
                            <div>
                              <span className="text-muted uppercase tracking-wide">Pesan error</span>
                              <p className="text-error mt-0.5 whitespace-pre-wrap">{l.error_message}</p>
                            </div>
                          )}
                          <p className="text-muted">
                            {l.user_name || (l.user_id ? `#${l.user_id}` : 'Anonim')} · cabang {l.branch_code} ·{' '}
                            {l.execution_time_ms != null ? `${l.execution_time_ms} ms` : 'durasi -'} · {formatDate(l.created_at)}
                          </p>
                        </div>
                      </td>
                    </tr>
                  )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Pagination (komponen bersama, sama dengan tab admin lain) */}
      {!loading && totalPages > 1 && (
        <PaginationBar page={page} totalPages={totalPages} onChange={setPage} totalItems={total} pageSize={PAGE_SIZE} />
      )}
    </div>
  );
}