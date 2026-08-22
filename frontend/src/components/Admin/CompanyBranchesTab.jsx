import { useState, useEffect, useMemo, useRef } from 'react';
import { createPortal } from 'react-dom'; 
import { motion, AnimatePresence } from 'framer-motion';
import { api } from '../../services/api';
import { 
  Plus, CheckCircle, XCircle, Box, X, Search, 
  Loader2, Trash2, Wifi, Pencil, ToggleRight, ToggleLeft, 
  Link, Unlink, MoreVertical, Database,
  ArrowUp, ArrowDown, ChevronsUpDown
} from 'lucide-react';
import { notify } from '../../utils/notification';

// Common & Modal Components
import ConfirmationDialog from './common/ConfirmationDialog';
import PaginationBar from './common/PaginationBar';
import CompanyModal from './company/CompanyModal';
import BranchModal from './branch/BranchModal';
import TenantModal from './branch/TenantModal';

const PAGE_SIZE = 15;

function SortIcon({ columnKey, sortConfig }) {
  if (sortConfig.key !== columnKey) {
    return <ChevronsUpDown size={14} className="inline ml-1 text-muted" />;
  }
  if (sortConfig.direction === 'asc') {
    return <ArrowUp size={14} className="inline ml-1 text-primary" />;
  }
  return <ArrowDown size={14} className="inline ml-1 text-primary" />;
}

