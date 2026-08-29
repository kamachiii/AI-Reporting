import { useState, useEffect, useMemo } from 'react';
import { motion } from 'framer-motion';
import {
  Plus, CheckCircle, XCircle, Search, Loader2,
  Trash2, Wifi, X, Pencil, RefreshCw} from 'lucide-react';
import { notify } from '../../utils/notification';
import PaginationBar from './common/PaginationBar';
import EmptyState from './common/EmptyState';
import ConfirmationDialog from './common/ConfirmationDialog';
import SkeletonTable from './common/SkeletonTable';
import DbConnectionModal from './tenants/DbConnectionModal';
import ConnectDbModal from './tenants/ConnectDbModal';
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
  // daftar cabang (untuk picker hubungkan: hanya yang belum terhubung)
  const [branches, setBranches] = useState([]);

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testingId, setTestingId] = useState(null);
  const [processingKey, setProcessingKey] = useState(null);
  const [introspecting, setIntrospecting] = useState(null);
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
      const [conns, tns, brs] = await Promise.all([
        api.getDbConnections(), api.getTenants(), api.getBranches(),
      ]);
      setConnections(conns || []);
      setTenants(tns || []);
      setBranches(brs || []);
      // status awal semua 'checking' sampai batch selesai
      const initial = {};
      (conns || []).forEach(c => { initial[String(c.id)] = { status: 'checking', message: '' }; });
      setDbStatus(initial);
      api.testAllDbConnections().then(r => setDbStatus(r || {})).catch(() => {});
    } catch {
      notify.error('Gagal memuat data database');
    } finally {
      setLoading(false);
    }
  };


  const handleTestRegistry = async (conn) => {
    setTestingId(conn.id);
    try {
      const result = await api.testDbConnection(conn.id);
      result.status === 'connected'
        ? notify.success(`Koneksi "${conn.name}" berhasil!`)
        : notify.error(`Gagal: ${result.message || ''}`);
    } catch {
      notify.error('Gagal menguji koneksi');
    } finally {
      setTestingId(null);
    }
  };

  // ---- CRUD registry ----
  const handleSaveDb = async ({ id, ...payload }) => {
    setSaving(true);
    try {
      if (id) {
        await api.updateDbConnection(id, payload);
        notify.success('Database berhasil diperbarui');
      } else {
        await api.createDbConnection(payload);
        notify.success('Database berhasil didaftarkan');
      }
      setShowDbModal(false);
      setEditingDb(null);
      await fetchData();
    } catch (e) {
      notify.error(e.response?.data?.detail || 'Gagal menyimpan database');
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
          notify.success('Database dihapus dari registry');
          setConfirmState(null);
          await fetchData();
        } catch (e) {
          notify.error(e.response?.data?.detail || 'Gagal menghapus database');
          setConfirmState(null);
        } finally {
          setProcessingKey(null);
        }
      },
    });
  };

  // ---- relasi ----
  const handleRefreshSchema = async (t) => {
    setIntrospecting(t.branch_code);
    try {
      const r = await api.refreshTenantSchema(t.branch_code);
      notify.success(r.message || `Skema ${t.branch_code} diperbarui`);
    } catch (e) {
      notify.error(e.response?.data?.detail || 'Gagal memperbarui skema');
    } finally {
      setIntrospecting(null);
    }
  };

  const handleSaveConnect = async ({ branch_code, db_connection_id, isChange }) => {
    setSaving(true);
    try {
      if (isChange) {
        await api.updateTenantDb(branch_code, db_connection_id);
        notify.success('Database cabang berhasil diganti');
      } else {
        await api.createTenant({ branch_code, db_connection_id });
        notify.success('Database berhasil dihubungkan ke cabang');
      }
      setShowConnModal(false);
      await fetchData();
    } catch (e) {
      notify.error(e.response?.data?.detail || 'Gagal menghubungkan database');
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
          notify.success(`Koneksi ${t.branch_code} diputus`);
          setConfirmState(null);
          await fetchData();
        } catch (e) {
          notify.error(e.response?.data?.detail || 'Gagal memutus koneksi');
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
                          {(() => {
                            const st = dbStatus[String(t.db_connection_id)];
                            if (!st || st.status === 'checking') {
                              return (
                                <span className="inline-flex items-center text-muted text-xs">
                                  <Loader2 size={12} className="mr-1.5 animate-spin" /> Menguji…
                                </span>
                              );
                            }
                            return st.status === 'connected' ? (
                              <span className="inline-flex items-center gap-1.5 text-success text-xs font-medium">
                                <CheckCircle size={13} /> Connected
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1.5 text-error text-xs font-medium">
                                <XCircle size={13} /> Disconnected
                              </span>
                            );
                          })()}
                        </td>
                        <td className="p-3">
                          <div className="flex justify-end gap-0.5">
                            <button onClick={() => handleRefreshSchema(t)} disabled={introspecting === t.branch_code}
                              title="Perbarui Skema" aria-label={`Perbarui skema ${t.branch_code}`}
                              className="p-1.5 text-muted hover:text-primary hover:bg-surface-soft rounded-md disabled:opacity-50">
                              {introspecting === t.branch_code ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}
                            </button>
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
        <ConnectDbModal
          key="connect-picker"
          isOpen
          onClose={() => setShowConnModal(false)}
          onSaved={handleSaveConnect}
          branches={branches.filter((b) => !tenants.some((t) => t.branch_code === b.code))}
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
