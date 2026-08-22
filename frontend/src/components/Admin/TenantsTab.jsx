import { useState, useEffect, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { api } from '../../services/api';
import { 
  Plus, CheckCircle, XCircle, Box, X, Search, 
  Loader2, AlertTriangle, ChevronLeft, ChevronRight, 
  Eye, EyeOff, Wifi, RefreshCw 
} from 'lucide-react';
import toast from 'react-hot-toast';

const PAGE_SIZE = 10;

export default function TenantsTab() {
  const [tenants, setTenants] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('All');
  const [page, setPage] = useState(1);
  const [connectionStatus, setConnectionStatus] = useState({});
  const [showAddModal, setShowAddModal] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [processingCode, setProcessingCode] = useState(null);
  const [confirmState, setConfirmState] = useState(null);

  // Form state for Add Tenant
  const [form, setForm] = useState({
    branch_code: '',
    db_host: '',
    db_port: '5432',
    db_name: '',
    db_username: '',
    db_password: '',
  });

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    setLoading(true);
    try {
      const data = await api.getTenants();
      setTenants(data || []);
      await testAllConnections(data || []);
    } catch (e) {
      toast.error('Gagal memuat data tenant');
    } finally {
      setLoading(false);
    }
  };

  const testAllConnections = async (tenantList) => {
    const statuses = {};
    await Promise.all(tenantList.map(async (t) => {
      try {
        const result = await api.testTenantConnection(t.branch_code);
        statuses[t.branch_code] = result.status;
      } catch (e) {
        statuses[t.branch_code] = 'disconnected';
      }
    }));
    setConnectionStatus(statuses);
  };

  const handleTestSingle = async (branch_code) => {
    setConnectionStatus(prev => ({ ...prev, [branch_code]: 'loading' }));
    try {
      const result = await api.testTenantConnection(branch_code);
      setConnectionStatus(prev => ({ ...prev, [branch_code]: result.status }));
      if (result.status === 'connected') toast.success(`Koneksi ke ${branch_code} berhasil!`);
      else toast.error(`Koneksi gagal: ${result.message || ''}`);
    } catch (e) {
      setConnectionStatus(prev => ({ ...prev, [branch_code]: 'disconnected' }));
      toast.error('Gagal melakukan test koneksi');
    }
  };

  const handleAddTenant = async (e) => {
    e.preventDefault();
    try {
      await api.createTenant(form);
      toast.success('Tenant berhasil ditambahkan!');
      setShowAddModal(false);
      setForm({ branch_code: '', db_host: '', db_port: '5432', db_name: '', db_username: '', db_password: '' });
      await fetchData();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Gagal menambahkan tenant');
    }
  };

  // --- DELETE LOGIC ---
  const handleDeleteTenant = (branch_code) => {
    setConfirmState({
      title: 'Hapus Tenant?',
      message: `Konfigurasi database untuk cabang ${branch_code} akan dihapus permanen. Tindakan ini tidak bisa dibatalkan.`,
      danger: true,
      onConfirm: async () => {
        setProcessingCode(branch_code);
        try {
          // Pastikan ada endpoint DELETE /admin/tenants/{branch_code} di backend
          await api.deleteTenant(branch_code); 
          toast.success('Tenant berhasil dihapus');
          await fetchData();
        } catch (e) {
          toast.error('Gagal menghapus tenant');
        } finally {
          setProcessingCode(null);
          setConfirmState(null);
        }
      },
    });
  };

  // --- FILTER & PAGINATION ---
  const filteredTenants = useMemo(() => {
    let data = tenants;
    if (searchTerm) {
      const lower = searchTerm.toLowerCase();
      data = data.filter(t => 
        (t.branch_code || '').toLowerCase().includes(lower) ||
        (t.db_host || '').toLowerCase().includes(lower) ||
        (t.db_name || '').toLowerCase().includes(lower)
      );
    }
    if (statusFilter !== 'All') {
      data = data.filter(t => connectionStatus[t.branch_code] === statusFilter.toLowerCase());
    }
    return data;
  }, [tenants, searchTerm, statusFilter, connectionStatus]);

  const totalPages = Math.max(1, Math.ceil(filteredTenants.length / PAGE_SIZE));
  const paginatedTenants = useMemo(() => {
    const start = (page - 1) * PAGE_SIZE;
    return filteredTenants.slice(start, start + PAGE_SIZE);
  }, [filteredTenants, page]);

  // Reset page ketika search/filter berubah
  useEffect(() => setPage(1), [searchTerm, statusFilter]);
  // Clamp page jika halaman saat ini melebihi total
  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  // --- Skeleton Loader ---
  const SkeletonLoader = () => (
    <div className="bg-white rounded-xl border border-hairline overflow-hidden shadow-sm p-4 space-y-3 animate-pulse">
      <div className="h-8 bg-surface-soft rounded w-1/4 mb-4" />
      {[...Array(4)].map((_, i) => (
        <div key={i} className="flex gap-4">
          <div className="h-6 bg-surface-soft rounded w-1/6" />
          <div className="h-6 bg-surface-soft rounded w-1/4" />
          <div className="h-6 bg-surface-soft rounded w-1/4" />
          <div className="h-6 bg-surface-soft rounded w-1/6" />
        </div>
      ))}
    </div>
  );

  if (loading) return <SkeletonLoader />;

  return (
    <div className="space-y-6">
      {/* Header & Search & Filter */}
      <div className="flex flex-col md:flex-row justify-between items-center gap-4 flex-wrap">
        <div className="relative flex-1 max-w-sm w-full">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" size={16} />
          <input
            type="text"
            placeholder="Cari kode cabang atau host..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full pl-9 pr-8 py-2 border border-hairline rounded-md bg-canvas text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
          />
          {searchTerm && (
            <button
              type="button"
              onClick={() => setSearchTerm('')}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted hover:text-ink"
            >
              <X size={14} />
            </button>
          )}
        </div>
        
        <div className="flex items-center gap-3 w-full md:w-auto">
          {/* Segmented Control Filter Status */}
          <div className="flex gap-1 border border-hairline rounded-md p-1 bg-surface-soft">
            {['All', 'Connected', 'Disconnected'].map((status) => (
              <button
                key={status}
                onClick={() => setStatusFilter(status)}
                className={`px-3 py-1 text-xs font-medium rounded transition-colors ${
                  statusFilter === status
                    ? 'bg-primary text-white shadow-sm'
                    : 'text-muted hover:text-ink'
                }`}
              >
                {status}
              </button>
            ))}
          </div>

          <button
            onClick={() => setShowAddModal(true)}
            className="flex items-center gap-2 px-3 py-1.5 bg-primary text-white rounded-md text-xs hover:bg-primary-active whitespace-nowrap"
          >
            <Plus size={14} /> Tambah Tenant
          </button>
        </div>
      </div>

      {/* Table */}
      {filteredTenants.length === 0 ? (
        <div className="bg-white rounded-xl border border-hairline p-10 flex flex-col items-center justify-center text-center text-muted">
          <Box className="w-12 h-12 mb-3 text-hairline" />
          <p className="font-medium text-ink">
            {tenants.length === 0 ? 'Belum ada tenant terdaftar' : 'Tidak ada hasil pencarian'}
          </p>
          <p className="text-sm mt-1">
            {tenants.length === 0 ? 'Klik tombol "Tambah Tenant" untuk mengkonfigurasi database cabang.' : 'Coba gunakan kata kunci lain.'}
          </p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-hairline overflow-hidden shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead className="bg-surface-soft text-sm text-muted">
                <tr>
                  <th className="p-3 w-24">Kode Cabang</th>
                  <th className="p-3 w-32">Status Koneksi</th>
                  <th className="p-3">Host / Port</th>
                  <th className="p-3 w-32">Aksi</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-hairline">
                {paginatedTenants.map((t, idx) => {
                  const status = connectionStatus[t.branch_code] || 'loading';
                  const isProcessing = processingCode === t.branch_code;
                  return (
                    <motion.tr
                      key={t.branch_code}
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: Math.min(idx * 0.03, 0.3) }}
                      className="hover:bg-surface-soft/50 transition-colors"
                    >
                      <td className="p-3 font-medium text-sm">{t.branch_code}</td>
                      <td className="p-3">
                        {status === 'loading' ? (
                          <span className="text-muted text-xs animate-pulse">Loading...</span>
                        ) : status === 'connected' ? (
                          <span className="inline-flex items-center text-success text-xs">
                            <CheckCircle size={14} className="mr-1" /> Connected
                          </span>
                        ) : (
                          <span className="inline-flex items-center text-error text-xs">
                            <XCircle size={14} className="mr-1" /> Disconnected
                          </span>
                        )}
                      </td>
                      <td className="p-3 text-sm text-body">{t.db_host}:{t.db_port}</td>
                      <td className="p-3 flex gap-2">
                        <button
                          onClick={() => handleTestSingle(t.branch_code)}
                          disabled={status === 'loading'}
                          className="text-muted hover:text-primary transition-colors disabled:opacity-50"
                          title="Test Koneksi"
                        >
                          <Wifi size={14} />
                        </button>
                        <button
                          onClick={() => handleDeleteTenant(t.branch_code)}
                          disabled={isProcessing}
                          className="text-muted hover:text-error transition-colors disabled:opacity-50"
                        >
                          {isProcessing ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                        </button>
                      </td>
                    </motion.tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <PaginationBar
            page={page}
            totalPages={totalPages}
            onChange={setPage}
            totalItems={filteredTenants.length}
            pageSize={PAGE_SIZE}
          />
        </div>
      )}

      {/* ============== CONFIRM DELETE DIALOG ============== */}
      <AnimatePresence>
        {confirmState && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60] p-4"
            onClick={(e) => { if (e.target === e.currentTarget && !processingCode) setConfirmState(null); }}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              transition={{ type: 'spring', damping: 20, stiffness: 300 }}
              className="bg-white rounded-xl p-6 max-w-sm w-full shadow-xl border border-hairline"
            >
              <div className="flex items-start gap-3 mb-4">
                <AlertTriangle size={18} className="text-error mt-0.5" />
                <div>
                  <h3 className="font-serif text-base text-ink">{confirmState.title}</h3>
                  <p className="text-sm text-muted mt-1">{confirmState.message}</p>
                </div>
              </div>
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setConfirmState(null)}
                  disabled={!!processingCode}
                  className="px-4 py-2 border border-hairline rounded-md text-sm hover:bg-surface-soft disabled:opacity-50"
                >
                  Batal
                </button>
                <button
                  type="button"
                  onClick={confirmState.onConfirm}
                  disabled={!!processingCode}
                  className="flex items-center gap-2 px-4 py-2 bg-error text-white rounded-md text-sm hover:opacity-90 disabled:opacity-60"
                >
                  {processingCode && <Loader2 size={14} className="animate-spin" />}
                  Hapus
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ============== MODAL TAMBAH TENANT ============== */}
      <AnimatePresence>
        {showAddModal && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
            onClick={(e) => { if (e.target === e.currentTarget) setShowAddModal(false); }}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              transition={{ type: 'spring', damping: 20, stiffness: 300 }}
              className="bg-white rounded-xl p-6 max-w-lg w-full shadow-xl border border-hairline relative"
            >
              <button onClick={() => setShowAddModal(false)} className="absolute right-4 top-4 text-muted hover:text-ink">
                <X size={20} />
              </button>
              <h3 className="font-serif text-lg text-ink mb-4">Tambah Tenant Baru</h3>
              <form onSubmit={handleAddTenant} className="space-y-4">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-sm font-medium text-ink mb-1">Kode Cabang</label>
                    <input
                      required
                      value={form.branch_code}
                      onChange={(e) => setForm({ ...form, branch_code: e.target.value })}
                      className="w-full px-3 py-2 border border-hairline rounded-md bg-canvas focus:ring-2 focus:ring-primary/30"
                      placeholder="JKT_01"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-ink mb-1">Database Port</label>
                    <input
                      required
                      type="number"
                      value={form.db_port}
                      onChange={(e) => setForm({ ...form, db_port: e.target.value })}
                      className="w-full px-3 py-2 border border-hairline rounded-md bg-canvas focus:ring-2 focus:ring-primary/30"
                      placeholder="5432"
                    />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-sm font-medium text-ink mb-1">Database Host</label>
                    <input
                      required
                      value={form.db_host}
                      onChange={(e) => setForm({ ...form, db_host: e.target.value })}
                      className="w-full px-3 py-2 border border-hairline rounded-md bg-canvas focus:ring-2 focus:ring-primary/30"
                      placeholder="localhost atau domain"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-ink mb-1">Database Name</label>
                    <input
                      required
                      value={form.db_name}
                      onChange={(e) => setForm({ ...form, db_name: e.target.value })}
                      className="w-full px-3 py-2 border border-hairline rounded-md bg-canvas focus:ring-2 focus:ring-primary/30"
                      placeholder="nama_database"
                    />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-sm font-medium text-ink mb-1">Username DB</label>
                    <input
                      required
                      value={form.db_username}
                      onChange={(e) => setForm({ ...form, db_username: e.target.value })}
                      className="w-full px-3 py-2 border border-hairline rounded-md bg-canvas focus:ring-2 focus:ring-primary/30"
                      placeholder="postgres"
                    />
                  </div>
                  <div className="flex flex-col">
                    <label className="block text-sm font-medium text-ink mb-1">Password DB</label>
                    <div className="relative flex-1">
                      <input
                        required
                        type="password"
                        value={form.db_password}
                        onChange={(e) => setForm({ ...form, db_password: e.target.value })}
                        className="w-full px-3 py-2 border border-hairline rounded-md bg-canvas focus:ring-2 focus:ring-primary/30"
                        placeholder="••••••••"
                      />
                    </div>
                  </div>
                </div>
                <div className="flex justify-end gap-2 pt-3 border-t border-hairline mt-2">
                  <button type="button" onClick={() => setShowAddModal(false)} className="px-4 py-2 border border-hairline rounded-md text-sm hover:bg-surface-soft">Batal</button>
                  <button type="submit" className="px-4 py-2 bg-primary text-white rounded-md text-sm hover:bg-primary-active">Simpan Tenant</button>
                </div>
              </form>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// --- Pagination Component ---
function PaginationBar({ page, totalPages, onChange, totalItems, pageSize }) {
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