export default function CompanyBranchesTab() {
  // ---- DATA STATES ----
  const [companies, setCompanies] = useState([]);
  const [branches, setBranches] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('companies');
  const [searchTerm, setSearchTerm] = useState('');
  
  // ---- PAGINATION ----
  const [companyPage, setCompanyPage] = useState(1);
  const [branchPage, setBranchPage] = useState(1);

  // ---- CONNECTION STATUS ----
  const [connectionStatus, setConnectionStatus] = useState({}); 
  const [tenantData, setTenantData] = useState({});
  
  // ---- MODAL STATES ----
  const [showCompanyModal, setShowCompanyModal] = useState(false);
  const [showBranchModal, setShowBranchModal] = useState(false);
  const [showTenantModal, setShowTenantModal] = useState(false);
  const [editingCompany, setEditingCompany] = useState(null);
  const [editingBranch, setEditingBranch] = useState(null);
  const [editingTenantBranch, setEditingTenantBranch] = useState(null);
  
  // ---- LOADING / PROCESSING ----
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [processingCode, setProcessingCode] = useState(null);

  // ---- CONFIRM DIALOG ----
  const [confirmState, setConfirmState] = useState(null);

  // ---- DROPDOWN STATE ----
  const [dropdownOpen, setDropdownOpen] = useState(null);
  const [dropdownPos, setDropdownPos] = useState({ top: 0, left: 0 });

  // ---- TABLE CONTAINER REF ----
  const tableContainerRef = useRef(null);

  // ---- SORTING STATE (BRANCH) ----
  const [sortConfig, setSortConfig] = useState({ key: 'code', direction: 'asc' });

  // ---- SORTING STATE (COMPANY) ----
  const [companySortConfig, setCompanySortConfig] = useState({ key: 'code', direction: 'asc' });

  // ==========================================
  // 1. DATA FETCHING
  // ==========================================
  useEffect(() => {
    fetchData();
  }, []);
  
  useEffect(() => {
      const handleClickOutside = (event) => {
        if (dropdownOpen && !event.target.closest('.dropdown-trigger')) {
          setDropdownOpen(null);
        }
      };
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }, [dropdownOpen]);

  const fetchData = async () => {
    const scrollTop = tableContainerRef.current?.scrollTop || 0;

    setLoading(true);
    try {
      const [companiesData, branchesWithTenantsData] = await Promise.all([
        api.getCompanies(),
        api.getBranchesWithTenants(),
      ]);
      setCompanies(companiesData || []);

      const statuses = {};
      const tenantDetails = {};
      const formattedBranches = [];

      (branchesWithTenantsData || []).forEach(item => {
        formattedBranches.push({
          code: item.code,
          name: item.name,
          company_code: item.company_code,
          address: item.address,
          is_active: item.is_active
        });

        if (item.db_host) {
          tenantDetails[item.code] = {
            db_host: item.db_host,
            db_port: item.db_port,
            db_name: item.db_name,
            db_username: item.db_username
          };
          statuses[item.code] = 'connected';
        } else {
          statuses[item.code] = 'disconnected';
        }
      });

      setBranches(formattedBranches);
      setTenantData(tenantDetails);
      setConnectionStatus(statuses);
    } catch (e) {
      notify.error('Gagal memuat data perusahaan & cabang');
    } finally {
      setLoading(false);
      setTimeout(() => {
        if (tableContainerRef.current) {
          tableContainerRef.current.scrollTop = scrollTop;
        }
      }, 0);
    }
  };

  // ==========================================
  // 2. FILTERS & PAGINATION
  // ==========================================
  const companiesByCode = useMemo(() => {
    const map = {};
    companies.forEach(c => map[c.code] = c);
    return map;
  }, [companies]);

  const activeCompanies = useMemo(() => companies.filter(c => c.is_active), [companies]);

  const handleTabChange = (tab) => {
    setActiveTab(tab);
    setSearchTerm('');
  };
  const handleSort = (key) => {
    let direction = 'asc';
    if (sortConfig.key === key && sortConfig.direction === 'asc') {
      direction = 'desc';
    }
    setSortConfig({ key, direction });
  };

  useEffect(() => {
    setCompanyPage(1);
    setBranchPage(1);
  }, [searchTerm]);

  const filteredCompanies = useMemo(() => {
    if (!searchTerm) return companies;
    const lower = searchTerm.toLowerCase();
    return companies.filter(c => 
      (c.code || '').toLowerCase().includes(lower) || 
      (c.name || '').toLowerCase().includes(lower)
    );
  }, [companies, searchTerm]);

  const filteredBranches = useMemo(() => {
    if (!searchTerm) return branches;
    const lower = searchTerm.toLowerCase();
    return branches.filter(b => {
      const companyName = companiesByCode[b.company_code]?.name || '';
      return (
        (b.code || '').toLowerCase().includes(lower) ||
        (b.name || '').toLowerCase().includes(lower) ||
        (b.company_code || '').toLowerCase().includes(lower) ||
        companyName.toLowerCase().includes(lower) ||
        (tenantData[b.code]?.db_host || '').toLowerCase().includes(lower)
      );
    });
  }, [branches, searchTerm, companiesByCode, tenantData]);

  const companyTotalPages = Math.max(1, Math.ceil(filteredCompanies.length / PAGE_SIZE));
  const branchTotalPages = Math.max(1, Math.ceil(filteredBranches.length / PAGE_SIZE));

  const sortedCompanies = useMemo(() => {
    const sorted = [...filteredCompanies];
    return sorted.sort((a, b) => {
      let aVal = a[companySortConfig.key] || '';
      let bVal = b[companySortConfig.key] || '';
      if (aVal < bVal) return companySortConfig.direction === 'asc' ? -1 : 1;
      if (aVal > bVal) return companySortConfig.direction === 'asc' ? 1 : -1;
      return 0;
    });
  }, [filteredCompanies, companySortConfig]);

  const safeCompanyPage = Math.min(companyPage, companyTotalPages);
  const paginatedCompanies = useMemo(() => {
    const start = (safeCompanyPage - 1) * PAGE_SIZE;
    return sortedCompanies.slice(start, start + PAGE_SIZE);
  }, [sortedCompanies, safeCompanyPage]);

  const sortedBranches = useMemo(() => {
    const sorted = [...filteredBranches];
    return sorted.sort((a, b) => {
      let aVal = a[sortConfig.key] || '';
      let bVal = b[sortConfig.key] || '';

      if (sortConfig.key === 'company_code') {
        aVal = companiesByCode[a.company_code]?.name || a.company_code;
        bVal = companiesByCode[b.company_code]?.name || b.company_code;
      }
      
      if (sortConfig.key === 'status') {
        aVal = connectionStatus[a.code] === 'connected' ? 1 : 0;
        bVal = connectionStatus[b.code] === 'connected' ? 1 : 0;
      }

      if (aVal < bVal) return sortConfig.direction === 'asc' ? -1 : 1;
      if (aVal > bVal) return sortConfig.direction === 'asc' ? 1 : -1;
      return 0;
    });
  }, [filteredBranches, sortConfig, companiesByCode, connectionStatus]);
 
  const safeBranchPage = Math.min(branchPage, branchTotalPages);
  const paginatedBranches = useMemo(() => {
    const start = (safeBranchPage - 1) * PAGE_SIZE;
    return sortedBranches.slice(start, start + PAGE_SIZE);
  }, [sortedBranches, safeBranchPage]);

  // ==========================================
  // 3. HANDLERS: COMPANY
  // ==========================================
  const handleSaveCompany = async (form) => {
    setSaving(true);
    try {
      if (editingCompany) {
        await api.updateCompany(editingCompany.code, form);
        notify.success('Perusahaan berhasil diperbarui!');
      } else {
        await api.createCompany(form);
        notify.success('Perusahaan berhasil ditambahkan!');
      }
      setShowCompanyModal(false);
      setEditingCompany(null);
      await fetchData();
    } catch (e) {
      notify.error(e.response?.data?.detail || 'Gagal menyimpan perusahaan');
    } finally {
      setSaving(false);
    }
  };

  const handleToggleCompany = async (company) => {
    setProcessingCode(company.code);
    try {
      const newStatus = !company.is_active;
      await api.updateCompany(company.code, {
        name: company.name,
        address: company.address || '',
        is_active: newStatus,
      });
      notify.success(`Perusahaan berhasil ${newStatus ? 'diaktifkan' : 'dinonaktifkan'}`);
      await fetchData();
    } catch (e) {
      notify.error(e.response?.data?.detail || 'Gagal mengubah status perusahaan');
    } finally {
      setProcessingCode(null);
    }
  };

  const handleCompanySort = (key) => {
    let direction = 'asc';
    if (companySortConfig.key === key && companySortConfig.direction === 'asc') {
      direction = 'desc';
    }
    setCompanySortConfig({ key, direction });
  };

  const handleDeleteCompany = (code) => {
    setConfirmState({
      title: 'Hapus Perusahaan?',
      message: `Perusahaan ${code} beserta semua cabang di bawahnya akan dihapus permanen. Tindakan ini tidak bisa dibatalkan.`,
      onConfirm: async () => {
        setProcessingCode(code);
        try {
          await api.deleteCompany(code);
          notify.success('Perusahaan berhasil dihapus');
          await fetchData();
        } catch (e) {
          notify.error('Gagal menghapus perusahaan');
        } finally {
          setProcessingCode(null);
          setConfirmState(null);
        }
      },
    });
  };

  // ==========================================
  // 4. HANDLERS: BRANCH
  // ==========================================
  const handleSaveBranch = async (form) => {
    setSaving(true);
    try {
      if (editingBranch) {
        await api.updateBranch(editingBranch.code, form);
        notify.success('Cabang berhasil diperbarui!');
      } else {
        await api.createBranch(form);
        notify.success('Cabang berhasil ditambahkan!');
      }
      setShowBranchModal(false);
      setEditingBranch(null);
      await fetchData();
    } catch (e) {
      notify.error(e.response?.data?.detail || 'Gagal menyimpan cabang');
    } finally {
      setSaving(false);
    }
  };

  const handleToggleBranch = async (branch) => {
    setProcessingCode(branch.code);
    try {
      const newStatus = !branch.is_active;
      await api.updateBranch(branch.code, {
        name: branch.name,
        company_code: branch.company_code,
        address: branch.address || '',
        is_active: newStatus,
      });
      notify.success(`Cabang berhasil ${newStatus ? 'diaktifkan' : 'dinonaktifkan'}`);
      await fetchData();
    } catch (e) {
      notify.error('Gagal mengubah status cabang');
    } finally {
      setProcessingCode(null);
    }
  };

  const handleDeleteBranch = (code) => {
    setConfirmState({
      title: 'Hapus Cabang?',
      message: `Cabang ${code} akan dihapus permanen. Tindakan ini tidak bisa dibatalkan.`,
      onConfirm: async () => {
        setProcessingCode(code);
        try {
          await api.deleteBranch(code);
          notify.success('Cabang berhasil dihapus');
          await fetchData();
        } catch (e) {
          notify.error('Gagal menghapus cabang');
        } finally {
          setProcessingCode(null);
          setConfirmState(null);
        }
      },
    });
  };

  // ==========================================
  // 5. HANDLERS: TENANT (DATABASE CONNECTION)
  // ==========================================
  const openTenantModal = (branch) => {
    setEditingTenantBranch(branch.code);
    setShowTenantModal(true);
  };

  const handleTestTenant = async (branch_code, form) => {
    setTesting(true);
    try {
      const result = await api.testTenantConnection(branch_code, form);
      return result;
    } catch (e) {
      return { status: 'disconnected', message: 'Terjadi kesalahan saat uji koneksi' };
    } finally {
      setTesting(false);
    }
  };

  const handleSaveTenant = async (form) => {
    setSaving(true);
    try {
      const isEdit = !!tenantData[editingTenantBranch];
      if (isEdit) {
        await api.updateTenant(editingTenantBranch, form);
        notify.success('Konfigurasi database berhasil diperbarui!');
      } else {
        await api.createTenant({ ...form, branch_code: editingTenantBranch });
        notify.success('Database berhasil dihubungkan ke cabang!');
      }
      setShowTenantModal(false);
      setEditingTenantBranch(null);
    } catch (e) {
      const detail = e.response?.data?.detail || 'Gagal menyimpan konfigurasi database';
      notify.error(detail);
    } finally {
      await fetchData();
      setSaving(false);
    }
  };

  const handleDisconnectTenant = (branch_code) => {
    setConfirmState({
      title: 'Putuskan Koneksi Database?',
      message: `Koneksi database untuk cabang ${branch_code} akan dihapus. Tindakan ini tidak bisa dibatalkan.`,
      onConfirm: async () => {
        setProcessingCode(branch_code);
        try {
          await api.deleteTenant(branch_code);
          notify.success('Koneksi database berhasil diputus');
          await fetchData();
        } catch (e) {
          notify.error('Gagal memutus koneksi database');
        } finally {
          setProcessingCode(null);
          setConfirmState(null);
        }
      },
    });
  };

  // ==========================================
  // 6. RENDER
  // ==========================================
  const SkeletonLoader = () => (
    <div className="bg-white rounded-xl border border-hairline overflow-hidden shadow-sm p-4 space-y-3 animate-pulse">
      <div className="h-8 bg-surface-soft rounded w-1/4 mb-4" />
      {[...Array(5)].map((_, i) => (
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
      {/* Global Search & Action Bar */}
      <div className="flex justify-between items-center gap-4 flex-wrap">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" size={16} />
          <input
            type="text"
            placeholder="Cari kode, nama, atau host..."
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
      </div>

      {/* Segmented Control Tab */}
      <div className="flex gap-2 border border-hairline rounded-md p-1 bg-surface-soft w-fit">
        <button onClick={() => handleTabChange('companies')} className={`px-4 py-1.5 text-xs font-medium rounded transition-colors ${activeTab === 'companies' ? 'bg-primary text-white shadow-sm' : 'text-muted hover:text-ink'}`}>
          Perusahaan
        </button>
        <button onClick={() => handleTabChange('branches')} className={`px-4 py-1.5 text-xs font-medium rounded transition-colors ${activeTab === 'branches' ? 'bg-primary text-white shadow-sm' : 'text-muted hover:text-ink'}`}>
          Cabang / Dealer
        </button>
      </div>

      {/* ============= TAB PERUSAHAAN ============= */}
      {activeTab === 'companies' && (
        <div className="space-y-4">
          <div className="flex justify-between items-center">
            <span className="text-xs text-muted">Menampilkan {filteredCompanies.length} dari {companies.length}</span>
            <button onClick={() => { setEditingCompany(null); setShowCompanyModal(true); }} className="flex items-center gap-2 px-3 py-1.5 bg-primary text-white rounded-md text-xs hover:bg-primary-active">
              <Plus size={14} /> Tambah Perusahaan
            </button>
          </div>

          {filteredCompanies.length === 0 ? (
            <div className="bg-white rounded-xl border border-hairline p-10 flex flex-col items-center justify-center text-center text-muted">
              <Box className="w-12 h-12 mb-3 text-hairline" />
              <p className="font-medium text-ink">{companies.length === 0 ? 'Belum ada perusahaan' : 'Tidak ada hasil'}</p>
            </div>
          ) : (
            <div className="bg-white rounded-xl border border-hairline overflow-hidden shadow-sm">
              <div ref={tableContainerRef}  className="overflow-x-auto">
                <table className="w-full text-left">
                  <thead className="bg-surface-soft text-sm text-muted">
                    <tr>
                      <th className="p-3 w-24 cursor-pointer select-none hover:text-ink" onClick={() => handleCompanySort('code')}>
                        Kode <SortIcon columnKey="code" sortConfig={companySortConfig} />
                      </th>
                      <th className="p-3 cursor-pointer select-none hover:text-ink" onClick={() => handleCompanySort('name')}>
                        Nama <SortIcon columnKey="name" sortConfig={companySortConfig} />
                      </th>
                      <th className="p-3">Alamat</th>
                      <th className="p-3 w-24 cursor-pointer select-none hover:text-ink" onClick={() => handleCompanySort('is_active')}>
                        Status <SortIcon columnKey="is_active" sortConfig={companySortConfig} />
                      </th>
                      <th className="p-3 w-24">Aksi</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-hairline">
                    {paginatedCompanies.map((c, idx) => (
                      <motion.tr key={c.code} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: idx * 0.03 }} className="hover:bg-surface-soft/50 transition-colors">
                        <td className="p-3 font-medium text-sm">{c.code}</td>
                        <td className="p-3 text-body text-sm">{c.name}</td>
                        <td className="p-3 text-muted text-sm">{c.address || '-'}</td>
                        <td className="p-3">
                          <button onClick={() => handleToggleCompany(c)} disabled={processingCode === c.code} className="flex items-center gap-1 text-xs font-medium hover:opacity-80 disabled:opacity-50">
                            {processingCode === c.code ? <Loader2 size={16} className="animate-spin" /> : c.is_active ? <><ToggleRight size={18} className="text-success" /> Aktif</> : <><ToggleLeft size={18} className="text-error" /> Nonaktif</>}
                          </button>
                        </td>
                        <td className="p-3 flex gap-2">
                          <button onClick={() => { setEditingCompany(c); setShowCompanyModal(true); }} className="text-muted hover:text-ink"><Pencil size={16} /></button>
                          <button onClick={() => handleDeleteCompany(c.code)} className="text-muted hover:text-error"><Trash2 size={16} /></button>
                        </td>
                      </motion.tr>
                    ))}
                  </tbody>
                </table>
              </div>
                <PaginationBar page={companyPage} totalPages={companyTotalPages} onChange={setCompanyPage} totalItems={filteredCompanies.length} pageSize={PAGE_SIZE} />
            </div>
          )}
        </div>
      )}

      {/* ============= TAB CABANG (Terintegrasi DB) ============= */}
      {activeTab === 'branches' && (
        <div className="space-y-4">
          <div className="flex justify-between items-center">
            <span className="text-xs text-muted">Menampilkan {filteredBranches.length} dari {branches.length}</span>
            <button onClick={() => { setEditingBranch(null); setShowBranchModal(true); }} className="flex items-center gap-2 px-3 py-1.5 bg-primary text-white rounded-md text-xs hover:bg-primary-active">
              <Plus size={14} /> Tambah Cabang
            </button>
          </div>

          {filteredBranches.length === 0 ? (
            <div className="bg-white rounded-xl border border-hairline p-10 flex flex-col items-center justify-center text-center text-muted">
              <Box className="w-12 h-12 mb-3 text-hairline" />
              <p className="font-medium text-ink">{branches.length === 0 ? 'Belum ada cabang' : 'Tidak ada hasil'}</p>
            </div>
          ) : (
            <div className="bg-white rounded-xl border border-hairline overflow-hidden shadow-sm">
              <div ref={tableContainerRef}  className="overflow-x-auto">
                <table className="w-full text-left">
                  <thead className="bg-surface-soft text-sm text-muted">
                    <tr>
                      <th className="p-3 w-24 cursor-pointer select-none hover:text-ink" onClick={() => handleSort('code')}>
                        Kode <SortIcon columnKey="code" sortConfig={sortConfig} />
                      </th>
                      <th className="p-3 cursor-pointer select-none hover:text-ink" onClick={() => handleSort('name')}>
                        Nama Cabang <SortIcon columnKey="name" sortConfig={sortConfig} />
                      </th>
                      <th className="p-3 cursor-pointer select-none hover:text-ink" onClick={() => handleSort('company_code')}>
                        Perusahaan <SortIcon columnKey="company_code" sortConfig={sortConfig} />
                      </th>
                      <th className="p-3 w-28 cursor-pointer select-none hover:text-ink" onClick={() => handleSort('status')}>
                        Status DB <SortIcon columnKey="status" sortConfig={sortConfig} />
                      </th>
                      <th className="p-3">Host / Port</th>
                      <th className="p-3 w-0 text-center">Aksi</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-hairline">
                    {paginatedBranches.map((b, idx) => {
                      const isProcessing = processingCode === b.code;
                      const status = connectionStatus[b.code] || 'disconnected';
                      const tenant = tenantData[b.code];
                      const isConnected = status === 'connected';
                      const isDropdownOpen = dropdownOpen === b.code;
                      const toggleDropdown = () => setDropdownOpen(isDropdownOpen ? null : b.code);

                      return (
                        <motion.tr key={b.code} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: idx * 0.03 }} className="hover:bg-surface-soft/50 transition-colors relative">
                          <td className="p-3 font-medium text-sm">{b.code}</td>
                          <td className="p-3 text-body text-sm">{b.name}</td>
                          <td className="p-3 text-muted text-sm">{companiesByCode[b.company_code]?.name || b.company_code}</td>
                          <td className="p-3">
                            <span className={`inline-flex items-center text-xs font-medium ${isConnected ? 'text-success' : 'text-error'}`}>
                              {isConnected ? <CheckCircle size={14} className="mr-1" /> : <XCircle size={14} className="mr-1" />}
                              {isConnected ? 'Connected' : 'Disconnected'}
                            </span>
                          </td>
                          <td className="p-3 text-sm text-body">{tenant ? `${tenant.db_host}:${tenant.db_port}` : '-'}</td>
                          
                          {/* ========== KOLOM AKSI BARU ========== */}
                          <td className="p-3">
                            <div className="flex justify-end">
                              
                              {/* Aksi Utama (Ikon Langsung) */}
                              {isConnected ? (
                                <>
                                  <button
                                    onClick={async () => {
                                      const testPayload = { ...tenant };
                                      delete testPayload.db_password;
                                      const result = await handleTestTenant(b.code, testPayload);
                                      if (result.status === 'connected') {
                                        notify.success('Koneksi berhasil!');
                                      } else {
                                        notify.error(`Koneksi gagal: ${result.message || ''}`);
                                      }
                                    }}
                                    disabled={isProcessing}
                                    className="p-1.5 text-muted hover:text-primary hover:bg-surface-soft rounded-md transition-colors disabled:opacity-50"
                                    title="Test Koneksi"
                                  >
                                    <Wifi size={16} />
                                  </button>
                                  <button 
                                    onClick={() => handleDisconnectTenant(b.code)} 
                                    disabled={isProcessing}
                                    className="p-1.5 text-muted hover:text-error hover:bg-error/5 rounded-md transition-colors disabled:opacity-50"
                                    title="Putus Koneksi"
                                  >
                                    <Unlink size={16} />
                                  </button>
                                </>
                              ) : (
                                <button 
                                  onClick={() => openTenantModal(b)} 
                                  disabled={isProcessing}
                                  className="p-1.5 text-primary hover:bg-primary/5 rounded-md transition-colors disabled:opacity-50"
                                  title="Hubungkan Database"
                                >
                                  <Link size={16} />
                                </button>
                              )}

                              {/* Dropdown Menu (Aksi Sekunder) */}
                              <div className="relative dropdown-trigger">
                                <button
                                  onClick={(e) => {
                                    const rect = e.currentTarget.getBoundingClientRect();
                                    setDropdownPos({
                                      top: rect.bottom + window.scrollY,
                                      left: rect.right - 160 + window.scrollX
                                    });
                                    toggleDropdown();
                                  }}
                                  className="dropdown-trigger p-1.5 text-muted hover:text-ink hover:bg-surface-soft rounded-md transition-colors"
                                >
                                  <MoreVertical size={16} />
                                </button>
                              
                                {/* Dropdown Content - DI PORTAL KE BODY */}
                                {isDropdownOpen && createPortal(
                                  <div
                                    className="fixed z-[9999] w-40 bg-white rounded-md shadow-lg border border-hairline py-1"
                                    style={{ top: dropdownPos.top, left: dropdownPos.left }}
                                  >
                                    <button
                                      onMouseDown={(e) => {
                                          e.preventDefault();
                                          setDropdownOpen(null);
                                          setTimeout(() => {
                                            setEditingBranch(b);
                                            setShowBranchModal(true);
                                          }, 50);
                                        }}
                                      className="flex items-center gap-2 w-full px-4 py-2 text-xs text-ink hover:bg-surface-soft transition-colors text-left"
                                    >
                                      <Pencil size={14} /> Edit Cabang
                                    </button>
                              
                                    {isConnected && (
                                      <button
                                        onMouseDown={(e) => {
                                          e.preventDefault();
                                          setDropdownOpen(null);
                                          setTimeout(() => {
                                            setEditingTenantBranch(b.code);
                                            setShowTenantModal(true);
                                          }, 50);
                                        }}
                                        className="flex items-center gap-2 w-full px-4 py-2 text-xs text-ink hover:bg-surface-soft transition-colors text-left"
                                      >
                                        <Database size={14} /> Edit Database
                                      </button>
                                    )}
                              
                                    <button
                                      onMouseDown={(e) => {
                                        e.preventDefault();
                                        setDropdownOpen(null);
                                        setTimeout(() => {
                                          setDropdownOpen(null);
                                          handleDeleteBranch(b.code);
                                        }, 50);
                                      }}
                                      className="flex items-center gap-2 w-full px-4 py-2 text-xs text-error hover:bg-error/5 transition-colors text-left"
                                    >
                                      <Trash2 size={14} /> Hapus Cabang
                                    </button>
                                  </div>,
                                  document.body
                                )}
                              </div>
                            </div>
                          </td>
                        </motion.tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <PaginationBar page={branchPage} totalPages={branchTotalPages} onChange={setBranchPage} totalItems={filteredBranches.length} pageSize={PAGE_SIZE} />
            </div>
          )}
        </div>
      )}

      {/* ============= MODALS ============= */}

      {/* Company Modal */}
      {showCompanyModal && (
        <CompanyModal
          key="companyModal"
          isOpen={showCompanyModal}
          onClose={() => setShowCompanyModal(false)}
          onSave={handleSaveCompany}
          company={editingCompany}
          isSaving={saving}
        />
      )}

      {/* Branch Modal */}
      {showBranchModal && (
        <BranchModal
          key={editingBranch?.code || 'new'}
          isOpen={showBranchModal}
          onClose={() => setShowBranchModal(false)}
          onSave={handleSaveBranch}
          branch={editingBranch}
          companies={companies}
          isSaving={saving}
        />
      )}
      
      {/* Tenant Modal */}
      {showTenantModal && (
        <TenantModal
          key={editingTenantBranch || 'new'}
          isOpen={showTenantModal}
          onClose={() => setShowTenantModal(false)}
          onSave={handleSaveTenant}
          onTest={handleTestTenant}
          branchCode={editingTenantBranch}
          tenant={tenantData[editingTenantBranch]}
          isSaving={saving}
          isTesting={testing}
        />
      )}

      {/* Confirmation Dialog */}
      {confirmState && (
        <ConfirmationDialog
          key="confirmDialog"
          isOpen={!!confirmState}
          onClose={() => setConfirmState(null)}
          onConfirm={confirmState.onConfirm}
          title={confirmState.title}
          message={confirmState.message}
          isLoading={!!processingCode}
        />
      )}
    </div>
  );
}