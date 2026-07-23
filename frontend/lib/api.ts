// ============================================================
// API Client — Centralized HTTP layer for Backend communication
// ============================================================

// URL backend API. Local dev: fallback 127.0.0.1 (không dùng "localhost" — trên
// Windows trình duyệt phân giải "localhost" thành IPv6 ::1 trong khi uvicorn chỉ
// bind IPv4 127.0.0.1 → "Failed to fetch"). Production: set NEXT_PUBLIC_API_URL
// trong Vercel (Settings → Environment Variables) trỏ đúng URL Render.
// PHẢI có prefix NEXT_PUBLIC_ để Next.js inline giá trị vào bundle client lúc build.
const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

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
  // Khớp UserRole ở backend (models/user.py) — trước đây sai thành "user"|"admin"
  // (giá trị "user" backend không bao giờ trả), sửa lại cho đúng khi thêm quản lý
  // role cho admin.
  role: "admin" | "editor" | "viewer";
  is_active: boolean;
  plan: "free" | "pro";
  // Computed ở backend (role=admin luôn true, bất kể plan) — dùng field này để
  // khoá/mở nút "Nâng cao", KHÔNG tự suy luận role/plan ở client.
  can_use_advanced_search: boolean;
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

export interface ConversationRef {
  id: string;
  title: string | null;
}

export interface Document {
  id: string;
  name: string;
  type: "pdf" | "docx" | "txt";
  status: "pending" | "processing" | "indexed" | "failed";
  version: number;
  source: string | null;
  file_size: number | null;
  is_active: boolean;
  conversations: ConversationRef[];
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

  // Self-service demo — KHÔNG có cổng thanh toán thật đứng sau (chưa nối Stripe...).
  // Đổi plan của chính user đang đăng nhập.
  async updatePlan(plan: "free" | "pro"): Promise<AuthUser> {
    const res = await apiFetch("/api/v1/auth/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan }),
    });
    return handleResponse<AuthUser>(res);
  },
};

// ============================================================
// Chat API
// ============================================================

export interface StreamCallbacks {
  onMeta?: (conversationId: string) => void;
  onDelta?: (text: string) => void;
  onDone?: (data: { conversation_id: string; message_id: string; citations: Citation[] }) => void;
  onError?: (detail: string) => void;
}

export const chatAPI = {
  // Streaming (SSE): câu trả lời hiện dần token-by-token. FE cập nhật nội dung tin
  // nhắn khi từng `delta` về, gắn citations lúc `done`.
  async sendMessageStream(
    message: string,
    conversation_id: string | null | undefined,
    search_tool: boolean | null | undefined,
    document_ids: string[] | null | undefined,
    cb: StreamCallbacks,
    options?: {
      topK?: number | null;
      similarityThreshold?: number | null;
      systemPrompt?: string | null;
      // Model tùy chỉnh (BYOM) — chỉ áp dụng khi apiKey có giá trị, xem panel Cấu hình.
      // apiKey đi thẳng lên backend theo từng request, KHÔNG lưu ở server.
      model?: string | null;
      apiKey?: string | null;
      baseUrl?: string | null;
      // Chế độ tra cứu chọn ở panel Cấu hình. "advanced" bị backend gate theo plan
      // (403 nếu free) — xem core/plan_gate.py. Không gửi -> hành vi mặc định hiện tại.
      searchMode?: "hybrid" | "vector" | "keyword" | "advanced" | null;
    }
  ): Promise<void> {
    const res = await apiFetch("/api/v1/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        conversation_id: conversation_id || null,
        search_tool: search_tool !== undefined ? search_tool : null,
        documentIds: document_ids || null,
        topK: options?.topK ?? null,
        similarityThreshold: options?.similarityThreshold ?? null,
        // rỗng/undefined → backend tự dùng SYSTEM_PROMPT mặc định.
        systemPrompt:
          options?.systemPrompt && options.systemPrompt.trim().length > 0
            ? options.systemPrompt
            : null,
        model: options?.apiKey ? options?.model || null : null,
        apiKey: options?.apiKey || null,
        baseUrl: options?.apiKey ? options?.baseUrl || null : null,
        searchMode: options?.searchMode ?? null,
      }),
    });

    if (!res.ok || !res.body) {
      let detail = `HTTP ${res.status}`;
      try {
        const body = await res.json();
        detail = body.detail || detail;
      } catch {
        // response không phải JSON (vd lỗi mạng) — giữ message mặc định
      }
      cb.onError?.(detail);
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";

    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      // Sự kiện SSE ngăn cách bởi \n\n
      const parts = buf.split("\n\n");
      buf = parts.pop() || "";
      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith("data:")) continue;
        let payload: { type: string; [k: string]: unknown };
        try {
          payload = JSON.parse(line.slice(5).trim());
        } catch {
          continue;
        }
        switch (payload.type) {
          case "meta":
            cb.onMeta?.(payload.conversation_id as string);
            break;
          case "delta":
            cb.onDelta?.(payload.text as string);
            break;
          case "done":
            cb.onDone?.(
              payload as unknown as {
                conversation_id: string;
                message_id: string;
                citations: Citation[];
              }
            );
            break;
          case "error":
            cb.onError?.(payload.detail as string);
            break;
        }
      }
    }
  },

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
  async upload(file: File, conversationId?: string | null): Promise<Document> {
    const formData = new FormData();
    formData.append("file", file);
    // Gắn tài liệu vào hội thoại (upload từ màn chat). Bỏ qua khi upload ở kho tổng.
    if (conversationId) {
      formData.append("conversation_id", conversationId);
    }

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

  async setActive(docId: string, isActive: boolean): Promise<Document> {
    const res = await apiFetch(`/api/v1/documents/${docId}/active`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_active: isActive }),
    });
    return handleResponse<Document>(res);
  },

  // Gắn thêm 1 hội thoại vào tài liệu, giữ nguyên các liên kết đã có.
  async addConversation(docId: string, conversationId: string): Promise<Document> {
    const res = await apiFetch(`/api/v1/documents/${docId}/conversations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_id: conversationId }),
    });
    return handleResponse<Document>(res);
  },

  // Thay toàn bộ hội thoại gắn với tài liệu. [] → gỡ hết, đưa về kho tổng.
  async setConversations(docId: string, conversationIds: string[]): Promise<Document> {
    const res = await apiFetch(`/api/v1/documents/${docId}/conversations`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_ids: conversationIds }),
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

  async listUsers(): Promise<AuthUser[]> {
    const res = await apiFetch("/api/v1/admin/users");
    return handleResponse<AuthUser[]>(res);
  },

  async updateUserRole(userId: string, role: "admin" | "editor" | "viewer"): Promise<AuthUser> {
    const res = await apiFetch(`/api/v1/admin/users/${userId}/role`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role }),
    });
    return handleResponse<AuthUser>(res);
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
