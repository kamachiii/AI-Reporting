import { useState, useEffect, useMemo } from 'react';
import { motion } from 'framer-motion';
import {
  Plus, CheckCircle, XCircle, Search, Loader2,
  Trash2, Wifi, X, Pencil, Database as DbIcon,
  Server,
  Check,
  RefreshCw} from 'lucide-react';
import toast from 'react-hot-toast';
import PaginationBar from './common/PaginationBar';
import EmptyState from './common/EmptyState';
import ConfirmationDialog from './common/ConfirmationDialog';
import SkeletonTable from './common/SkeletonTable';
import DbConnectionModal from './tenants/DbConnectionModal';
import { api } from '../../services/api';
import useDebounce from '../../hooks/useDebounce';
import useAdminShortcuts from '../../hooks/useAdminShortcuts';

const PAGE_SIZE = 10;

/**
 * Halaman "Database & Tenant" — dua sub-tab:
 *  1. Database  : CRUD registry db_connections (kredensial didaftarkan sekali)
 *  2. Koneksi   : relasi cabang ↔ database + status koneksi nyata
 */
export default function TenantsTab() {
  const [activeTab, setActiveTab] = useState('database');
  const [searchTerm, setSearchTerm] = useState('');
  const debouncedSearch = useDebounce(searchTerm, 300);

  // data registry
  const [connections, setConnections] = useState([]);
  // data tenant (relasi)
  const [tenants, setTenants] = useState([]);

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testingId, setTestingId] = useState(null);
  const [processingKey, setProcessingKey] = useState(null);
  const [confirmState, setConfirmState] = useState(null);


  // status koneksi NYATA milik DATABASE (registry): { "<id>": {status, message} }
  const [dbStatus, setDbStatus] = useState({});
  const [statusLoading, setStatusLoading] = useState(false);
  const REFRESH_MS = 45000;

  // modal
  const [showConnModal, setShowConnModal] = useState(false);      // hubungkan cabang
  const [showDbModal, setShowDbModal] = useState(false);          // daftarkan/edit database
  const [editingDb, setEditingDb] = useState(null);

  // pagination & sort
  const [dbPage, setDbPage] = useState(1);
  const [connPage, setConnPage] = useState(1);

  useEffect(() => { fetchData(); }, []);

  useAdminShortcuts({
    onEscape: () => {
      if (confirmState) setConfirmState(null);
      else if (showDbModal) setShowDbModal(false);
      else if (showConnModal) setShowConnModal(false);
    },
    isBusy: !!processingKey || !!testingId,
    searchInputId: 'tenant-search',
  });

  const fetchStatuses = async () => {
    // SATU request batch untuk semua database (backend paralel, timeout 4s)
    if (!connections.length) return;
    setStatusLoading(true);
    try {
      const result = await api.testAllDbConnections();
      setDbStatus(result || {});
    } catch {
      // diam: biarkan status lama bertahan
    } finally {
      setStatusLoading(false);
    }
  };

  const fetchData = async () => {
    setLoading(true);
    try {
      const [conns, tns] = await Promise.all([api.getDbConnections(), api.getTenants()]);
      setConnections(conns || []);
      setTenants(tns || []);
      // status awal semua 'checking' sampai batch selesai
      const initial = {};
      (conns || []).forEach(c => { initial[String(c.id)] = { status: 'checking', message: '' }; });
      setDbStatus(initial);
      api.testAllDbConnections().then(r => setDbStatus(r || {})).catch(() => {});
    } catch {
      toast.error('Gagal memuat data database');
    } finally {
      setLoading(false);
    }
  };


  const handleTestRegistry = async (conn) => {
    setTestingId(conn.id);
    try {
      const result = await api.testDbConnection(conn.id);
      result.status === 'connected'
        ? notifyOk(`Koneksi "${conn.name}" berhasil!`)
        : toast.error(`Gagal: ${result.message || ''}`);
    } catch {
      toast.error('Gagal menguji koneksi');
    } finally {
      setTestingId(null);
    }
  };
  const notifyOk = (m) => toast.success(m);

  // ---- CRUD registry ----
  const handleSaveDb = async ({ id, ...payload }) => {
    setSaving(true);
    try {
      if (id) {
        await api.updateDbConnection(id, payload);
        toast.success('Database berhasil diperbarui');
      } else {
        await api.createDbConnection(payload);
        toast.success('Database berhasil didaftarkan');
      }
      setShowDbModal(false);
      setEditingDb(null);
      await fetchData();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Gagal menyimpan database');
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteDb = (conn) => {
    setConfirmState({
      title: 'Hapus Database?',
      message: `"${conn.name}" akan dihapus dari registry. Cabang yang masih memakainya harus diputuskan dulu.`,
      onConfirm: async () => {
        setProcessingKey(`db-${conn.id}`);
        try {
          await api.deleteDbConnection(conn.id);
          toast.success('Database dihapus dari registry');
          setConfirmState(null);
          await fetchData();
        } catch (e) {
          toast.error(e.response?.data?.detail || 'Gagal menghapus database');
          setConfirmState(null);
        } finally {
          setProcessingKey(null);
        }
      },
    });
  };

  // ---- relasi ----
  const handleSaveConnect = async ({ branch_code, db_connection_id, isChange }) => {
    setSaving(true);
    try {
      if (isChange) {
        await api.updateTenantDb(branch_code, db_connection_id);
        toast.success('Database cabang berhasil diganti');
      } else {
        await api.createTenant({ branch_code, db_connection_id });
        toast.success('Database berhasil dihubungkan ke cabang');
      }
      setShowConnModal(false);
      await fetchData();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Gagal menghubungkan database');
    } finally {
      setSaving(false);
    }
  };

  const handleDisconnect = (t) => {
    setConfirmState({
      title: 'Putuskan Koneksi?',
      message: `Koneksi antara cabang ${t.branch_code} dan database "${t.db_name_label}" akan diputus. Data tidak hilang — bisa dihubungkan lagi kapan pun.`,
      onConfirm: async () => {
        setProcessingKey(t.branch_code);
        try {
          await api.deleteTenant(t.branch_code);
          toast.success(`Koneksi ${t.branch_code} diputus`);
          setConfirmState(null);
          await fetchData();
        } catch (e) {
          toast.error(e.response?.data?.detail || 'Gagal memutus koneksi');
          setConfirmState(null);
        } finally {
          setProcessingKey(null);
        }
      },
    });
  };

  // Auto-refresh status tiap 45 dtk — hanya saat tab browser terlihat (hemat resource)
  useEffect(() => {
    const id = setInterval(() => {
      if (document.visibilityState === 'visible') fetchStatuses();
    }, REFRESH_MS);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connections.length]);

  // ---- filter & pagination ----
  const filteredDbs = useMemo(() => {
    if (!debouncedSearch) return connections;
    const q = debouncedSearch.toLowerCase();
    return connections.filter(c =>
      c.name.toLowerCase().includes(q) ||
      (c.db_host || '').toLowerCase().includes(q) ||
      (c.db_name || '').toLowerCase().includes(q));
  }, [connections, debouncedSearch]);

  const dbTotalPages = Math.max(1, Math.ceil(filteredDbs.length / PAGE_SIZE));
  useEffect(() => { if (dbPage > dbTotalPages) setDbPage(dbTotalPages); }, [dbPage, dbTotalPages]);
  const paginatedDbs = useMemo(
    () => filteredDbs.slice((dbPage - 1) * PAGE_SIZE, dbPage * PAGE_SIZE),
    [filteredDbs, dbPage]);

  const usedByMap = useMemo(() => {
    const m = {};
    tenants.forEach(t => { m[t.db_connection_id] = (m[t.db_connection_id] || 0) + 1; });
    return m;
  }, [tenants]);

  const filteredConns = useMemo(() => {
    if (!debouncedSearch) return tenants;
    const q = debouncedSearch.toLowerCase();
    return tenants.filter(t =>
      t.branch_code.toLowerCase().includes(q) ||
      (t.db_name_label || '').toLowerCase().includes(q));
  }, [tenants, debouncedSearch]);

  const connTotalPages = Math.max(1, Math.ceil(filteredConns.length / PAGE_SIZE));
  useEffect(() => { if (connPage > connTotalPages) setConnPage(connTotalPages); }, [connPage, connTotalPages]);
  const paginatedConns = useMemo(
    () => filteredConns.slice((connPage - 1) * PAGE_SIZE, connPage * PAGE_SIZE),
    [filteredConns, connPage]);


  const openConnectModal = async () => {
    setShowConnModal(true);
  };

  if (loading) return <SkeletonTable rows={5} columns={4} />;

  return (
    <div className="space-y-6">
      {/* Toolbar: search kiri - switch tengah-kanan - aksi kanan */}
      <div className="flex items-center gap-4 flex-wrap">
        <div className="relative w-full sm:w-64">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" size={16} />
          <input
            id="tenant-search"
            type="text"
            placeholder="Cari nama, host, atau cabang...  ( / )"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full pl-9 pr-8 py-2 border border-hairline rounded-md bg-canvas text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
          />
          {searchTerm && (
            <button type="button" onClick={() => setSearchTerm('')} aria-label="Bersihkan pencarian"
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted hover:text-ink">
              <X size={14} />
            </button>
          )}
        </div>

        <div className="ml-auto flex items-center gap-3">
                  <button onClick={fetchStatuses} disabled={statusLoading}
                    title="Refresh status koneksi" aria-label="Refresh status koneksi"
                    className="p-2 border border-hairline rounded-md text-muted hover:text-primary hover:border-primary/30 disabled:opacity-50">
                    <RefreshCw size={14} className={statusLoading ? 'animate-spin' : ''} />
                  </button>
          <div className="flex gap-2 border border-hairline rounded-md p-1 bg-surface-soft">
            <button onClick={() => setActiveTab('database')}
              className={`px-4 py-1.5 text-xs font-medium rounded transition-colors ${activeTab === 'database' ? 'bg-primary text-white shadow-sm' : 'text-muted hover:text-ink'}`}>
              Database
            </button>
            <button onClick={() => setActiveTab('koneksi')}
              className={`px-4 py-1.5 text-xs font-medium rounded transition-colors ${activeTab === 'koneksi' ? 'bg-primary text-white shadow-sm' : 'text-muted hover:text-ink'}`}>
              Koneksi
            </button>
          </div>

          {activeTab === 'database' ? (
            <>
              <button onClick={() => { setEditingDb(null); setShowDbModal(true); }}
                className="flex items-center gap-2 px-3 py-1.5 bg-primary text-white rounded-md text-xs hover:bg-primary-active whitespace-nowrap">
                <Plus size={14} /> Daftarkan Database
              </button>
            </>
          ) : (
            <button onClick={openConnectModal}
              className="flex items-center gap-2 px-3 py-1.5 bg-primary text-white rounded-md text-xs hover:bg-primary-active whitespace-nowrap">
              <Plus size={14} /> Hubungkan
            </button>
          )}
        </div>
      </div>

      {/* ================= SUB-TAB DATABASE ================= */}
      {activeTab === 'database' && (
        filteredDbs.length === 0 ? (
          <EmptyState variant="plug"
            title="Belum ada database terdaftar"
            description='Klik "Daftarkan Database" di kanan atas untuk mulai.' />
        ) : (
          <div className="bg-white rounded-xl border border-hairline overflow-hidden shadow-sm">
            <div className="overflow-auto max-h-[420px]">
              <table className="w-full text-left">
                <thead className="bg-surface-soft text-sm text-muted sticky top-0 z-10">
                  <tr>
                    <th className="p-3">Nama</th>
                    <th className="p-3">Host</th>
                    <th className="p-3">Database</th>
                    <th className="p-3 w-24 text-center">Dipakai</th>
                    <th className="p-3 w-20">Status</th>
                    <th className="p-3 w-28">Koneksi</th>
                    <th className="p-3 w-0 text-center">Aksi</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-hairline">
                  {paginatedDbs.map((c, idx) => (
                    <motion.tr key={c.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }}
                      transition={{ delay: idx * 0.03 }} className="hover:bg-surface-soft/50">
                      <td className="p-3 text-sm font-medium">{c.name}</td>
                      <td className="p-3 text-sm text-muted">{c.db_host}:{c.db_port}</td>
                      <td className="p-3 text-sm text-body">{c.db_name}</td>
                      <td className="p-3 text-center text-sm text-muted">
                        {(usedByMap[c.id] ?? c.used_by ?? 0)} cabang
                      </td>
                      <td className="p-3">
                        {c.is_active ? (
                          <span className="inline-flex items-center gap-1.5 text-success text-xs font-medium">
                            <span className="w-1.5 h-1.5 rounded-full bg-success" /> Aktif
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1.5 text-error text-xs font-medium">
                            <span className="w-1.5 h-1.5 rounded-full bg-error opacity-70" /> Nonaktif
                          </span>
                        )}
                      </td>
                      {(() => {
                        const st = dbStatus[String(c.id)];
                        return (
                          <td className="p-3" title={st?.message || ''}>
                            {!st || st.status === 'checking' ? (
                              <span className="inline-flex items-center text-muted text-xs">
                                <Loader2 size={12} className="mr-1.5 animate-spin" /> Menguji…
                              </span>
                            ) : st.status === 'connected' ? (
                              <span className="inline-flex items-center gap-1.5 text-success text-xs font-medium">
                                <CheckCircle size={13} /> Connected
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1.5 text-error text-xs font-medium">
                                <XCircle size={13} /> Disconnected
                              </span>
                            )}
                          </td>
                        );
                      })()}
                      <td className="p-3">
                        <div className="flex justify-end gap-0.5">
                          <button onClick={() => handleTestRegistry(c)} disabled={testingId === c.id}
                            title="Test Koneksi" aria-label={`Test koneksi ${c.name}`}
                            className="p-1.5 text-muted hover:text-primary hover:bg-surface-soft rounded-md disabled:opacity-50">
                            {testingId === c.id ? <Loader2 size={15} className="animate-spin" /> : <Wifi size={15} />}
                          </button>
                          <button onClick={() => { setEditingDb(c); setShowDbModal(true); }}
                            title="Edit" aria-label={`Edit ${c.name}`}
                            className="p-1.5 text-muted hover:text-ink hover:bg-surface-soft rounded-md">
                            <Pencil size={15} />
                          </button>
                          <button onClick={() => handleDeleteDb(c)} disabled={processingKey === `db-${c.id}`}
                            title="Hapus" aria-label={`Hapus ${c.name}`}
                            className="p-1.5 text-muted hover:text-error hover:bg-error/5 rounded-md disabled:opacity-50">
                            {processingKey === `db-${c.id}` ? <Loader2 size={15} className="animate-spin" /> : <Trash2 size={15} />}
                          </button>
                        </div>
                      </td>
                    </motion.tr>
                  ))}
                </tbody>
              </table>
            </div>
            <PaginationBar page={dbPage} totalPages={dbTotalPages} onChange={setDbPage}
              totalItems={filteredDbs.length} pageSize={PAGE_SIZE} />
          </div>
        )
      )}

      {/* ================= SUB-TAB KONEKSI ================= */}
      {activeTab === 'koneksi' && (
        filteredConns.length === 0 ? (
          <EmptyState variant="plug"
            title="Belum ada koneksi"
            description='Klik "Hubungkan" di kanan atas untuk menghubungkan cabang ke database.' />
        ) : (
          <div className="bg-white rounded-xl border border-hairline overflow-hidden shadow-sm">
            <div className="overflow-auto max-h-[420px]">
              <table className="w-full text-left">
                <thead className="bg-surface-soft text-sm text-muted sticky top-0 z-10">
                  <tr>
                    <th className="p-3">Cabang</th>
                    <th className="p-3">Database</th>
                    <th className="p-3">Lokasi</th>
                    <th className="p-3 w-32">Status</th>
                    <th className="p-3 w-0 text-center">Aksi</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-hairline">
                  {paginatedConns.map((t, idx) => (
                      <motion.tr key={t.branch_code} initial={{ opacity: 0 }} animate={{ opacity: 1 }}
                        transition={{ delay: idx * 0.03 }} className="hover:bg-surface-soft/50">
                        <td className="p-3 text-sm font-medium">{t.branch_code}</td>
                        <td className="p-3 text-sm text-body">{t.db_name_label}</td>
                        <td className="p-3 text-sm text-muted">{t.db_host}:{t.db_port}</td>
                        <td className="p-3">
                          <div className="flex justify-end gap-0.5">
                            <button onClick={() => handleDisconnect(t)} disabled={processingKey === t.branch_code}
                              title="Putuskan" aria-label={`Putuskan ${t.branch_code}`}
                              className="p-1.5 text-muted hover:text-error hover:bg-error/5 rounded-md disabled:opacity-50">
                              {processingKey === t.branch_code ? <Loader2 size={15} className="animate-spin" /> : <Trash2 size={15} />}
                            </button>
                          </div>
                        </td>
                      </motion.tr>
                  ))}
                </tbody>
              </table>
            </div>
            <PaginationBar page={connPage} totalPages={connTotalPages} onChange={setConnPage}
              totalItems={filteredConns.length} pageSize={PAGE_SIZE} />
          </div>
        )
      )}

      {/* ===== MODALS ===== */}
      {showConnModal && (
        <HubungkanPicker
          onClose={() => setShowConnModal(false)}
          onSaved={handleSaveConnect}
          existingTenants={tenants}
        />
      )}

      {showDbModal && (
        <DbConnectionModal
          key={editingDb?.id || 'new'}
          isOpen
          onClose={() => { setShowDbModal(false); setEditingDb(null); }}
          onSave={handleSaveDb}
          editing={editingDb}
          isSaving={saving}
        />
      )}

      {confirmState && (
        <ConfirmationDialog
          isOpen
          title={confirmState.title}
          message={confirmState.message}
          onConfirm={confirmState.onConfirm}
          onCancel={() => setConfirmState(null)}
        />
      )}
    </div>
  );
}

