import { useState } from 'react';
import { X, Search } from 'lucide-react';
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
import TenantModal from './tenants/TenantModal';
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
  const [showTenantModal, setShowTenantModal] = useState(false);
  const [editingCompany, setEditingCompany] = useState(null);
  const [editingBranch, setEditingBranch] = useState(null);
  const [editingTenantBranch, setEditingTenantBranch] = useState(null);

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
      else if (showTenantModal) setShowTenantModal(false);
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
  const handleTestTenant = async (branch_code, form) => {
    setTesting(true);
    try {
      return await api.testTenantConnection(branch_code, form);
    } catch {
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
      notify.error(e.response?.data?.detail || 'Gagal menyimpan konfigurasi database');
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
        } catch {
          notify.error('Gagal memutus koneksi database');
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
      {/* Global Search */}
      <div className="flex justify-between items-center gap-4 flex-wrap">
        <div className="relative flex-1 max-w-sm">
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
            <button type="button" onClick={() => setSearchTerm('')} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted hover:text-ink">
              <X size={14} />
            </button>
          )}
        </div>
      </div>

      {/* Segmented Control */}
      <div className="flex gap-2 border border-hairline rounded-md p-1 bg-surface-soft w-fit">
        <button onClick={() => setActiveTab('companies')} className={`px-4 py-1.5 text-xs font-medium rounded transition-colors ${activeTab === 'companies' ? 'bg-primary text-white shadow-sm' : 'text-muted hover:text-ink'}`}>
          Perusahaan
        </button>
        <button onClick={() => setActiveTab('branches')} className={`px-4 py-1.5 text-xs font-medium rounded transition-colors ${activeTab === 'branches' ? 'bg-primary text-white shadow-sm' : 'text-muted hover:text-ink'}`}>
          Cabang / Dealer
        </button>
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
          onAdd={() => { setEditingCompany(null); setShowCompanyModal(true); }}
          onViewDetail={(c) => setDetailCompany(c)}
        />
      )}

      {activeTab === 'branches' && (
        <BranchesTable
          paginatedBranches={paginatedBranches}
          totalCount={data.branches.length}
          filteredCount={filteredBranches.length}
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
          onDisconnect={handleDisconnectTenant}
          onConnectDb={(b) => { setEditingTenantBranch(b.code); setShowTenantModal(true); }}
          onEditTenant={(code) => { setEditingTenantBranch(code); setShowTenantModal(true); }}
          onViewDetail={(b) => setDetailBranch(b)}
          onEditBranch={(b) => { setEditingBranch(b); setShowBranchModal(true); }}
          onDeleteBranch={handleDeleteBranch}
          onAddBranch={() => { setEditingBranch(null); setShowBranchModal(true); }}
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
