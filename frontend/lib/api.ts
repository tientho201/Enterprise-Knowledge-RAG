// ============================================================
// API Client — Centralized HTTP layer for Backend communication
// ============================================================

// Dùng 127.0.0.1 (không phải "localhost"): trên Windows, trình duyệt phân giải
// "localhost" thành IPv6 ::1 trong khi uvicorn chỉ bind IPv4 127.0.0.1 → "Failed
// to fetch". Ép IPv4 để khớp. Origin (localhost:3000) không đổi nên CORS vẫn OK.
const BASE_URL = "http://127.0.0.1:8000"; // Directly calls backend API

// ============================================================
// MOCK MODE — Set to true to bypass backend (dev/demo only)
// Credentials: admin@enterprise.com / admin123
// ============================================================
export const MOCK_MODE = false;

// --------------- Token helpers ---------------

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("access_token");
}

export function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("refresh_token");
}

export function setTokens(access: string, refresh: string) {
  localStorage.setItem("access_token", access);
  localStorage.setItem("refresh_token", refresh);
}

export function clearTokens() {
  localStorage.removeItem("access_token");
  localStorage.removeItem("refresh_token");
}

// --------------- Core fetch wrapper ---------------

let isRefreshing = false;
let refreshPromise: Promise<boolean> | null = null;