/* Picker sederhana: pilih cabang (yang belum terhubung) + database, lalu hubungkan.
   Menggantikan alur lama yang connect hanya dari halaman cabang. */
function HubungkanPicker({ onClose, onSaved, existingTenants }) {
  const [branches, setBranches] = useState([]);
  const [loadingB, setLoadingB] = useState(true);
  const [branchCode, setBranchCode] = useState('');
  const [selectedId, setSelectedId] = useState(null);
  const [connections, setConnections] = useState([]);
  const [loadingC, setLoadingC] = useState(true);
  const [page, setPage] = useState(1);
  const [saving, setSaving] = useState(false);

  const CARD_PAGE = 6;

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      import('../../services/api').then(m => m.api.getBranches()),
      import('../../services/api').then(m => m.api.getDbConnections()),
    ]).then(([brs, conns]) => {
      if (cancelled) return;
      const connected = new Set(existingTenants.map(t => t.branch_code));
      setBranches(brs.filter(b => !connected.has(b.code)));
      setConnections(conns.filter(c => c.is_active));
    }).catch(() => {}).finally(() => {
      if (!cancelled) { setLoadingB(false); setLoadingC(false); }
    });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const totalPages = Math.max(1, Math.ceil(connections.length / CARD_PAGE));

  const submit = async () => {
    if (!branchCode || !selectedId) return;
    setSaving(true);
    try {
      await onSaved({ branch_code: branchCode, db_connection_id: Number(selectedId), isChange: false });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <motion.div initial={{ scale: .95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
        className="bg-white rounded-xl p-6 max-w-lg w-full shadow-xl border border-hairline relative">
        <button onClick={onClose} aria-label="Tutup"
          className="absolute right-4 top-4 text-muted hover:text-ink"><X size={20} /></button>

        <div className="flex items-center gap-3 mb-4">
          <span className="w-9 h-9 rounded-lg bg-violet-500/10 border border-violet-500/30 text-violet-500 flex items-center justify-center shrink-0">
            <DbIcon size={18} />
          </span>
          <h3 className="font-serif text-lg text-ink">Hubungkan Cabang ke Database</h3>
        </div>

        {/* pilih cabang */}
        <label className="block text-sm font-medium text-ink mb-1">Cabang (belum terhubung)</label>
        <select value={branchCode} onChange={(e) => setBranchCode(e.target.value)}
          className="w-full px-3 py-2 border border-hairline rounded-md bg-canvas text-sm mb-4 focus:ring-2 focus:ring-primary/30">
          <option value="" disabled>— Pilih cabang —</option>
          {loadingB && <option>Memuat…</option>}
          {!loadingB && branches.length === 0 && <option value="">Semua cabang sudah terhubung ✓</option>}
          {branches.map(b => <option key={b.code} value={b.code}>{b.code} — {b.name}</option>)}
        </select>

        {/* pilih database: grid kartu + paginasi */}
        <label className="block text-sm font-medium text-ink mb-1">Pilih Database</label>
        {loadingC ? (
          <div className="py-8 text-center text-sm text-muted"><Loader2 className="animate-spin inline mr-2" size={16} />Memuat…</div>
        ) : connections.length === 0 ? (
          <p className="text-sm text-muted italic py-6 text-center">Belum ada database terdaftar. Daftarkan dulu di sub-tab Database.</p>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-2 min-h-[264px] content-start mt-1 max-h-[300px] overflow-y-auto">
              {connections.slice((page - 1) * CARD_PAGE, page * CARD_PAGE).map((c) => {
                const active = c.id === Number(selectedId);
                return (
                  <button key={c.id} type="button" onClick={() => setSelectedId(c.id)}
                    className={`relative flex flex-col items-start gap-1.5 p-3 rounded-lg border text-left transition-all ${
                      active ? 'border-primary bg-primary/5 ring-1 ring-primary/40'
                             : 'border-hairline hover:border-muted/40 hover:bg-surface-soft'}`}>
                    <span className={`w-9 h-9 rounded-lg flex items-center justify-center border ${
                      c.is_active ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-600'
                                  : 'bg-slate-400/10 border-slate-400/30 text-slate-400'}`}>
                      <Server size={15} />
                    </span>
                    <span className="block text-sm font-medium text-ink truncate w-full">{c.name}</span>
                    <span className="block text-[11px] text-muted truncate w-full">{c.db_name}</span>
                    {active && (
                      <span className="absolute top-2 right-2 w-5 h-5 rounded-full bg-primary text-white flex items-center justify-center">
                        <Check size={12} strokeWidth={3} />
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
            {connections.length > CARD_PAGE && (
              <div className="flex items-center justify-between mt-2">
                <span className="text-[10px] text-muted">
                  {(page - 1) * CARD_PAGE + 1}–{Math.min(page * CARD_PAGE, connections.length)} dari {connections.length}
                </span>
                <span className="flex gap-1.5">
                  <button type="button" onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1}
                    className="px-2 py-1 border border-hairline rounded text-xs hover:bg-surface-soft disabled:opacity-40">‹</button>
                  <span className="px-2 py-1 text-xs text-muted">{page} / {totalPages}</span>
                  <button type="button" onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page >= totalPages}
                    className="px-2 py-1 border border-hairline rounded text-xs hover:bg-surface-soft disabled:opacity-40">›</button>
                </span>
              </div>
            )}
          </>
        )}

        <div className="flex justify-end gap-2 mt-5 pt-4 border-t border-hairline">
          <button type="button" onClick={onClose}
            className="px-4 py-2 border border-hairline rounded-md text-sm hover:bg-surface-soft">Batal</button>
          <button type="button" onClick={submit} disabled={!branchCode || !selectedId || saving}
            className="px-4 py-2 bg-primary text-white rounded-md text-sm hover:bg-primary-active disabled:opacity-50 flex items-center gap-2">
            {saving && <Loader2 size={14} className="animate-spin" />} Hubungkan
          </button>
        </div>
      </motion.div>
    </div>
  );
}
