import { useState, useEffect, useCallback, Fragment } from 'react';
import { motion } from 'framer-motion';
import { api } from '../../services/api';
import { notify } from '../../utils/notification';
import {
  RefreshCw, Search, CheckCircle, XCircle, Clock, X, ChevronDown,
  Activity, Zap, Gauge, BarChart3, FileText, Settings2, ShieldCheck,
  Building2
} from 'lucide-react';
import {
  ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid, Legend
} from 'recharts';

import EmptyState from './common/EmptyState';
import PaginationBar from './common/PaginationBar';
import SkeletonTable from './common/SkeletonTable';
import SortIcon from './common/SortIcon';
import BranchQuotaModal from './audit/BranchQuotaModal';

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
  const [activeSubTab, setActiveSubTab] = useState('analytics'); // 'analytics' | 'logs'

  // Overview metrics & Branch usage states
  const [overview, setOverview] = useState(null);
  const [timeline, setTimeline] = useState([]);
  const [branches, setBranches] = useState([]);
  const [loadingMetrics, setLoadingMetrics] = useState(true);

  // Quota modal state
  const [selectedBranchForQuota, setSelectedBranchForQuota] = useState(null);
  const [isSavingQuota, setIsSavingQuota] = useState(false);

  // Logs table states
  const [logs, setLogs] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [expandedId, setExpandedId] = useState(null);
  const [sortConfig, setSortConfig] = useState({ key: 'created_at', direction: 'desc' });

  // Load metrics
  const fetchMetrics = useCallback(async () => {
    try {
      const [ovData, tlData, brData] = await Promise.all([
        api.getAIMetricsOverview(),
        api.getAIMetricsTimeline(7),
        api.getAIMetricsBranchUsage(),
      ]);
      setOverview(ovData);
      setTimeline(tlData.timeline || []);
      setBranches(brData.branches || []);
    } catch {
      notify.error('Gagal memuat analitik metrik AI');
    } finally {
      setLoadingMetrics(false);
    }
  }, []);

  // Load logs
  const fetchLogs = useCallback(async (opts = {}) => {
    const p = opts.page ?? page;
    try {
      const params = { page: p, per_page: PAGE_SIZE };
      if (statusFilter) params.status = statusFilter;
      if (dateFrom) params.date_from = dateFrom;
      if (dateTo) params.date_to = dateTo;
      if (searchQuery) params.q = searchQuery;
      params.sort_by = sortConfig.key;
      params.sort_dir = sortConfig.direction;
      const data = await api.getAuditLogs(params);
      setLogs(data.data || []);
      setTotal(data.total || 0);
    } catch {
      notify.error('Gagal memuat log aktivitas');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [page, statusFilter, dateFrom, dateTo, searchQuery, sortConfig]);

  useEffect(() => {
    let ignore = false;
    (async () => {
      try {
        const [ovData, tlData, brData] = await Promise.all([
          api.getAIMetricsOverview(),
          api.getAIMetricsTimeline(7),
          api.getAIMetricsBranchUsage(),
        ]);
        if (!ignore) {
          setOverview(ovData);
          setTimeline(tlData.timeline || []);
          setBranches(brData.branches || []);
        }
      } catch {
        if (!ignore) notify.error('Gagal memuat analitik metrik AI');
      } finally {
        if (!ignore) setLoadingMetrics(false);
      }
    })();
    return () => { ignore = true; };
  }, []);

  useEffect(() => {
    let ignore = false;
    (async () => {
      try {
        const params = { page, per_page: PAGE_SIZE };
        if (statusFilter) params.status = statusFilter;
        if (dateFrom) params.date_from = dateFrom;
        if (dateTo) params.date_to = dateTo;
        if (searchQuery) params.q = searchQuery;
        params.sort_by = sortConfig.key;
        params.sort_dir = sortConfig.direction;
        const data = await api.getAuditLogs(params);
        if (!ignore) {
          setLogs(data.data || []);
          setTotal(data.total || 0);
        }
      } catch {
        if (!ignore) notify.error('Gagal memuat log aktivitas');
      } finally {
        if (!ignore) {
          setLoading(false);
          setRefreshing(false);
        }
      }
    })();
    return () => { ignore = true; };
  }, [page, statusFilter, dateFrom, dateTo, searchQuery, sortConfig]);

  const handleRefresh = async () => {
    setRefreshing(true);
    setLoadingMetrics(true);
    setLoading(true);
    await Promise.all([fetchMetrics(), fetchLogs()]);
  };

  const handleSaveQuota = async (branchCode, newQuota) => {
    setIsSavingQuota(true);
    try {
      const res = await api.updateBranchQuota(branchCode, newQuota);
      notify.success(res.message || 'Batas kuota berhasil diperbarui');
      setSelectedBranchForQuota(null);
      await fetchMetrics();
    } catch (err) {
      notify.error(err.response?.data?.detail || 'Gagal memperbarui kuota');
    } finally {
      setIsSavingQuota(false);
    }
  };

  const handleSort = (key) => {
    let direction = 'asc';
    if (sortConfig.key === key && sortConfig.direction === 'asc') direction = 'desc';
    setSortConfig({ key, direction });
    setPage(1);
    setLoading(true);
  };

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const handleSearchKey = (e) => {
    if (e.key === 'Enter') {
      setSearchQuery(searchTerm.trim());
      setPage(1);
      setLoading(true);
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
    if (s === 'success') return <span className={`${base} bg-emerald-50 text-emerald-700 border border-emerald-200`}><CheckCircle size={12} /> Sukses</span>;
    if (s === 'rejected') return <span className={`${base} bg-amber-50 text-amber-700 border border-amber-200`}><ShieldCheck size={12} /> Ditolak Verifier</span>;
    if (s === 'error' || s === 'failed') return <span className={`${base} bg-rose-50 text-rose-700 border border-rose-200`}><XCircle size={12} /> Gagal</span>;
    return <span className={`${base} bg-surface-soft text-muted`}><Clock size={12} /> {s || 'Unknown'}</span>;
  };

  const clearFilters = () => {
    setStatusFilter('');
    setDateFrom('');
    setDateTo('');
    setSearchTerm('');
    setSearchQuery('');
    setPage(1);
    setLoading(true);
  };

  const hasFilters = statusFilter || dateFrom || dateTo || searchTerm;

  return (
    <div className="space-y-6">
      {/* 1. Header & Actions */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h2 className="font-serif text-2xl text-ink">Audit Log & Analitik AI</h2>
          <p className="text-xs text-muted mt-0.5">
            Pemantauan aktivitas kueri bahasa natural, efisiensi token, dan batas kuota cabang dealer.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* Sub-tab view toggle */}
          <div className="flex items-center bg-surface-soft p-0.5 rounded-lg border border-hairline">
            <button
              onClick={() => setActiveSubTab('analytics')}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-all ${
                activeSubTab === 'analytics'
                  ? 'bg-white text-ink shadow-sm'
                  : 'text-muted hover:text-ink'
              }`}
            >
              <BarChart3 size={14} />
              Analitik & Kuota Cabang
            </button>
            <button
              onClick={() => setActiveSubTab('logs')}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-all ${
                activeSubTab === 'logs'
                  ? 'bg-white text-ink shadow-sm'
                  : 'text-muted hover:text-ink'
              }`}
            >
              <FileText size={14} />
              Log Aktivitas Kueri ({total})
            </button>
          </div>

          <button
            onClick={handleRefresh}
            disabled={refreshing || loadingMetrics}
            className="px-3 py-1.5 rounded-md border border-hairline text-sm bg-white hover:bg-surface-soft transition-colors flex items-center gap-1.5 disabled:opacity-50"
            title="Muat ulang metrik dan log"
          >
            <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>
      </div>

      {/* 2. Executive Stat Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Card 1: Total Queries */}
        <div className="bg-white border border-hairline rounded-xl p-4 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-muted uppercase tracking-wider">Total Kueri AI</span>
            <div className="w-8 h-8 rounded-lg bg-blue-50 text-blue-600 flex items-center justify-center">
              <Activity size={16} />
            </div>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-semibold text-ink">
              {loadingMetrics ? '...' : (overview?.total_queries?.toLocaleString('id-ID') ?? 0)}
            </span>
            <span className="text-xs text-muted">pertanyaan</span>
          </div>
          <div className="mt-2 flex items-center gap-1.5 text-xs">
            <span className="font-medium text-emerald-600">
              {loadingMetrics ? '...' : `${overview?.success_rate ?? 100}%`}
            </span>
            <span className="text-muted">tingkat keberhasilan query</span>
          </div>
        </div>

        {/* Card 2: SQL Memory Savings */}
        <div className="bg-white border border-hairline rounded-xl p-4 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-muted uppercase tracking-wider">Penghematan Memory</span>
            <div className="w-8 h-8 rounded-lg bg-indigo-50 text-indigo-600 flex items-center justify-center">
              <Zap size={16} />
            </div>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-semibold text-indigo-700">
              {loadingMetrics ? '...' : `~${(overview?.tokens_saved ?? 0).toLocaleString('id-ID')}`}
            </span>
            <span className="text-xs text-indigo-600/80 font-medium">token hemat</span>
          </div>
          <div className="mt-2 flex items-center gap-1.5 text-xs text-muted">
            <span className="font-medium text-ink">
              {loadingMetrics ? '...' : (overview?.memory_hits ?? 0)} kueri
            </span>
            <span>0-token replay (Level A)</span>
          </div>
        </div>

        {/* Card 3: Token Usage Today */}
        <div className="bg-white border border-hairline rounded-xl p-4 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-muted uppercase tracking-wider">Konsumsi Token AI</span>
            <div className="w-8 h-8 rounded-lg bg-amber-50 text-amber-600 flex items-center justify-center">
              <Gauge size={16} />
            </div>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-semibold text-ink">
              {loadingMetrics ? '...' : `~${(overview?.tokens_estimated ?? 0).toLocaleString('id-ID')}`}
            </span>
            <span className="text-xs text-muted">token terpakai</span>
          </div>
          <div className="mt-2 flex items-center gap-1.5 text-xs text-muted">
            <span className="font-medium text-ink">
              {loadingMetrics ? '...' : (overview?.today_total ?? 0)} aktivitas
            </span>
            <span>terekam hari ini</span>
          </div>
        </div>

        {/* Card 4: Latency */}
        <div className="bg-white border border-hairline rounded-xl p-4 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-muted uppercase tracking-wider">Rata-rata Durasi</span>
            <div className="w-8 h-8 rounded-lg bg-emerald-50 text-emerald-600 flex items-center justify-center">
              <Clock size={16} />
            </div>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-semibold text-ink">
              {loadingMetrics ? '...' : (overview?.avg_latency_ms ?? 0)}
            </span>
            <span className="text-xs text-muted">ms</span>
          </div>
          <div className="mt-2 flex items-center gap-1 text-xs text-emerald-600 font-medium">
            <CheckCircle size={12} />
            <span>Eksekusi query teroptimasi</span>
          </div>
        </div>
      </div>

      {/* 3. Sub-Tab Content */}
      {activeSubTab === 'analytics' ? (
        <div className="space-y-6">
          {/* 3A. Timeline Chart */}
          <div className="bg-white border border-hairline rounded-xl p-5 shadow-xs">
            <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
              <div>
                <h3 className="font-serif text-base text-ink">Tren Aktivitas & Efisiensi Token (7 Hari Terakhir)</h3>
                <p className="text-xs text-muted">
                  Perbandingan kueri baru LLM vs kueri instan SQL Memory (0-biaya token).
                </p>
              </div>
              <div className="flex items-center gap-3 text-xs">
                <span className="inline-flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-blue-600" /> Kueri LLM
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-emerald-500" /> Memory Replay (0 Token)
                </span>
              </div>
            </div>

            <div className="h-64 w-full">
              {loadingMetrics ? (
                <div className="h-full flex items-center justify-center text-xs text-muted">
                  Memuat visualisasi tren...
                </div>
              ) : timeline.length === 0 ? (
                <div className="h-full flex items-center justify-center text-xs text-muted">
                  Belum ada data riwayat tren.
                </div>
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={timeline} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                    <defs>
                      <linearGradient id="colorLlm" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#2563EB" stopOpacity={0.4} />
                        <stop offset="95%" stopColor="#2563EB" stopOpacity={0} />
                      </linearGradient>
                      <linearGradient id="colorMem" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#10B981" stopOpacity={0.4} />
                        <stop offset="95%" stopColor="#10B981" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" />
                    <XAxis dataKey="formatted_date" stroke="#94A3B8" fontSize={11} tickLine={false} />
                    <YAxis stroke="#94A3B8" fontSize={11} tickLine={false} allowDecimals={false} />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: '#FFFFFF',
                        borderRadius: '8px',
                        border: '1px solid #E2E8F0',
                        fontSize: '12px',
                      }}
                      formatter={(val, name) => [
                        val,
                        name === 'llm_queries' ? 'Kueri LLM' : 'Memory Replay (0 Token)'
                      ]}
                    />
                    <Legend wrapperStyle={{ display: 'none' }} />
                    <Area
                      type="monotone"
                      dataKey="llm_queries"
                      stroke="#2563EB"
                      strokeWidth={2}
                      fillOpacity={1}
                      fill="url(#colorLlm)"
                    />
                    <Area
                      type="monotone"
                      dataKey="memory_hits"
                      stroke="#10B981"
                      strokeWidth={2}
                      fillOpacity={1}
                      fill="url(#colorMem)"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>

          {/* 3B. Branch Quota Monitoring Table */}
          <div className="bg-white border border-hairline rounded-xl overflow-hidden shadow-xs">
            <div className="p-4 border-b border-hairline flex items-center justify-between flex-wrap gap-2">
              <div>
                <h3 className="font-serif text-base text-ink">Pemantauan Kuota Token Harian per Cabang</h3>
                <p className="text-xs text-muted">
                  Penegakan kuota token harian untuk mencegah lonjakan biaya AI per cabang dealer.
                </p>
              </div>
              <span className="text-xs text-muted bg-surface-soft px-2.5 py-1 rounded-full border border-hairline">
                {branches.length} Cabang Terhubung
              </span>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-surface-soft/60">
                  <tr className="text-left text-xs uppercase tracking-wider text-muted border-b border-hairline">
                    <th className="px-4 py-3">Cabang & Perusahaan</th>
                    <th className="px-4 py-3">Kuota Harian</th>
                    <th className="px-4 py-3">Terpakai Hari Ini</th>
                    <th className="px-4 py-3 w-48">Utilisasi Kuota</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3 text-right">Aksi</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-hairline">
                  {loadingMetrics ? (
                    <tr>
                      <td colSpan={6} className="px-4 py-8 text-center text-xs text-muted">
                        Memuat status kuota cabang...
                      </td>
                    </tr>
                  ) : branches.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="px-4 py-8 text-center text-xs text-muted">
                        Belum ada tenant cabang yang terdaftar.
                      </td>
                    </tr>
                  ) : (
                    branches.map((b) => {
                      const isOver = b.status === 'exceeded';
                      const isCrit = b.status === 'critical';
                      const isWarn = b.status === 'warning';

                      let barColor = 'bg-emerald-500';
                      let badge = (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
                          <CheckCircle size={11} /> Normal
                        </span>
                      );

                      if (isOver) {
                        barColor = 'bg-rose-600';
                        badge = (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-rose-50 text-rose-700 border border-rose-200">
                            <XCircle size={11} /> Kuota Habis
                          </span>
                        );
                      } else if (isCrit) {
                        barColor = 'bg-rose-500';
                        badge = (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-rose-50 text-rose-700 border border-rose-200">
                            <Gauge size={11} /> Kritis (&gt;85%)
                          </span>
                        );
                      } else if (isWarn) {
                        barColor = 'bg-amber-500';
                        badge = (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-amber-50 text-amber-700 border border-amber-200">
                            <Clock size={11} /> Waspada
                          </span>
                        );
                      }

                      return (
                        <tr key={b.branch_code} className="hover:bg-surface-soft/30 transition-colors">
                          <td className="px-4 py-3">
                            <div className="font-medium text-ink flex items-center gap-2">
                              <Building2 size={15} className="text-muted shrink-0" />
                              <span>{b.branch_name}</span>
                              <span className="font-mono text-xs px-1.5 py-0.5 rounded bg-surface-soft text-muted">
                                {b.branch_code}
                              </span>
                            </div>
                            <div className="text-xs text-muted mt-0.5 ml-6">
                              {b.company_name} · Total {b.all_time_queries} kueri
                            </div>
                          </td>

                          <td className="px-4 py-3 font-mono text-xs text-ink font-medium">
                            {b.daily_token_quota.toLocaleString('id-ID')} token
                          </td>

                          <td className="px-4 py-3 text-xs">
                            <span className="font-mono font-medium text-ink">
                              ~{b.today_tokens_used.toLocaleString('id-ID')}
                            </span>
                            <span className="text-muted ml-1">({b.today_llm_queries} query)</span>
                          </td>

                          <td className="px-4 py-3">
                            <div className="space-y-1">
                              <div className="flex justify-between text-[11px]">
                                <span className="font-mono text-muted">{b.quota_percentage}%</span>
                              </div>
                              <div className="w-full bg-slate-100 rounded-full h-2 overflow-hidden">
                                <div
                                  className={`h-full rounded-full transition-all ${barColor}`}
                                  style={{ width: `${Math.min(b.quota_percentage, 100)}%` }}
                                />
                              </div>
                            </div>
                          </td>

                          <td className="px-4 py-3 whitespace-nowrap">
                            {badge}
                          </td>

                          <td className="px-4 py-3 text-right">
                            <button
                              onClick={() => setSelectedBranchForQuota(b)}
                              className="px-2.5 py-1 text-xs rounded border border-hairline hover:bg-surface-soft text-ink font-medium transition-colors inline-flex items-center gap-1.5"
                            >
                              <Settings2 size={12} />
                              Atur Kuota
                            </button>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      ) : (
        /* 4. Log Detail Table View */
        <div className="space-y-4">
          {/* Filter bar */}
          <div className="flex items-center gap-2 flex-wrap bg-white border border-hairline rounded-lg p-2.5 shadow-xs">
            <div className="relative flex-1 min-w-[180px]">
              <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted" />
              <input
                id="audit-search"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                onKeyDown={handleSearchKey}
                aria-label="Cari log aktivitas"
                placeholder="Cari user, cabang, atau kueri... (Tekan Enter)"
                className="w-full pl-8 pr-8 py-1.5 text-xs bg-canvas border border-hairline rounded-md focus:outline-none focus:ring-1 focus:ring-primary/40"
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
              onChange={(e) => { setStatusFilter(e.target.value); setPage(1); setLoading(true); }}
              className="px-2.5 py-1.5 text-xs bg-canvas border border-hairline rounded-md focus:outline-none text-ink"
            >
              <option value="">Semua Status</option>
              <option value="success">Sukses</option>
              <option value="rejected">Ditolak Verifier</option>
              <option value="error">Gagal</option>
            </select>

            <div className="flex items-center gap-1.5">
              <input
                type="date"
                value={dateFrom}
                onChange={(e) => { setDateFrom(e.target.value); setPage(1); setLoading(true); }}
                className="px-2.5 py-1.5 text-xs bg-canvas border border-hairline rounded-md text-ink"
                title="Dari tanggal (YYYY-MM-DD)"
                aria-label="Dari tanggal"
              />
              <span className="text-muted text-xs">–</span>
              <input
                type="date"
                value={dateTo}
                onChange={(e) => { setDateTo(e.target.value); setPage(1); setLoading(true); }}
                className="px-2.5 py-1.5 text-xs bg-canvas border border-hairline rounded-md text-ink"
                title="Sampai tanggal (YYYY-MM-DD)"
                aria-label="Sampai tanggal"
              />
            </div>

            {hasFilters && (
              <button
                onClick={clearFilters}
                className="px-2.5 py-1.5 text-xs text-muted hover:text-ink transition-colors border border-hairline rounded-md"
              >
                Reset Filter
              </button>
            )}
          </div>

          {/* Tabel Log */}
          <div className="border border-hairline rounded-xl overflow-hidden bg-white shadow-xs">
            {loading ? (
              <SkeletonTable rows={8} columns={5} />
            ) : logs.length === 0 ? (
              <EmptyState
                title={hasFilters ? 'Tidak ada log yang cocok' : 'Belum ada aktivitas'}
                description={hasFilters ? 'Coba ubah kata kunci atau filter.' : 'Log query AI akan muncul di sini saat user mengajukan pertanyaan.'}
              />
            ) : (
              <div className="overflow-auto max-h-[500px]">
                <table className="w-full text-sm">
                  <thead className="bg-surface-soft/80 sticky top-0 z-10">
                    <tr className="text-left text-xs uppercase tracking-wider text-muted border-b border-hairline">
                      <th className="px-2 py-2.5 w-8"><span className="sr-only">Detail</span></th>
                      <th className="px-3 py-2.5 cursor-pointer select-none hover:text-ink" onClick={() => handleSort('created_at')}>
                        Waktu <SortIcon columnKey="created_at" sortConfig={sortConfig} />
                      </th>
                      <th className="px-3 py-2.5 cursor-pointer select-none hover:text-ink" onClick={() => handleSort('user_name')}>
                        User <SortIcon columnKey="user_name" sortConfig={sortConfig} />
                      </th>
                      <th className="px-3 py-2.5 cursor-pointer select-none hover:text-ink" onClick={() => handleSort('branch_code')}>
                        Cabang <SortIcon columnKey="branch_code" sortConfig={sortConfig} />
                      </th>
                      <th className="px-3 py-2.5">Pertanyaan</th>
                      <th className="px-3 py-2.5 cursor-pointer select-none hover:text-ink" onClick={() => handleSort('execution_time_ms')}>
                        Durasi <SortIcon columnKey="execution_time_ms" sortConfig={sortConfig} />
                      </th>
                      <th className="px-3 py-2.5 cursor-pointer select-none hover:text-ink" onClick={() => handleSort('status')}>
                        Status <SortIcon columnKey="status" sortConfig={sortConfig} />
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-hairline">
                    {logs.map((l) => (
                      <Fragment key={l.id}>
                        <motion.tr
                          initial={{ opacity: 0 }}
                          animate={{ opacity: 1 }}
                          className="hover:bg-surface-soft/40 transition-colors"
                        >
                          <td className="px-2 py-2.5 align-middle">
                            <button
                              onClick={() => setExpandedId(expandedId === l.id ? null : l.id)}
                              aria-label={expandedId === l.id ? 'Tutup detail log' : 'Lihat detail log'}
                              aria-expanded={expandedId === l.id}
                              className="p-1 text-muted hover:text-ink rounded-md transition-colors"
                            >
                              <ChevronDown size={14} className={`transition-transform ${expandedId === l.id ? 'rotate-180' : ''}`} />
                            </button>
                          </td>
                          <td className="px-3 py-2.5 whitespace-nowrap text-muted text-xs">{formatDate(l.created_at)}</td>
                          <td className="px-3 py-2.5 text-xs font-medium">{l.user_name || `#${l.user_id}` || '-'}</td>
                          <td className="px-3 py-2.5 font-mono text-xs">{l.branch_code}</td>
                          <td className="px-3 py-2.5 max-w-[280px]">
                            <div className="truncate text-xs" title={l.prompt_text || ''}>
                              {l.prompt_text || '-'}
                            </div>
                          </td>
                          <td className="px-3 py-2.5 whitespace-nowrap text-muted text-xs">
                            {l.execution_time_ms != null ? `${l.execution_time_ms} ms` : '-'}
                          </td>
                          <td className="px-3 py-2.5">{statusBadge(l.status)}</td>
                        </motion.tr>

                        {/* Expandable Detail */}
                        {expandedId === l.id && (
                          <tr className="bg-slate-50/80">
                            <td colSpan={7} className="px-4 py-3">
                              <div className="grid grid-cols-1 gap-2.5 text-xs">
                                <div>
                                  <span className="text-muted uppercase tracking-wide font-medium">Pertanyaan Pengguna</span>
                                  <p className="text-body whitespace-pre-wrap mt-0.5">{l.prompt_text || '-'}</p>
                                </div>
                                <div>
                                  <span className="text-muted uppercase tracking-wide font-medium">SQL yang Dihasilkan</span>
                                  <pre className="mt-0.5 bg-white border border-hairline rounded-md p-2.5 overflow-x-auto font-mono text-[11px] text-body whitespace-pre-wrap">
                                    {l.generated_sql || '-'}
                                  </pre>
                                </div>
                                <div>
                                  <span className="text-muted uppercase tracking-wide font-medium">Rencana JSON & Jejak Trace</span>
                                  <pre className="mt-0.5 bg-white border border-hairline rounded-md p-2.5 overflow-x-auto font-mono text-[11px] text-body max-h-40 overflow-y-auto">
                                    {prettyJson(l.ai_json_filter)}
                                  </pre>
                                </div>
                                {l.error_message && (
                                  <div>
                                    <span className="text-muted uppercase tracking-wide font-medium">Pesan Error / Alasan Penolakan</span>
                                    <p className="text-rose-600 mt-0.5 whitespace-pre-wrap font-medium">{l.error_message}</p>
                                  </div>
                                )}
                                <p className="text-muted text-[11px] pt-1">
                                  Diajukan oleh {l.user_name || (l.user_id ? `#${l.user_id}` : 'Anonim')} · Cabang {l.branch_code} · {l.execution_time_ms != null ? `${l.execution_time_ms} ms` : 'durasi -'} · {formatDate(l.created_at)}
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

          {/* Pagination */}
          {!loading && totalPages > 1 && (
            <PaginationBar page={page} totalPages={totalPages} onChange={(p) => { setPage(p); setLoading(true); }} totalItems={total} pageSize={PAGE_SIZE} />
          )}
        </div>
      )}

      {/* Modal Ubah Kuota */}
      {selectedBranchForQuota && (
        <BranchQuotaModal
          key={selectedBranchForQuota.branch_code}
          isOpen={!!selectedBranchForQuota}
          onClose={() => setSelectedBranchForQuota(null)}
          branch={selectedBranchForQuota}
          onSave={handleSaveQuota}
          isSaving={isSavingQuota}
        />
      )}
    </div>
  );
}