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
  deleteTenant: async (branchCode) => {
    const response = await apiClient.delete(`/admin/tenants/${branchCode}`);
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
  // Toggle Tier 2 (F2.6) per tenant — return { branch_code, chat_tier2 }
  setTenantTier2: async (branch_code, enabled) => {
    const response = await apiClient.post(`/admin/tenants/${branch_code}/tier2`, { enabled });
    return response.data;
  },
  // Set Mode AI per tenant (Opsi 1: vanna | tier2 | tier1)
  setTenantChatMode: async (branch_code, mode) => {
    const response = await apiClient.post(`/admin/tenants/${branch_code}/mode`, { mode });
    return response.data; // { branch_code, chat_mode, chat_tier2 }
  },
  // Knowledge Base tenant (F2.0) — lapisan semantik untuk AI
  getTenantKnowledgeBase: async (branchCode) => {
    const response = await apiClient.get(`/admin/tenants/${branchCode}/knowledge-base`);
    return response.data; // { branch_code, knowledge_base, updated_at, sumber }
  },
  saveTenantKnowledgeBase: async (branchCode, data) => {
    const response = await apiClient.put(`/admin/tenants/${branchCode}/knowledge-base`, data);
    return response.data; // { message, knowledge_base, perubahan }
  },
  validateTenantKnowledgeBase: async (branchCode, data) => {
    const response = await apiClient.post(`/admin/tenants/${branchCode}/knowledge-base/validate`, data);
    return response.data; // { ok, errors } — dry-run, tidak menyimpan
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
  getAIMetricsOverview: async () => {
    const response = await apiClient.get('/admin/ai-metrics/overview');
    return response.data;
  },
  getAIMetricsTimeline: async (days = 7) => {
    const response = await apiClient.get('/admin/ai-metrics/timeline', { params: { days } });
    return response.data;
  },
  getAIMetricsBranchUsage: async () => {
    const response = await apiClient.get('/admin/ai-metrics/branch-usage');
    return response.data;
  },
  updateBranchQuota: async (branchCode, dailyTokenQuota) => {
    const response = await apiClient.patch(`/admin/ai-metrics/branch-quota/${branchCode}`, {
      daily_token_quota: dailyTokenQuota,
    });
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

  // ==========================================
  // 5. CHAT USER (F4) — pipeline AI nyata
  // ==========================================
  // Jawaban: {source, confidence, sql, params, columns, rows, row_count,
  //           truncated, duration_ms, memory_id}
  // memory_id hanya terisi untuk jawaban baru (SQL memory pending) —
  // dipakai tombol feedback "Jawaban benar/salah".
  askAssistant: async (branchCode, question, conversationId = null, mode = 'auto') => {
    // Timeout 180 dtk (3 menit): mengakomodasi model penalaran / thinking AI
    const payload = { branch_code: branchCode, question, mode: (typeof mode === 'string' && mode) ? mode : 'auto' };
    if (conversationId) {
      payload.conversation_id = conversationId;
    }
    const response = await apiClient.post('/chat/query',
      payload, { timeout: 180000 });
    return response.data;
  },
  getConversations: async (branchCode) => {
    const response = await apiClient.get('/chat/conversations', {
      params: { branch_code: branchCode },
    });
    return response.data;
  },
  getConversationMessages: async (conversationId) => {
    const response = await apiClient.get(`/chat/conversations/${conversationId}`);
    return response.data;
  },
  deleteConversation: async (conversationId) => {
    const response = await apiClient.delete(`/chat/conversations/${conversationId}`);
    return response.data;
  },
  clearAllConversations: async (branchCode) => {
    const response = await apiClient.delete('/chat/conversations', {
      params: { branch_code: branchCode },
    });
    return response.data;
  },
  // Riwayat percakapan lama / default:
  fetchChatHistory: async (branchCode) => {
    const response = await apiClient.get('/chat/history',
      { params: { branch_code: branchCode } });
    return response.data;
  },
  // Feedback jawaban (F4): hanya berlaku bila response punya memory_id.
  // Return {ok, status}; 409 bila transisi status dilarang.
  confirmMemory: async (branchCode, memoryId) => {
    const response = await apiClient.post('/chat/confirm-memory',
      { branch_code: branchCode, memory_id: memoryId });
    return response.data;
  },
  rejectMemory: async (branchCode, memoryId) => {
    const response = await apiClient.post('/chat/reject-memory',
      { branch_code: branchCode, memory_id: memoryId });
    return response.data;
  },
  explainChat: async ({ branchCode, question, sql, rows }) => {
    const response = await apiClient.post('/chat/explain', {
      branch_code: branchCode,
      question,
      sql,
      rows,
    });
    return response.data;
  },
  trainVanna: async ({ branchCode, question, sql }) => {
    const response = await apiClient.post('/chat/train', {
      branch_code: branchCode,
      question,
      sql,
    });
    return response.data;
  },
  exportExcel: async ({ branchCode, question, tabName, rows, columns }) => {
    const response = await apiClient.post('/chat/export-excel', {
      branch_code: branchCode,
      question,
      tab_name: tabName,
      rows,
      columns,
    }, {
      responseType: 'blob',
    });
    return response;
  },

  // ==========================================
  // 6. ADMIN: GLOBAL KNOWLEDGE BASE (F3/F3.1)
  // ==========================================
  getGlobalKBStats: async () => {
    const response = await apiClient.get('/admin/global-kb/stats');
    return response.data;
  },
  getGlobalKBItems: async ({ kind, q, limit = 25, offset = 0 } = {}) => {
    const params = { limit, offset };
    if (kind) params.kind = kind;
    if (q) params.q = q;
    const response = await apiClient.get('/admin/global-kb/items', { params });
    return response.data;
  },
  getGlobalKBItem: async (id) => {
    const response = await apiClient.get(`/admin/global-kb/items/${id}`);
    return response.data;
  },
  createGlobalKBItem: async (data) => {
    const response = await apiClient.post('/admin/global-kb/items', data);
    return response.data;
  },
  updateGlobalKBItem: async (id, data) => {
    const response = await apiClient.put(`/admin/global-kb/items/${id}`, data);
    return response.data;
  },
  deleteGlobalKBItem: async (id) => {
    const response = await apiClient.delete(`/admin/global-kb/items/${id}`);
    return response.data;
  },
  syncGlobalKB: async () => {
    const response = await apiClient.post('/admin/global-kb/sync');
    return response.data;
  },
};