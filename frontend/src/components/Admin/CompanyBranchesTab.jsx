import { useState } from 'react';
import { X, Search , Database, Plus, CheckCircle, Wifi, Pencil, Trash2, Loader2} from 'lucide-react';
import toast from 'react-hot-toast';
import { api } from '../../services/api';
import { notify } from '../../utils/notification';

import ConfirmationDialog from './common/ConfirmationDialog';
import SkeletonTable from './common/SkeletonTable';
import CompanyModal from './company/CompanyModal';
import CompanyDetailModal from './company/CompanyDetailModal';
import CompaniesTable from './company/CompaniesTable';
import BranchModal from './branch/BranchModal';
import BranchDetailModal from './branch/BranchDetailModal';
import BranchesTable from './branch/BranchesTable';
import ConnectDbModal from './tenants/ConnectDbModal';
import DbConnectionModal from './tenants/DbConnectionModal';
import useAdminShortcuts from '../../hooks/useAdminShortcuts';
import useCompanyBranchData from '../../hooks/useCompanyBranchData';

/**
 * Orkestrator tipis: state data & tabel ada di useCompanyBranchData +
 * sub-komponen company/CompaniesTable & branch/BranchesTable.
 * File ini hanya menampung handler aksi (CRUD, tenant, confirm) dan layout.
 */