async function tryRefreshToken(): Promise<boolean> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) return false;

  try {
    const res = await fetch(`${BASE_URL}/api/v1/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });

    if (!res.ok) return false;

    const data = await res.json();
    setTokens(data.access_token, data.refresh_token);
    return true;
  } catch {
    return false;
  }
}

/**
 * Wrapper around fetch that:
 * 1. Attaches Authorization header automatically
 * 2. Auto-refreshes token on 401
 * 3. Throws ApiError with status + detail on failure
 */
export async function apiFetch(
  path: string,
  options: RequestInit = {},
  skipAuth = false
): Promise<Response> {
  const url = `${BASE_URL}${path}`;

  const headers = new Headers(options.headers || {});
  if (!skipAuth) {
    const token = getAccessToken();
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }
  }

  let res = await fetch(url, { ...options, headers });

  // If 401 and we have a refresh token, try to refresh
  if (res.status === 401 && !skipAuth) {
    // Deduplicate concurrent refresh attempts
    if (!isRefreshing) {
      isRefreshing = true;
      refreshPromise = tryRefreshToken().finally(() => {
        isRefreshing = false;
        refreshPromise = null;
      });
    }

    const refreshed = await (refreshPromise || Promise.resolve(false));

    if (refreshed) {
      // Retry original request with new token
      const newToken = getAccessToken();
      if (newToken) {
        headers.set("Authorization", `Bearer ${newToken}`);
      }
      res = await fetch(url, { ...options, headers });
    } else {
      // Refresh failed — clear tokens (caller should redirect to login)
      clearTokens();
    }
  }

  return res;
}

// --------------- Error helper ---------------

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail || body.message || JSON.stringify(body);
    } catch {
      // ignore parse errors
    }
    throw new ApiError(res.status, detail);
  }

  // 204 No Content
  if (res.status === 204) {
    return undefined as T;
  }

  return res.json();
}

// ============================================================
// API Types (matching backend responses)
// ============================================================

export interface AuthUser {
  id: string;
  email: string;
  full_name: string | null;
  role: "user" | "admin";
  is_active: boolean;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface Citation {
  chunk_id: string;
  document_id: string;
  document_name: string;
  page_number: number | null;
  section_title: string | null;
  source_link: string | null;
  content_snippet: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  citations: Citation[];
}

export interface ChatResponse {
  conversation_id: string;
  message: ChatMessage;
}

export interface ConversationSummary {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ConversationDetail {
  id: string;
  title: string | null;
  created_at: string;
  messages: ChatMessage[];
}

export interface Document {
  id: string;
  name: string;
  type: "pdf" | "docx" | "txt";
  status: "pending" | "processing" | "indexed" | "failed";
  version: number;
  source: string | null;
  file_size: number | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentListResponse {
  items: Document[];
  total: number;
  page: number;
  page_size: number;
}

export interface AdminDashboard {
  total_users: number;
  total_documents: number;
  total_conversations: number;
  total_messages: number;
  documents_by_status: {
    pending: number;
    processing: number;
    indexed: number;
    failed: number;
  };
}

// ============================================================
// Auth API
// ============================================================

export const authAPI = {
  async login(email: string, password: string): Promise<LoginResponse> {
    const res = await apiFetch("/api/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    }, true);
    return handleResponse<LoginResponse>(res);
  },

  async register(email: string, password: string, full_name?: string | null): Promise<AuthUser> {
    const res = await apiFetch("/api/v1/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, full_name: full_name || null }),
    }, true);
    return handleResponse<AuthUser>(res);
  },

  async me(): Promise<AuthUser> {
    const res = await apiFetch("/api/v1/auth/me");
    return handleResponse<AuthUser>(res);
  },
};

// ============================================================
// Chat API
// ============================================================

export const chatAPI = {
  async sendMessage(
    message: string,
    conversation_id?: string | null,
    search_tool?: boolean | null,
    document_ids?: string[] | null
  ): Promise<ChatResponse> {
    const res = await apiFetch("/api/v1/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        conversation_id: conversation_id || null,
        search_tool: search_tool !== undefined ? search_tool : null,
        documentIds: document_ids || null,
      }),
    });
    return handleResponse<ChatResponse>(res);
  },

  async getHistory(): Promise<ConversationSummary[]> {
    const res = await apiFetch("/api/v1/chat/history");
    return handleResponse<ConversationSummary[]>(res);
  },

  async getConversation(conversationId: string): Promise<ConversationDetail> {
    const res = await apiFetch(`/api/v1/chat/${conversationId}`);
    return handleResponse<ConversationDetail>(res);
  },

  async deleteConversation(conversationId: string): Promise<void> {
    const res = await apiFetch(`/api/v1/chat/${conversationId}`, {
      method: "DELETE",
    });
    return handleResponse<void>(res);
  },
};

// ============================================================
// Documents API
// ============================================================

export const documentsAPI = {
  async upload(file: File): Promise<Document> {
    const formData = new FormData();
    formData.append("file", file);

    const res = await apiFetch("/api/v1/documents/upload", {
      method: "POST",
      // Do NOT set Content-Type — browser auto-sets multipart/form-data with boundary
      body: formData,
    });
    return handleResponse<Document>(res);
  },

  async list(page = 1, page_size = 100): Promise<DocumentListResponse> {
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(page_size),
    });
    const res = await apiFetch(`/api/v1/documents?${params}`);
    return handleResponse<DocumentListResponse>(res);
  },

  async getById(docId: string): Promise<Document> {
    const res = await apiFetch(`/api/v1/documents/${docId}`);
    return handleResponse<Document>(res);
  },

  async delete(docId: string): Promise<void> {
    const res = await apiFetch(`/api/v1/documents/${docId}`, {
      method: "DELETE",
    });
    return handleResponse<void>(res);
  },

  async reindex(documentId: string): Promise<Document> {
    const res = await apiFetch("/api/v1/documents/reindex", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document_id: documentId }),
    });
    return handleResponse<Document>(res);
  },
};

// ============================================================
// Admin API
// ============================================================

export const adminAPI = {
  async dashboard(): Promise<AdminDashboard> {
    const res = await apiFetch("/api/v1/admin/dashboard");
    return handleResponse<AdminDashboard>(res);
  },

  async jobs(): Promise<{ active: any; reserved: any }> {
    const res = await apiFetch("/api/v1/admin/jobs");
    return handleResponse<{ active: any; reserved: any }>(res);
  },
};

// ============================================================
// Audit Logs API
// ============================================================

export interface BackendAuditLog {
  id: string;
  user_id: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  extra_data: { details?: string } | null;
  ip_address: string | null;
  created_at: string;
  updated_at: string;
}

export const auditLogsAPI = {
  async list(): Promise<BackendAuditLog[]> {
    const res = await apiFetch("/api/v1/audit-logs");
    return handleResponse<BackendAuditLog[]>(res);
  },

  async create(action: string, type?: string | null, details?: string | null): Promise<BackendAuditLog> {
    const res = await apiFetch("/api/v1/audit-logs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action,
        resource_type: type || null,
        extra_data: details ? { details } : null,
      }),
    });
    return handleResponse<BackendAuditLog>(res);
  },
};
