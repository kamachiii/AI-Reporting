import { useState, useEffect } from 'react';
import { Plus, Search, X, RefreshCw } from 'lucide-react';
import { notify } from '../../utils/notification';
import ConfirmationDialog from './common/ConfirmationDialog';
import SkeletonTable from './common/SkeletonTable';
import DbConnectionModal from './tenants/DbConnectionModal';
import ConnectDbModal from './tenants/ConnectDbModal';
import DatabaseRegistryTable from './tenants/DatabaseRegistryTable';
import TenantConnectionsTable from './tenants/TenantConnectionsTable';
import { api } from '../../services/api';
import useDebounce from '../../hooks/useDebounce';
import useAdminShortcuts from '../../hooks/useAdminShortcuts';

const REFRESH_MS = 45000;

/**
 * Halaman "Database & Tenant" — dua sub-tab:
 *  1. Database  : CRUD registry db_connections (kredensial didaftarkan sekali)
 *  2. Koneksi   : relasi cabang ↔ database + status koneksi nyata
 *
 * Orkestrator tipis: memegang state + aksi CRUD/test; render tabel
 * dipindah ke tenants/DatabaseRegistryTable.jsx dan tenants/TenantConnectionsTable.jsx.
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

  // modal
  const [showConnModal, setShowConnModal] = useState(false);      // hubungkan cabang
  const [showDbModal, setShowDbModal] = useState(false);          // daftarkan/edit database
  const [editingDb, setEditingDb] = useState(null);

  // pagination
  const [dbPage, setDbPage] = useState(1);
  const [connPage, setConnPage] = useState(1);

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

  useEffect(() => { fetchData(); }, []);

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

  const openConnectModal = () => setShowConnModal(true);

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
            <button onClick={() => { setEditingDb(null); setShowDbModal(true); }}
              className="flex items-center gap-2 px-3 py-1.5 bg-primary text-white rounded-md text-xs hover:bg-primary-active whitespace-nowrap">
              <Plus size={14} /> Daftarkan Database
            </button>
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
        <DatabaseRegistryTable
          connections={connections}
          tenants={tenants}
          debouncedSearch={debouncedSearch}
          dbPage={dbPage}
          setDbPage={setDbPage}
          dbStatus={dbStatus}
          testingId={testingId}
          processingKey={processingKey}
          onTest={handleTestRegistry}
          onEdit={(c) => { setEditingDb(c); setShowDbModal(true); }}
          onDelete={handleDeleteDb}
        />
      )}

      {/* ================= SUB-TAB KONEKSI ================= */}
      {activeTab === 'koneksi' && (
        <TenantConnectionsTable
          tenants={tenants}
          debouncedSearch={debouncedSearch}
          connPage={connPage}
          setConnPage={setConnPage}
          dbStatus={dbStatus}
          introspecting={introspecting}
          processingKey={processingKey}
          onRefreshSchema={handleRefreshSchema}
          onDisconnect={handleDisconnect}
        />
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