export default function CompanyBranchesTab() {
  const data = useCompanyBranchData();
  const {
    companies, loading, fetchData,
    tenantData, connectionStatus, companiesByCode, tableContainerRef,
    dbConnections, dbConnectionsById,
    searchTerm, setSearchTerm,
    paginatedCompanies, companyPage, setCompanyPage, companyTotalPages, filteredCompanies,
    companySortConfig, handleCompanySort,
    paginatedBranches, branchPage, setBranchPage, branchTotalPages, filteredBranches,
    branchSortConfig, handleBranchSort,
    PAGE_SIZE,
  } = data;

  // ---- SUB-TAB ----
  const [activeTab, setActiveTab] = useState('companies');

  // ---- MODAL STATES ----
  const [showCompanyModal, setShowCompanyModal] = useState(false);
  const [showBranchModal, setShowBranchModal] = useState(false);
  const [editingCompany, setEditingCompany] = useState(null);
  const [editingBranch, setEditingBranch] = useState(null);
  const [connectDbBranch, setConnectDbBranch] = useState(null); // cabang yang sedang memilih database
  const [showRegistryModal, setShowRegistryModal] = useState(false);
  const [editingRegistry, setEditingRegistry] = useState(null);

  // ---- PROCESSING / CONFIRM ----
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [processingCode, setProcessingCode] = useState(null);
  const [confirmState, setConfirmState] = useState(null);

  // ---- DETAIL MODALS ----
  const [detailCompany, setDetailCompany] = useState(null);
  const [detailBranch, setDetailBranch] = useState(null);

  // ---- DROPDOWN ----
  const [dropdownOpen, setDropdownOpen] = useState(null);
  const [dropdownPos, setDropdownPos] = useState({ top: 0, left: 0 });

  // Keyboard standar admin
  useAdminShortcuts({
    onEscape: () => {
      if (confirmState) setConfirmState(null);
      else if (showCompanyModal) setShowCompanyModal(false);
      else if (showBranchModal) setShowBranchModal(false);
      else if (dropdownOpen) setDropdownOpen(null);
    },
    isBusy: !!processingCode || saving || testing,
    searchInputId: 'cb-search',
  });

  // ==========================================
  // HANDLERS: COMPANY
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

  const handleToggleCompany = (company) => {
    // Aksi berdampak kaskade (semua cabang ikut berubah) -> wajib konfirmasi
    setConfirmState({
      title: company.is_active ? 'Nonaktifkan Perusahaan?' : 'Aktifkan Perusahaan?',
      message: company.is_active
        ? `Semua cabang di bawah ${company.name} akan ikut dinonaktifkan. Lanjutkan?`
        : `Perusahaan ${company.name} dan seluruh cabangnya akan diaktifkan kembali. Lanjutkan?`,
      onConfirm: async () => {
        setProcessingCode(company.code);
        try {
          await api.updateCompany(company.code, {
            name: company.name,
            address: company.address || '',
            is_active: !company.is_active,
          });
          notify.success(`Perusahaan berhasil ${!company.is_active ? 'diaktifkan' : 'dinonaktifkan'}`);
          await fetchData();
        } catch (e) {
          notify.error(e.response?.data?.detail || 'Gagal mengubah status perusahaan');
        } finally {
          setProcessingCode(null);
          setConfirmState(null);
        }
      },
    });
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
          const detail = e.response?.data?.detail || 'Gagal menghapus perusahaan';
          // Kalau ditolak karena masih ada tenant, tawarkan jalan pintas ke tab tenant
          if (String(detail).toLowerCase().includes('tenant')) {
            toast.custom((t) => (
              <div className="bg-white border border-hairline shadow-lg rounded-lg p-4 flex items-start gap-3 max-w-md">
                <div className="flex-1 text-sm text-body">{detail}</div>
                <button
                  onClick={() => { toast.dismiss(t.id); window.dispatchEvent(new CustomEvent('dms-navigate', { detail: 'tenants' })); }}
                  className="px-3 py-1.5 bg-primary text-white rounded-md text-xs font-medium hover:bg-primary-active whitespace-nowrap"
                >
                  Ke menu Tenant
                </button>
              </div>
            ), { duration: 8000 });
          } else {
            notify.error(detail);
          }
        } finally {
          setProcessingCode(null);
          setConfirmState(null);
        }
      },
    });
  };

  // ==========================================
  // HANDLERS: BRANCH
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
          notify.error(e.response?.data?.detail || 'Gagal menghapus cabang');
        } finally {
          setProcessingCode(null);
          setConfirmState(null);
        }
      },
    });
  };

  // ==========================================
  // HANDLERS: TENANT (DATABASE CONNECTION)
  // ==========================================
  const handleTestTenant = async (branch_code) => {
    setTesting(true);
    try {
      return await api.testTenantConnection(branch_code);
    } catch {
      return { status: 'disconnected', message: 'Terjadi kesalahan saat uji koneksi' };
    } finally {
      setTesting(false);
    }
  };

  // Simpan pilihan database untuk cabang (hubungkan baru / ganti)
  const handleSaveConnectDb = async ({ branch_code, db_connection_id, isChange }) => {
    setSaving(true);
    try {
      if (isChange) {
        await api.updateTenantDb(branch_code, db_connection_id);
        notify.success('Database cabang berhasil diganti');
      } else {
        await api.createTenant({ branch_code, db_connection_id });
        notify.success('Database berhasil dihubungkan ke cabang');
      }
      setConnectDbBranch(null);
      await fetchData();
    } catch (e) {
      notify.error(e.response?.data?.detail || 'Gagal menghubungkan database');
    } finally {
      setSaving(false);
    }
  };

  // Registry: daftarkan / edit database
  const handleSaveRegistry = async ({ id, ...payload }) => {
    setSaving(true);
    try {
      if (id) {
        await api.updateDbConnection(id, payload);
        notify.success('Database terdaftar berhasil diperbarui');
      } else {
        await api.createDbConnection(payload);
        notify.success('Database berhasil didaftarkan');
      }
      setShowRegistryModal(false);
      setEditingRegistry(null);
      await fetchData();
    } catch (e) {
      notify.error(e.response?.data?.detail || 'Gagal menyimpan database');
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteRegistry = (conn) => {
    setConfirmState({
      title: 'Hapus Database Terdaftar?',
      message: `Database "${conn.name}" akan dihapus dari registry. Cabang yang masih memakainya harus diputuskan dulu.`,
      onConfirm: async () => {
        try {
          await api.deleteDbConnection(conn.id);
          notify.success('Database dihapus dari registry');
          setConfirmState(null);
          await fetchData();
        } catch (e) {
          notify.error(e.response?.data?.detail || 'Gagal menghapus database');
          setConfirmState(null);
        }
      },
    });
  };

  const handleTestRegistry = async (connId) => {
    setTesting(true);
    try {
      const result = await api.testDbConnection(connId);
      result.status === 'connected'
        ? notify.success('Koneksi berhasil!')
        : notify.error(`Gagal: ${result.message || ''}`);
    } catch {
      notify.error('Gagal menguji koneksi');
    } finally {
      setTesting(false);
    }
  };

  // Toggle aktif/nonaktif satu cabang (dengan konfirmasi)
  const handleToggleBranchStatus = (b) => {
    setConfirmState({
      title: b.is_active ? 'Nonaktifkan Cabang?' : 'Aktifkan Cabang?',
      message: b.is_active
        ? `Cabang ${b.code} - ${b.name} akan dinonaktifkan. Lanjutkan?`
        : `Cabang ${b.code} - ${b.name} akan diaktifkan kembali. Lanjutkan?`,
      onConfirm: async () => {
        setProcessingCode(b.code);
        try {
          await api.setBranchStatus(b.code, !b.is_active);
          notify.success(`Cabang ${b.code} berhasil ${!b.is_active ? 'diaktifkan' : 'dinonaktifkan'}`);
          await fetchData();
        } catch (e) {
          notify.error(e.response?.data?.detail || 'Gagal mengubah status cabang');
        } finally {
          setProcessingCode(null);
          setConfirmState(null);
        }
      },
    });
  };



  // ==========================================
  // RENDER
  // ==========================================
  if (loading) return <SkeletonTable rows={5} columns={4} />;

  return (
    <div className="space-y-6">
      {/* Toolbar: search kiri - switch tengah - aksi kanan */}
<div className="flex items-center gap-4 flex-wrap">
        <div className="relative w-full sm:w-64">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" size={16} />
          <input
            id="cb-search"
            type="text"
            placeholder="Cari kode, nama, atau host...  ( / )"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full pl-9 pr-8 py-2 border border-hairline rounded-md bg-canvas text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
          />
          {searchTerm && (
            <button type="button" onClick={() => setSearchTerm('')} aria-label="Bersihkan pencarian" className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted hover:text-ink">
              <X size={14} />
            </button>
          )}
        </div>

        <div className="ml-auto flex items-center gap-3">
          <div className="flex gap-2 border border-hairline rounded-md p-1 bg-surface-soft">
            <button onClick={() => { setActiveTab('companies'); setSearchTerm(''); }} className={`px-4 py-1.5 text-xs font-medium rounded transition-colors ${activeTab === 'companies' ? 'bg-primary text-white shadow-sm' : 'text-muted hover:text-ink'}`}>
              Perusahaan
            </button>
            <button onClick={() => { setActiveTab('branches'); setSearchTerm(''); }} className={`px-4 py-1.5 text-xs font-medium rounded transition-colors ${activeTab === 'branches' ? 'bg-primary text-white shadow-sm' : 'text-muted hover:text-ink'}`}>
              Cabang / Dealer
            </button>
          </div>
          {activeTab === 'companies' ? (
            <button onClick={() => { setEditingCompany(null); setShowCompanyModal(true); }}
              className="flex items-center gap-2 px-3 py-1.5 bg-primary text-white rounded-md text-xs hover:bg-primary-active whitespace-nowrap">
              <Plus size={14} /> Tambah Perusahaan
            </button>
          ) : (
            <button onClick={() => { setEditingBranch(null); setShowBranchModal(true); }}
              className="flex items-center gap-2 px-3 py-1.5 bg-primary text-white rounded-md text-xs hover:bg-primary-active whitespace-nowrap">
              <Plus size={14} /> Tambah Cabang
            </button>
          )}
        </div>
      </div>

      {activeTab === 'companies' && (
        <CompaniesTable
          paginatedCompanies={paginatedCompanies}
          totalCount={companies.length}
          filteredCount={filteredCompanies.length}
          page={companyPage}
          totalPages={companyTotalPages}
          onPageChange={setCompanyPage}
          pageSize={PAGE_SIZE}
          sortConfig={companySortConfig}
          onSort={handleCompanySort}
          processingCode={processingCode}
          onToggleRequest={handleToggleCompany}
          onEdit={(c) => { setEditingCompany(c); setShowCompanyModal(true); }}
          onDelete={handleDeleteCompany}
          onViewDetail={(c) => setDetailCompany(c)}
        />
      )}

      {activeTab === 'branches' && (
        <div className="bg-white rounded-xl border border-hairline shadow-sm p-4">
          <div className="flex justify-between items-center mb-3">
            <div>
              <h4 className="text-sm font-medium text-ink">Database Terdaftar</h4>
              <p className="text-xs text-muted">Kredensial didaftarkan sekali di sini; cabang tinggal memilih.</p>
            </div>
            <button onClick={() => { setEditingRegistry(null); setShowRegistryModal(true); }}
              className="flex items-center gap-2 px-3 py-1.5 bg-primary text-white rounded-md text-xs hover:bg-primary-active">
              <Plus size={14} /> Daftarkan Database
            </button>
          </div>
          {dbConnections.length === 0 ? (
            <p className="text-sm text-muted italic">Belum ada database terdaftar. Klik "Daftarkan Database" untuk mulai.</p>
          ) : (
            <ul className="flex flex-wrap gap-2">
              {dbConnections.map((c) => (
                <li key={c.id} className="group flex items-center gap-2 border border-hairline rounded-md px-3 py-1.5 bg-surface-soft">
                  <Database size={13} className={c.is_active ? 'text-success' : 'text-muted'} />
                  <span className="text-sm text-body">{c.name}</span>
                  <span className="text-xs text-muted">· dipakai {c.used_by} cabang</span>
                  {tenantData && Object.values(tenantData).some(t => t.db_connection_id === c.id) ? (
                    <span className="inline-flex items-center text-success text-xs"><CheckCircle size={12} /></span>
                  ) : null}
                  <span className="hidden group-hover:flex items-center gap-1 ml-1">
                    <button onClick={() => handleTestRegistry(c.id)} disabled={testing}
                      title="Test Koneksi" className="p-0.5 text-muted hover:text-primary disabled:opacity-50">
                      {testing ? <Loader2 size={12} className="animate-spin" /> : <Wifi size={12} />}
                    </button>
                    <button onClick={() => setEditingRegistry(c)} title="Edit"
                      className="p-0.5 text-muted hover:text-ink"><Pencil size={12} /></button>
                    <button onClick={() => handleDeleteRegistry(c)} title="Hapus"
                      className="p-0.5 text-muted hover:text-error"><Trash2 size={12} /></button>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {activeTab === 'branches' && (
        <BranchesTable
          paginatedBranches={paginatedBranches}
          filteredBranches={filteredBranches}
          companiesByCode={companiesByCode}
          connectionStatus={connectionStatus}
          tenantData={tenantData}
          page={branchPage}
          totalPages={branchTotalPages}
          onPageChange={setBranchPage}
          pageSize={PAGE_SIZE}
          sortConfig={branchSortConfig}
          onSort={handleBranchSort}
          processingCode={processingCode}
          tableContainerRef={tableContainerRef}
          onTestConnection={handleTestTenant}
          onConnectDb={(b) => setConnectDbBranch(b.code)}
          onViewDetail={(b) => setDetailBranch(b)}
          onToggleStatusRequest={handleToggleBranchStatus}
          dbConnectionsById={dbConnectionsById}
          onEditBranch={(b) => { setEditingBranch(b); setShowBranchModal(true); }}
          onDeleteBranch={handleDeleteBranch}
          dropdownOpen={dropdownOpen}
          setDropdownOpen={setDropdownOpen}
          dropdownPos={dropdownPos}
          setDropdownPos={setDropdownPos}
        />
      )}

      {/* ===== MODALS ===== */}
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

      {connectDbBranch && (
        <ConnectDbModal
          key={connectDbBranch}
          isOpen={!!connectDbBranch}
          onClose={() => setConnectDbBranch(null)}
          branchCode={connectDbBranch}
          currentConnId={tenantData[connectDbBranch]?.db_connection_id}
          onSaved={handleSaveConnectDb}
        />
      )}

      {showRegistryModal && (
        <DbConnectionModal
          key={editingRegistry?.id || 'new'}
          isOpen={showRegistryModal}
          onClose={() => { setShowRegistryModal(false); setEditingRegistry(null); }}
          onSave={handleSaveRegistry}
          editing={editingRegistry}
          isSaving={saving}
        />
      )}

      {detailCompany && (
        <CompanyDetailModal
          isOpen={!!detailCompany}
          onClose={() => setDetailCompany(null)}
          company={detailCompany}
          branches={data.branches}
          connectionStatus={connectionStatus}
        />
      )}

      {detailBranch && (
        <BranchDetailModal
          isOpen={!!detailBranch}
          onClose={() => setDetailBranch(null)}
          branch={detailBranch}
          companyName={companiesByCode[detailBranch.company_code]?.name}
          tenantData={tenantData}
          connectionStatus={connectionStatus}
        />
      )}

      {confirmState && (
        <ConfirmationDialog
          key="cbConfirm"
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
