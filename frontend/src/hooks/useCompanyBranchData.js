import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { api } from '../services/api';
import { notify } from '../utils/notification';
import useDebounce from './useDebounce';

/**
 * Sumber data tunggal untuk CompanyBranchesTab:
 * companies, branches (+ tenant & status koneksi nyata), search debounce,
 * filter/sort/pagination untuk kedua sub-tabel.
 *
 * Dipakai bersama CompaniesTable dan BranchesTable agar tidak ada
 * duplikasi state/logika antar dua tabel.
 */
export default function useCompanyBranchData() {
  const [companies, setCompanies] = useState([]);
  const [branches, setBranches] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const debouncedSearch = useDebounce(searchTerm, 300);

  const [connectionStatus, setConnectionStatus] = useState({});
  const [tenantData, setTenantData] = useState({});
  const [dbConnections, setDbConnections] = useState([]);
  const [dbConnectionsById, setDbConnectionsById] = useState({});

  const tableContainerRef = useRef(null);
  const PAGE_SIZE = 15;

  const fetchData = useCallback(async () => {
    const scrollTop = tableContainerRef.current?.scrollTop || 0;
    setLoading(true);
    try {
      const [companiesData, branchesData, connectionsData] = await Promise.all([
        api.getCompanies(),
        api.getBranches(),
        api.getDbConnections(),
      ]);
      setCompanies(companiesData || []);
      setDbConnections(connectionsData || []);

      const byId = {};
      (connectionsData || []).forEach(c => { byId[c.id] = c; });
      setDbConnectionsById(byId);

      // Tenant aktif per cabang (model baru: penunjuk ke registry)
      const tenantsData = await api.getTenants();
      const tenantsByBranch = {};
      (tenantsData || []).forEach(t => { tenantsByBranch[t.branch_code] = t; });
      setTenantData(tenantsByBranch);

      const statuses = {};
      const formattedBranches = (branchesData || []).map(b => ({
        code: b.code,
        name: b.name,
        company_code: b.company_code,
        address: b.address,
        is_active: b.is_active,
      }));

      Object.keys(tenantsByBranch).forEach(code => { statuses[code] = 'checking'; });

      setBranches(formattedBranches);
      // Set awal; hasil tes nyata menimpa per baris di bawah
      setConnectionStatus(statuses);

      // Status koneksi NYATA (paralel)
      Object.keys(tenantsByBranch).forEach(async (code) => {
        try {
          const result = await api.testTenantConnection(code);
          setConnectionStatus(prev => ({ ...prev, [code]: result.status }));
        } catch {
          setConnectionStatus(prev => ({ ...prev, [code]: 'disconnected' }));
        }
      });
    } catch {
      notify.error('Gagal memuat data perusahaan & cabang');
    } finally {
      setLoading(false);
      setTimeout(() => {
        if (tableContainerRef.current) {
          tableContainerRef.current.scrollTop = scrollTop;
        }
      }, 0);
    }
  }, []);

  useEffect(() => {
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---------- FILTER / SORT / PAGINATION ----------
  const companiesByCode = useMemo(() => {
    const map = {};
    companies.forEach(c => map[c.code] = c);
    return map;
  }, [companies]);

  const filteredCompanies = useMemo(() => {
    if (!debouncedSearch) return companies;
    const lower = debouncedSearch.toLowerCase();
    return companies.filter(c =>
      (c.code || '').toLowerCase().includes(lower) ||
      (c.name || '').toLowerCase().includes(lower)
    );
  }, [companies, debouncedSearch]);

  const filteredBranches = useMemo(() => {
    if (!debouncedSearch) return branches;
    const lower = debouncedSearch.toLowerCase();
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
  }, [branches, debouncedSearch, companiesByCode, tenantData]);

  // Company sort/paginate
  const [companySortConfig, setCompanySortConfig] = useState({ key: 'code', direction: 'asc' });
  const handleCompanySort = (key) => {
    let direction = 'asc';
    if (companySortConfig.key === key && companySortConfig.direction === 'asc') direction = 'desc';
    setCompanySortConfig({ key, direction });
  };
  const sortedCompanies = useMemo(() => {
    const sorted = [...filteredCompanies];
    return sorted.sort((a, b) => {
      const aVal = a[companySortConfig.key] ?? '';
      const bVal = b[companySortConfig.key] ?? '';
      if ((aVal === true || aVal === false)) {
        // boolean sort (is_active)
        const av = aVal ? 1 : 0, bv = bVal ? 1 : 0;
        return companySortConfig.direction === 'asc' ? av - bv : bv - av;
      }
      if (aVal < bVal) return companySortConfig.direction === 'asc' ? -1 : 1;
      if (aVal > bVal) return companySortConfig.direction === 'asc' ? 1 : -1;
      return 0;
    });
  }, [filteredCompanies, companySortConfig]);

  const [companyPage, setCompanyPage] = useState(1);
  const companyTotalPages = Math.max(1, Math.ceil(sortedCompanies.length / PAGE_SIZE));
  useEffect(() => { setCompanyPage(1); }, [debouncedSearch]);
  const safeCompanyPage = Math.min(companyPage, companyTotalPages);
  const paginatedCompanies = useMemo(() => {
    const start = (safeCompanyPage - 1) * PAGE_SIZE;
    return sortedCompanies.slice(start, start + PAGE_SIZE);
  }, [sortedCompanies, safeCompanyPage]);

  // Branch sort/paginate
  const [branchSortConfig, setBranchSortConfig] = useState({ key: 'code', direction: 'asc' });
  const handleBranchSort = (key) => {
    let direction = 'asc';
    if (branchSortConfig.key === key && branchSortConfig.direction === 'asc') direction = 'desc';
    setBranchSortConfig({ key, direction });
  };
  const sortedBranches = useMemo(() => {
    const sorted = [...filteredBranches];
    return sorted.sort((a, b) => {
      let aVal = a[branchSortConfig.key] ?? '';
      let bVal = b[branchSortConfig.key] ?? '';

      if (branchSortConfig.key === 'company_code') {
        aVal = companiesByCode[a.company_code]?.name || a.company_code;
        bVal = companiesByCode[b.company_code]?.name || b.company_code;
      }
      if (branchSortConfig.key === 'db') {
        aVal = tenantData[a.code]?.db_name_label || '';
        bVal = tenantData[b.code]?.db_name_label || '';
      }
      if (branchSortConfig.key === 'status_branch') {
        aVal = a.is_active ? 1 : 0;
        bVal = b.is_active ? 1 : 0;
      }

      if (aVal < bVal) return branchSortConfig.direction === 'asc' ? -1 : 1;
      if (aVal > bVal) return branchSortConfig.direction === 'asc' ? 1 : -1;
      return 0;
    });
  }, [filteredBranches, branchSortConfig, companiesByCode, connectionStatus]);

  const [branchPage, setBranchPage] = useState(1);
  const branchTotalPages = Math.max(1, Math.ceil(sortedBranches.length / PAGE_SIZE));
  useEffect(() => { setBranchPage(1); }, [debouncedSearch]);
  const safeBranchPage = Math.min(branchPage, branchTotalPages);
  const paginatedBranches = useMemo(() => {
    const start = (safeBranchPage - 1) * PAGE_SIZE;
    return sortedBranches.slice(start, start + PAGE_SIZE);
  }, [sortedBranches, safeBranchPage]);

  return {
    // data
    companies, branches, loading, fetchData,
    tenantData, connectionStatus, dbConnections, dbConnectionsById,
    companiesByCode, tableContainerRef,
    // search
    searchTerm, setSearchTerm, debouncedSearch,
    // company list
    paginatedCompanies, companyPage, setCompanyPage, companyTotalPages, filteredCompanies,
    companySortConfig, handleCompanySort,
    // branch list
    paginatedBranches, branchPage, setBranchPage, branchTotalPages, filteredBranches,
    branchSortConfig, handleBranchSort,
    PAGE_SIZE,
  };
}
