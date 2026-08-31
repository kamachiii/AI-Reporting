import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Interceptor untuk menyisipkan token JWT ke setiap request
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Interceptor response: sesi kadaluarsa / tidak valid -> auto logout.
// Pengecualian: 401 dari endpoint login sendiri (salah password) TIDAK memicu logout.
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const isLoginCall = error.config?.url?.includes('/auth/login');
    if (error.response?.status === 401 && !isLoginCall) {
      localStorage.removeItem('access_token');
      localStorage.removeItem('user_data');
      sessionStorage.setItem('session_expired', '1');
      window.location.reload();
    }
    return Promise.reject(error);
  }
);

export const api = {
  // ==========================================
  // 1. AUTH
  // ==========================================
  login: async (username, password) => {
    const response = await apiClient.post('/auth/login', { username, password });
    return response.data;
  },

  // ==========================================
  // 2. ADMIN: COMPANY, BRANCH, & TENANT
  // ==========================================
  getCompanies: async () => {
    const response = await apiClient.get('/admin/companies');
    return response.data;
  },
  createCompany: async (data) => {
    const response = await apiClient.post('/admin/companies', data);
    return response.data;
  },
  updateCompany: async (code, data) => {
    const response = await apiClient.put(`/admin/companies/${code}`, data);
    return response.data;
  },
  deleteCompany: async (code) => {
    const response = await apiClient.delete(`/admin/companies/${code}`);
    return response.data;
  },

  getBranches: async () => {
    const response = await apiClient.get('/admin/branches');
    return response.data;
  },
  getBranchesWithTenants: async () => {
    const response = await apiClient.get('/admin/branches-with-tenants');
    return response.data;
  },
  createBranch: async (data) => {
    const response = await apiClient.post('/admin/branches', data);
    return response.data;
  },
  updateBranch: async (code, data) => {
    const response = await apiClient.put(`/admin/branches/${code}`, data);
    return response.data;
  },
  deleteBranch: async (code) => {
    const response = await apiClient.delete(`/admin/branches/${code}`);
    return response.data;
  },

  getTenants: async () => {
    const response = await apiClient.get('/admin/tenants');
    return response.data;
  },
  // Registry Database (kredensial didaftarkan sekali, cabang tinggal pilih)
  getDbConnections: async () => {
    const response = await apiClient.get('/admin/db-connections');
    return response.data;
  },
  createDbConnection: async (data) => {
    const response = await apiClient.post('/admin/db-connections', data);
    return response.data;
  },
  updateDbConnection: async (id, data) => {
    const response = await apiClient.put(`/admin/db-connections/${id}`, data);
    return response.data;
  },
  deleteDbConnection: async (id) => {
    const response = await apiClient.delete(`/admin/db-connections/${id}`);
    return response.data;
  },
  testDbConnection: async (id) => {
    const response = await apiClient.post(`/admin/db-connections/${id}/test-connection`);
    return response.data;
  },
  testAllDbConnections: async () => {
    const response = await apiClient.post('/admin/db-connections/test-all');
    return response.data; // { "<id>": {status, message} }
  },
  createTenant: async (data) => {
    const response = await apiClient.post('/admin/tenants', data);
    return response.data;
  },
  updateTenantDb: async (branchCode, dbConnectionId) => {
    const response = await apiClient.put(`/admin/tenants/${branchCode}`, { branch_code: branchCode, db_connection_id: dbConnectionId });
    return response.data;
  },
  setBranchStatus: async (code, isActive) => {
    const response = await apiClient.put(`/admin/branches/${code}/status`, { is_active: isActive });
    return response.data;
  },
  testTenantConnection: async (branch_code, data) => {
    const response = await apiClient.post(`/admin/tenants/${branch_code}/test-connection`, data || {});
    return response.data;
  },
  refreshTenantSchema: async (branch_code) => {
    const response = await apiClient.post(`/admin/tenants/${branch_code}/refresh-schema`);
    return response.data; // { message, tables, columns }
  },

  // ==========================================
  // 3. ADMIN: USERS
  // ==========================================
  getUsers: async () => {
    const response = await apiClient.get('/admin/users');
    return response.data;
  },
  createUser: async (data) => {
    const response = await apiClient.post('/admin/users', data);
    return response.data;
  },
  updateUser: async (id, data) => {
    const response = await apiClient.put(`/admin/users/${id}`, data);
    return response.data;
  },
  setUserStatus: async (id, is_active) => {
    const response = await apiClient.put(`/admin/users/${id}/status`, { is_active });
    return response.data;
  },
  deleteUser: async (id) => {
    const response = await apiClient.delete(`/admin/users/${id}`);
    return response.data;
  },

  // ==========================================
  // 4. ADMIN: AI CONFIGS & MODELS
  // ==========================================
  getAIConfigs: async () => {
    const response = await apiClient.get('/admin/ai-configs');
    return response.data;
  },
  getAuditLogs: async (params = {}) => {
    const response = await apiClient.get('/admin/audit-logs', { params });
    return response.data;
  },
  createAIConfig: async (data) => {
    const response = await apiClient.post('/admin/ai-configs', data);
    return response.data;
  },
  updateAIConfig: async (id, data) => {
    const response = await apiClient.put(`/admin/ai-configs/${id}`, data);
    return response.data;
  },
  deleteAIConfig: async (id) => {
    const response = await apiClient.delete(`/admin/ai-configs/${id}`);
    return response.data;
  },
  testAIConfig: async (id) => {
    const response = await apiClient.post(`/admin/ai-configs/${id}/test`);
    return response.data;
  },
  testAllAIConfigs: async () => {
    const response = await apiClient.post('/admin/ai-configs/test-all');
    return response.data; // { "<id>": {status, message} }
  },
  fetchProviderModels: async (provider, api_key, api_type, base_url, config_id) => {
    const response = await apiClient.post('/admin/ai-providers/models', { 
      provider, api_key, api_type, base_url, config_id 
    });
    return response.data;
  },
  testAIConfigDraft: async (api_type, base_url, api_key, config_id) => {
    const response = await apiClient.post('/admin/ai-configs/test-draft', { 
      api_type, base_url, api_key, config_id 
    });
    return response.data;
  },
};