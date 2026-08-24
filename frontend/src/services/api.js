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

  getBranchesWithTenants: async () => {
      const response = await apiClient.get('/admin/branches-with-tenants');
      return response.data;
  },
  
  getTenants: async () => {
    const response = await apiClient.get('/admin/tenants');
    return response.data;
  },
  getTenantByBranch: async (branch_code) => {
      const response = await apiClient.get(`/admin/tenants/${branch_code}`);
      return response.data;
    },
  createTenant: async (data) => {
    const response = await apiClient.post('/admin/tenants', data);
    return response.data;
  },
  testTenantConnection: async (branch_code, data) => {
    const response = await apiClient.post(`/admin/tenants/${branch_code}/test-connection`, data || {});
    return response.data;
  },
  testTenantDraft: async (data) => {
    const response = await apiClient.post('/admin/tenants/test-draft', data);
    return response.data;
  },

  // ==========================================
  // 4. ADMIN: AI CONFIGS & MODELS
  // ==========================================
  getAIConfigs: async () => {
    const response = await apiClient.get('/admin/ai-configs');
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