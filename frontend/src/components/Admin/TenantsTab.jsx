import { useState, useEffect, useMemo } from 'react';
import { motion } from 'framer-motion';
import { api } from '../../services/api';
import {
  Plus, CheckCircle, XCircle, Search,
  Loader2, Trash2, Wifi, X
} from 'lucide-react';
import toast from 'react-hot-toast';
import PaginationBar from './common/PaginationBar';
import EmptyState from './common/EmptyState';
import ConfirmationDialog from './common/ConfirmationDialog';
import TenantFormModal from './tenants/TenantFormModal';
import SkeletonTable from './common/SkeletonTable';
import useDebounce from '../../hooks/useDebounce';
import useAdminShortcuts from '../../hooks/useAdminShortcuts';

const PAGE_SIZE = 10;

export default function TenantsTab() {
  const [tenants, setTenants] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const debouncedSearch = useDebounce(searchTerm, 300);
  const [statusFilter, setStatusFilter] = useState('All');
  const [page, setPage] = useState(1);
  const [connectionStatus, setConnectionStatus] = useState({});
  const [showAddModal, setShowAddModal] = useState(false);
  const [processingCode, setProcessingCode] = useState(null);
  const [confirmState, setConfirmState] = useState(null);

  useEffect(() => {
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useAdminShortcuts({
    onEscape: () => {
      if (confirmState) setConfirmState(null);
      else if (showAddModal) setShowAddModal(false);
    },
    isBusy: !!processingCode,
    searchInputId: 'tenant-search',
  });

  const fetchData = async () => {
    setLoading(true);
    try {
      const data = await api.getTenants();
      setTenants(data || []);
      testAllConnections(data || []);
    } catch {
      toast.error('Gagal memuat data tenant');
    } finally {
      setLoading(false);
    }
  };

  const testAllConnections = (tenantList) => {
    // Paralel; tiap baris menampilkan spinner sampai hasilnya masuk
    tenantList.forEach(async (t) => {
      setConnectionStatus(prev => ({ ...prev, [t.branch_code]: 'checking' }));
      try {
        const result = await api.testTenantConnection(t.branch_code);
        setConnectionStatus(prev => ({ ...prev, [t.branch_code]: result.status }));
      } catch {
        setConnectionStatus(prev => ({ ...prev, [t.branch_code]: 'disconnected' }));
      }
    });
  };

  const handleTestSingle = async (branch_code) => {
    setConnectionStatus(prev => ({ ...prev, [branch_code]: 'checking' }));
    try {
      const result = await api.testTenantConnection(branch_code);
      setConnectionStatus(prev => ({ ...prev, [branch_code]: result.status }));
      if (result.status === 'connected') toast.success(`Koneksi ke ${branch_code} berhasil!`);
      else toast.error(`Koneksi gagal: ${result.message || ''}`);
    } catch {
      setConnectionStatus(prev => ({ ...prev, [branch_code]: 'disconnected' }));
      toast.error('Gagal melakukan test koneksi');
    }
  };

  const handleAddTenant = async (form) => {
    try {
      await api.createTenant(form);
      toast.success('Tenant berhasil ditambahkan!');
      setShowAddModal(false);
      await fetchData();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Gagal menambahkan tenant');
    }
  };

  const handleDeleteTenant = (branch_code) => {
    setConfirmState({
      title: 'Hapus Tenant?',
      message: `Konfigurasi database untuk cabang ${branch_code} akan dihapus permanen. Tindakan ini tidak bisa dibatalkan.`,
      onConfirm: async () => {
        setProcessingCode(branch_code);
        try {
          await api.deleteTenant(branch_code);
          toast.success('Tenant berhasil dihapus');
          await fetchData();
        } catch {
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
    if (debouncedSearch) {
      const lower = debouncedSearch.toLowerCase();
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
  }, [tenants, debouncedSearch, statusFilter, connectionStatus]);

  const totalPages = Math.max(1, Math.ceil(filteredTenants.length / PAGE_SIZE));
  const paginatedTenants = useMemo(() => {
    const start = (page - 1) * PAGE_SIZE;
    return filteredTenants.slice(start, start + PAGE_SIZE);
  }, [filteredTenants, page]);

  useEffect(() => setPage(1), [debouncedSearch, statusFilter]);
  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  if (loading) return <SkeletonTable rows={4} columns={4} />;

  return (
    <div className="space-y-6">
      {/* Search + filter status + tambah */}
      <div className="flex items-center gap-4 flex-wrap">
        <div className="relative flex-1 max-w-sm w-full">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" size={16} />
          <input
            id="tenant-search"
            type="text"
            placeholder="Cari kode cabang atau host...  ( / )"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full pl-9 pr-8 py-2 border border-hairline rounded-md bg-canvas text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
          />
          {searchTerm && (
            <button type="button" onClick={() => setSearchTerm('')} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted hover:text-ink">
              <X size={14} />
            </button>
          )}
        </div>

        <div className="flex items-center gap-3 ml-auto">
          <div className="flex gap-1 border border-hairline rounded-md p-1 bg-surface-soft">
            {['All', 'Connected', 'Disconnected'].map((status) => (
              <button key={status} onClick={() => setStatusFilter(status)}
                className={`px-3 py-1 text-xs font-medium rounded transition-colors ${
                  statusFilter === status ? 'bg-primary text-white shadow-sm' : 'text-muted hover:text-ink'
                }`}>
                {status}
              </button>
            ))}
          </div>
          <button onClick={() => setShowAddModal(true)}
            className="flex items-center gap-2 px-3 py-1.5 bg-primary text-white rounded-md text-xs hover:bg-primary-active whitespace-nowrap">
            <Plus size={14} /> Tambah Tenant
          </button>
        </div>
      </div>

      {filteredTenants.length === 0 ? (
        <EmptyState
          variant="plug"
          title={tenants.length === 0 ? 'Belum ada tenant terdaftar' : 'Tidak ada hasil pencarian'}
          description={
            tenants.length === 0
              ? 'Klik tombol "Tambah Tenant" untuk menghubungkan database cabang.'
              : 'Coba gunakan kata kunci lain.'
          }
        />
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
                  const status = connectionStatus[t.branch_code] || 'checking';
                  const isProcessing = processingCode === t.branch_code;
                  return (
                    <motion.tr
                      key={t.branch_code}
                      initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: Math.min(idx * 0.03, 0.3) }}
                      className="hover:bg-surface-soft/50 transition-colors"
                    >
                      <td className="p-3 font-medium text-sm">{t.branch_code}</td>
                      <td className="p-3">
                        {status === 'checking' || status === 'loading' ? (
                          <span className="inline-flex items-center text-muted text-xs">
                            <Loader2 size={13} className="mr-1.5 animate-spin" /> Menguji…
                          </span>
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
                        <button onClick={() => handleTestSingle(t.branch_code)}
                          disabled={status === 'checking' || status === 'loading'}
                          className="text-muted hover:text-primary transition-colors disabled:opacity-50" title="Test Koneksi">
                          <Wifi size={14} />
                        </button>
                        <button onClick={() => handleDeleteTenant(t.branch_code)} disabled={isProcessing}
                          className="text-muted hover:text-error transition-colors disabled:opacity-50" title="Hapus">
                          {isProcessing ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                        </button>
                      </td>
                    </motion.tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <PaginationBar page={page} totalPages={totalPages} onChange={setPage} totalItems={filteredTenants.length} pageSize={PAGE_SIZE} />
        </div>
      )}

      {/* Confirm delete */}
      {confirmState && (
        <ConfirmationDialog
          key="tenantConfirm"
          isOpen={!!confirmState}
          onClose={() => setConfirmState(null)}
          onConfirm={confirmState.onConfirm}
          title={confirmState.title}
          message={confirmState.message}
          isLoading={!!processingCode}
        />
      )}

      {/* Modal tambah */}
      {showAddModal && (
        <TenantFormModal
          isOpen={showAddModal}
          onClose={() => setShowAddModal(false)}
          onSubmit={handleAddTenant}
        />
      )}
    </div>
  );
}
