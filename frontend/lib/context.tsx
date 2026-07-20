"use client"

import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from "react"
import {
  authAPI,
  chatAPI,
  documentsAPI,
  auditLogsAPI,
  clearTokens,
  getAccessToken,
  setTokens,
  ApiError,
  MOCK_MODE,
  type AuthUser,
  type Document,
  type ConversationSummary,
  type ChatMessage,
  type Citation,
} from "./api"

// ============================================================
// Interfaces
// ============================================================

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  isStreaming?: boolean;
  timestamp: string;
  citations?: Citation[];
}

export interface User {
  id: string;
  name: string;
  email: string;
  role: "user" | "admin";
  avatarUrl?: string;
}

export interface ChatSession {
  id: string;        // conversation_id from backend, or "new-<timestamp>" for unsaved
  title: string;
  messages: Message[];
  messageCount?: number;
  isLoaded?: boolean; // whether full messages are loaded from API
}

export interface CustomModel {
  id: string;
  name: string;
  apiKey: string;
  provider?: string;
}

export interface AuditLog {
  id: string;
  action: string;
  type: "upload" | "query" | "research" | "config";
  timestamp: string;
  details?: string;
}

export interface SavedResearch {
  id: string;
  title: string;
  content: string;
  date: string;
  docIds: string[];
}

export interface RagSettings {
  searchMode: string;
  model: string;
  topK: number;
  similarityThreshold: number;
  systemPrompt: string;
}

interface AppContextType {
  documents: Document[];
  setDocuments: React.Dispatch<React.SetStateAction<Document[]>>;
  activeDocs: string[];
  setActiveDocs: React.Dispatch<React.SetStateAction<string[]>>;
  chatSessions: ChatSession[];
  setChatSessions: React.Dispatch<React.SetStateAction<ChatSession[]>>;
  activeSessionId: string;
  setActiveSessionId: React.Dispatch<React.SetStateAction<string>>;
  activeSession: ChatSession;
  customModels: CustomModel[];
  setCustomModels: React.Dispatch<React.SetStateAction<CustomModel[]>>;
  ragSettings: RagSettings;
  setRagSettings: React.Dispatch<React.SetStateAction<RagSettings>>;
  uploadProgress: {
    fileName: string;
    progress: number;
    stepText: string;
    isUploading: boolean;
  } | null;
  setUploadProgress: React.Dispatch<React.SetStateAction<any>>;
  showLeftSidebar: boolean;
  setShowLeftSidebar: React.Dispatch<React.SetStateAction<boolean>>;
  showRightPanel: boolean;
  setShowRightPanel: React.Dispatch<React.SetStateAction<boolean>>;
  rightPanelTab: "docs" | "settings";
  setRightPanelTab: React.Dispatch<React.SetStateAction<"docs" | "settings">>;
  auditLogs: AuditLog[];
  addAuditLog: (action: string, type: AuditLog["type"], details?: string) => void;
  savedResearch: SavedResearch[];
  addSavedResearch: (title: string, content: string, docIds: string[]) => void;
  handleNewChat: () => void;
  handleDeleteSession: (id: string, e?: React.MouseEvent) => void;
  handleSendMessage: (messageText: string, searchTool?: boolean | null) => void;
  isLlmGenerating: boolean;
  setIsLlmGenerating: React.Dispatch<React.SetStateAction<boolean>>;
  showRagProcessId: string | null;
  setShowRagProcessId: React.Dispatch<React.SetStateAction<string | null>>;
  processFile: (file: File) => Promise<void>;
  deleteDocument: (docId: string) => Promise<void>;
  reindexDocument: (docId: string) => Promise<void>;
  loadConversation: (conversationId: string) => Promise<void>;
  user: User | null;
  isAuthLoading: boolean;
  login: (email: string, password: string) => Promise<{ success: boolean; error?: string }>;
  register: (name: string, email: string, password: string) => Promise<{ success: boolean; error?: string }>;
  logout: () => void;
  refreshDocuments: () => Promise<void>;
  refreshChatHistory: () => Promise<void>;
  refreshAuditLogs: () => Promise<void>;
}

const AppContext = createContext<AppContextType | undefined>(undefined)

// ============================================================
// Helper: Preprocess citations in raw content from backend
// ============================================================
export function preprocessCitations(content: string, citations?: Citation[]): string {
  if (!content) return "";
  if (!citations || citations.length === 0) return content;
  // Match [SOURCE: chunk_id] or [SOURCE: chunk-id] or [SOURCE: web_id] case-insensitive
  return content.replace(/\[SOURCE:\s*([^\]]+)\]/gi, (match, chunkId) => {
    const citation = citations.find(c => c.chunk_id === chunkId);
    if (citation) {
      // Build a premium label format: "Document Name - Section / Page / Detail"
      if (chunkId.toLowerCase().startsWith("web_")) {
        const label = `Web - ${citation.document_name}`;
        return `[${label}](#cite-${chunkId})`;
      } else {
        const section = citation.section_title || (citation.page_number ? `Trang ${citation.page_number}` : 'Chi tiết');
        const label = `${citation.document_name} - ${section}`;
        return `[${label}](#cite-${chunkId})`;
      }
    }
    return `[Nguồn - ${chunkId}](#cite-${chunkId})`;
  });
}

// ============================================================
// Helper: Map backend user to frontend User
// ============================================================
function mapAuthUser(u: AuthUser): User {
  return {
    id: u.id,
    name: u.full_name || u.email.split("@")[0],
    email: u.email,
    role: u.role,
    avatarUrl: `https://api.dicebear.com/7.x/initials/svg?seed=${encodeURIComponent(u.full_name || u.email)}`,
  }
}

// ============================================================
// Default empty session
// ============================================================
function createEmptySession(): ChatSession {
  return {
    id: `new-${Date.now()}`,
    title: "Hội thoại mới",
    messages: [],
    isLoaded: true,
  }
}

// ============================================================
// Provider
// ============================================================
export function AppContextProvider({ children }: { children: React.ReactNode }) {
  // --- States ---
  const [documents, setDocuments] = useState<Document[]>([])
  const [activeDocs, setActiveDocs] = useState<string[]>([])

  const [chatSessions, setChatSessions] = useState<ChatSession[]>([createEmptySession()])
  const [activeSessionId, setActiveSessionId] = useState<string>(chatSessions[0]?.id || "")

  const [customModels, setCustomModels] = useState<CustomModel[]>([])
  const [showLeftSidebar, setShowLeftSidebar] = useState<boolean>(true)
  const [showRightPanel, setShowRightPanel] = useState<boolean>(true)
  const [rightPanelTab, setRightPanelTab] = useState<"docs" | "settings">("docs")
  const [isLlmGenerating, setIsLlmGenerating] = useState<boolean>(false)
  const [showRagProcessId, setShowRagProcessId] = useState<string | null>(null)

  const [ragSettings, setRagSettings] = useState<RagSettings>({
    searchMode: "Lai (Hybrid)",
    model: "Gemini 1.5 Flash",
    topK: 4,
    similarityThreshold: 0.25,
    systemPrompt: "Bạn là trợ lý pháp lý AI chuyên nghiệp của doanh nghiệp. Hãy dùng các tài liệu được cung cấp dưới đây để trả lời câu hỏi một cách trung thực và chính xác. Trích dẫn rõ ràng Điều, Khoản và Tên tài liệu khi trả lời. Nếu không tìm thấy thông tin trong tài liệu, hãy báo cho người dùng biết."
  })

  const [uploadProgress, setUploadProgress] = useState<{
    fileName: string;
    progress: number;
    stepText: string;
    isUploading: boolean;
  } | null>(null)

  // --- Auth State ---
  const [user, setUser] = useState<User | null>(null)
  const [isAuthLoading, setIsAuthLoading] = useState<boolean>(true)

  // Audit Logs (client-side only)
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([])

  // Saved Research (client-side only)
  const [savedResearch, setSavedResearch] = useState<SavedResearch[]>([])

  // Track if initial data has been loaded
  const initializedRef = useRef(false)

  // ============================================================
  // Audit Logs
  // ============================================================
  const addAuditLog = useCallback((action: string, type: AuditLog["type"], details?: string) => {
    const newLog: AuditLog = {
      id: `log-${Date.now()}`,
      action,
      type,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
      details
    }
    setAuditLogs(prev => [newLog, ...prev])

    // Save to backend database (Supabase) if authenticated
    // Skip "query" and "upload" types because they are automatically logged by backend services
    if (getAccessToken() && type !== "query" && type !== "upload") {
      auditLogsAPI.create(action, type, details).catch((err) => {
        console.error("Failed to save audit log to DB:", err)
      })
    }
  }, [])

  // ============================================================
  // Saved Research
  // ============================================================
  const addSavedResearch = useCallback((title: string, content: string, docIds: string[]) => {
    const newRes: SavedResearch = {
      id: `res-${Date.now()}`,
      title,
      content,
      date: new Date().toISOString().replace('T', ' ').substring(0, 16),
      docIds
    }
    setSavedResearch(prev => [newRes, ...prev])
    addAuditLog(`Đã lưu báo cáo nghiên cứu: ${title}`, "research", `Liên kết với ${docIds.length} tài liệu.`)
  }, [addAuditLog])

  // ============================================================
  // Data Loaders
  // ============================================================
  const refreshAuditLogs = useCallback(async () => {
    try {
      const data = await auditLogsAPI.list()
      const mappedLogs: AuditLog[] = data.map((log) => ({
        id: log.id,
        action: log.action,
        type: (log.resource_type || "config") as AuditLog["type"],
        timestamp: new Date(log.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
        details: log.extra_data?.details || undefined,
      }))
      setAuditLogs(mappedLogs)
    } catch (err) {
      console.error("Failed to load audit logs:", err)
    }
  }, [])

  const refreshDocuments = useCallback(async () => {
    try {
      const data = await documentsAPI.list(1, 100)
      setDocuments(data.items)
      
      // Only set activeDocs to default if not already configured in localStorage for current session
      const currentActiveId = localStorage.getItem("active_session_id") || "new";
      const saved = localStorage.getItem(`active_docs_${currentActiveId}`);
      if (!saved) {
        setActiveDocs(data.items.filter(d => d.status === "indexed").map(d => d.id))
      }
    } catch (err) {
      console.error("Failed to load documents:", err)
    }
  }, [])

  const loadConversation = useCallback(async (conversationId: string) => {
    // Skip if already loaded or if it's a new session
    if (conversationId.startsWith("new-")) return

    try {
      const conv = await chatAPI.getConversation(conversationId)
      const messages: Message[] = conv.messages.map((m: ChatMessage) => ({
        id: m.id,
        role: m.role,
        content: preprocessCitations(m.content, m.citations),
        timestamp: new Date(m.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        citations: m.citations,
      }))

      setChatSessions(prev => prev.map(s =>
        s.id === conversationId
          ? { ...s, messages, title: conv.title || s.title, isLoaded: true }
          : s
      ))
    } catch (err) {
      console.error("Failed to load conversation:", err)
    }
  }, [])

  const refreshChatHistory = useCallback(async () => {
    try {
      const history = await chatAPI.getHistory()
      const sessions: ChatSession[] = history.map((conv: ConversationSummary) => ({
        id: conv.id,
        title: conv.title || "Hội thoại",
        messages: [],
        messageCount: conv.message_count,
        isLoaded: false,
      }))

      // Add empty "new" session at top if needed
      setChatSessions(prev => {
        const newSessions = prev.filter(s => s.id.startsWith("new-") && s.messages.length === 0)
        return [...newSessions, ...sessions]
      })

      // Restore active session if stored in localStorage
      const storedActiveId = localStorage.getItem("active_session_id")
      if (storedActiveId && history.some(conv => conv.id === storedActiveId)) {
        setActiveSessionId(storedActiveId)
        loadConversation(storedActiveId)
      }
    } catch (err) {
      console.error("Failed to load chat history:", err)
    }
  }, [loadConversation])

  // ============================================================
  // Init: Restore session from stored token
  // ============================================================
  useEffect(() => {
    if (initializedRef.current) return
    initializedRef.current = true

    // MOCK MODE: auto-login without backend
    if (MOCK_MODE) {
      setUser({
        id: "mock-user-001",
        name: "Admin User",
        email: "admin@enterprise.com",
        role: "admin",
        avatarUrl: `https://api.dicebear.com/7.x/initials/svg?seed=Admin`,
      })
      setIsAuthLoading(false)
      return
    }

    const token = getAccessToken()
    if (!token) {
      setIsAuthLoading(false)
      return
    }

    // Try to restore user session
    authAPI.me()
      .then((authUser) => {
        setUser(mapAuthUser(authUser))
        // Load data after auth
        return Promise.all([refreshDocuments(), refreshChatHistory(), refreshAuditLogs()])
      })
      .then(() => {
        addAuditLog("Khởi tạo hệ thống — phiên đăng nhập đã được khôi phục", "config")
      })
      .catch((err) => {
        console.error("Session restore failed:", err)
        clearTokens()
      })
      .finally(() => {
        setIsAuthLoading(false)
      })
  }, [refreshDocuments, refreshChatHistory, addAuditLog])

  // ============================================================
  // Sync activeSessionId to localStorage for session persistence
  // ============================================================
  useEffect(() => {
    if (typeof window !== "undefined" && activeSessionId) {
      if (!activeSessionId.startsWith("new-")) {
        localStorage.setItem("active_session_id", activeSessionId)
      } else {
        localStorage.removeItem("active_session_id")
      }
    }
  }, [activeSessionId])

  // Load activeDocs for the newly active session
  useEffect(() => {
    if (!activeSessionId) return;
    
    // Read from localStorage
    const saved = localStorage.getItem(`active_docs_${activeSessionId}`);
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed)) {
          setActiveDocs(parsed);
          return;
        }
      } catch (e) {
        // ignore JSON parse errors
      }
    }
    
    // Default to all indexed documents if not found in localStorage
    const indexedDocIds = documents.filter(d => d.status === "indexed").map(d => d.id);
    setActiveDocs(indexedDocIds);
  }, [activeSessionId, documents]);

  // Save activeDocs to localStorage whenever it changes for the active session
  useEffect(() => {
    if (!activeSessionId || (activeSessionId.startsWith("new-") && activeDocs.length === 0)) return;
    
    localStorage.setItem(`active_docs_${activeSessionId}`, JSON.stringify(activeDocs));
  }, [activeDocs, activeSessionId]);

  // ============================================================
  // Auth Operations
  // ============================================================
  const login = async (email: string, password: string) => {
    try {
      const tokens = await authAPI.login(email, password)
      setTokens(tokens.access_token, tokens.refresh_token)

      const authUser = await authAPI.me()
      const userInfo = mapAuthUser(authUser)
      setUser(userInfo)

      // Load initial data
      await Promise.all([refreshDocuments(), refreshChatHistory(), refreshAuditLogs()])
      addAuditLog(`Người dùng ${userInfo.name} đăng nhập thành công`, "config", `Email: ${email}`)

      return { success: true }
    } catch (err) {
      const message = err instanceof ApiError ? err.detail : "Có lỗi xảy ra khi đăng nhập!"
      return { success: false, error: message }
    }
  }

  const register = async (name: string, email: string, password: string) => {
    try {
      // 1. Register
      await authAPI.register(email, password, name)

      // 2. Auto-login after register
      const tokens = await authAPI.login(email, password)
      setTokens(tokens.access_token, tokens.refresh_token)

      const authUser = await authAPI.me()
      const userInfo = mapAuthUser(authUser)
      setUser(userInfo)

      await Promise.all([refreshDocuments(), refreshChatHistory(), refreshAuditLogs()])
      addAuditLog(`Đăng ký tài khoản mới thành công`, "config", `Name: ${name} | Email: ${email}`)

      return { success: true }
    } catch (err) {
      const message = err instanceof ApiError ? err.detail : "Có lỗi xảy ra khi đăng ký!"
      return { success: false, error: message }
    }
  }

  const logout = () => {
    addAuditLog(`Đã đăng xuất tài khoản`, "config")
    setUser(null)
    clearTokens()
    setChatSessions([createEmptySession()])
    setDocuments([])
    setActiveDocs([])
  }

  // ============================================================
  // Chat Operations
  // ============================================================
  const activeSession = chatSessions.find(s => s.id === activeSessionId) || chatSessions[0] || createEmptySession()

  const handleNewChat = () => {
    const newSession = createEmptySession()
    setChatSessions(prev => [newSession, ...prev])
    setActiveSessionId(newSession.id)
    addAuditLog("Đã tạo hội thoại mới", "query")
  }

  const handleDeleteSession = async (id: string, e?: React.MouseEvent) => {
    if (e) e.stopPropagation()

    // Delete from localStorage
    localStorage.removeItem(`active_docs_${id}`);

    // Delete from backend if it's a real conversation
    if (!id.startsWith("new-")) {
      try {
        await chatAPI.deleteConversation(id)
      } catch (err) {
        console.error("Failed to delete conversation:", err)
      }
    }

    const updated = chatSessions.filter(s => s.id !== id)
    if (updated.length === 0) {
      const fallback = createEmptySession()
      setChatSessions([fallback])
      setActiveSessionId(fallback.id)
    } else {
      setChatSessions(updated)
      if (activeSessionId === id) {
        setActiveSessionId(updated[0].id)
      }
    }
    addAuditLog("Đã xóa hội thoại", "query", `ID hội thoại: ${id}`)
  }

  const handleSendMessage = async (messageText: string, searchTool?: boolean | null) => {
    if (!messageText.trim() || isLlmGenerating) return

    // 1. Add user message to UI immediately
    const userMsgId = `u-${Date.now()}`
    const userMessage: Message = {
      id: userMsgId,
      role: "user",
      content: messageText,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    }

    const currentSession = activeSession
    const updatedMessages = [...currentSession.messages, userMessage]

    // Update title if new session
    let updatedTitle = currentSession.title
    if (currentSession.title === "Hội thoại mới" || currentSession.messages.length === 0) {
      updatedTitle = messageText.length > 22 ? messageText.substring(0, 20) + "..." : messageText
    }

    setChatSessions(prev => prev.map(s =>
      s.id === activeSessionId
        ? { ...s, title: updatedTitle, messages: updatedMessages }
        : s
    ))

    setIsLlmGenerating(true)

    // 2. Add placeholder assistant message with streaming indicator
    const assistantMsgId = `a-${Date.now()}`
    const placeholderAssistant: Message = {
      id: assistantMsgId,
      role: "assistant",
      content: "",
      isStreaming: true,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    }

    setChatSessions(prev => prev.map(s =>
      s.id === activeSessionId
        ? { ...s, messages: [...updatedMessages, placeholderAssistant] }
        : s
    ))

    // Cập nhật tin nhắn assistant placeholder — target theo message-id (ổn định kể
    // cả khi session id đổi từ "new-..." sang id thật), tránh race với onMeta.
    const patchAssistant = (patch: Partial<Message>) => {
      setChatSessions(prev => prev.map(s =>
        s.messages.some(m => m.id === assistantMsgId)
          ? { ...s, messages: s.messages.map(m => m.id === assistantMsgId ? { ...m, ...patch } : m) }
          : s
      ))
    }

    try {
      const conversationId = currentSession.id.startsWith("new-") ? null : currentSession.id
      let accumulated = ""

      await chatAPI.sendMessageStream(messageText, conversationId, searchTool, activeDocs, {
        // Nhận id hội thoại thật sớm → migrate session "new-..." + localStorage docs
        onMeta: (convId) => {
          if (currentSession.id.startsWith("new-")) {
            const savedDocs = localStorage.getItem(`active_docs_${currentSession.id}`)
            if (savedDocs) {
              localStorage.setItem(`active_docs_${convId}`, savedDocs)
              localStorage.removeItem(`active_docs_${currentSession.id}`)
            }
            setChatSessions(prev => prev.map(s => s.id === currentSession.id ? { ...s, id: convId } : s))
            setActiveSessionId(convId)
          }
        },
        // Từng mẩu văn bản → nối vào nội dung đang stream
        onDelta: (text) => {
          accumulated += text
          patchAssistant({ content: accumulated })
        },
        // Hoàn tất → chốt nội dung + citations
        onDone: ({ citations }) => {
          const processed = preprocessCitations(accumulated, citations)
          patchAssistant({ content: processed, isStreaming: false, citations })
          setIsLlmGenerating(false)
          addAuditLog(
            `Chạy truy vấn RAG: "${messageText.length > 30 ? messageText.substring(0, 30) + '...' : messageText}"`,
            "query",
            `Trích dẫn: ${citations?.length || 0}`
          )
          refreshAuditLogs()
        },
        onError: (detail) => {
          patchAssistant({ content: `Lỗi từ server: ${detail}`, isStreaming: false })
          setIsLlmGenerating(false)
        },
      })
    } catch (err) {
      console.error("Failed to send message:", err)
      const errorContent = err instanceof ApiError
        ? `Lỗi từ server: ${err.detail}`
        : "Không thể kết nối đến server. Vui lòng thử lại."
      patchAssistant({ content: errorContent, isStreaming: false })
      setIsLlmGenerating(false)
    }
  }

  // ============================================================
  // Document Operations
  // ============================================================
  const processFile = async (file: File) => {
    if (uploadProgress?.isUploading) return

    setUploadProgress({
      fileName: file.name,
      progress: 0,
      stepText: 'Đang chuẩn bị tải lên...',
      isUploading: true
    })

    try {
      // Step 1: Upload
      setUploadProgress(prev => prev ? { ...prev, progress: 30, stepText: 'Đang tải file lên server...' } : null)
      const doc = await documentsAPI.upload(file)

      // Step 2: Document is uploaded, backend processes it
      setUploadProgress(prev => prev ? { ...prev, progress: 60, stepText: 'Đã tải lên — đang chờ backend xử lý...' } : null)

      // Add document to local state immediately
      setDocuments(prev => [...prev, doc])

      // Step 3: Poll for indexing completion
      if (doc.status === "pending" || doc.status === "processing") {
        setUploadProgress(prev => prev ? { ...prev, progress: 70, stepText: 'Đang chờ indexing hoàn tất...' } : null)

        let attempts = 0
        const maxAttempts = 60 // 3 min max
        const pollInterval = setInterval(async () => {
          attempts++
          try {
            const updated = await documentsAPI.getById(doc.id)
            setDocuments(prev => prev.map(d => d.id === doc.id ? updated : d))

            if (updated.status === "indexed") {
              clearInterval(pollInterval)
              setActiveDocs(prev => [...prev, doc.id])
              setUploadProgress(null)
              addAuditLog(`Đã indexing tài liệu: ${file.name}`, "upload", `Kích thước: ${(file.size / 1024).toFixed(0)} KB | Trạng thái: Sẵn sàng`)
              refreshAuditLogs()
            } else if (updated.status === "failed" || attempts >= maxAttempts) {
              clearInterval(pollInterval)
              setUploadProgress({
                fileName: file.name,
                progress: 100,
                stepText: updated.status === "failed" ? 'Indexing thất bại!' : 'Hết thời gian chờ indexing!',
                isUploading: false
              })
              setTimeout(() => setUploadProgress(null), 3000)
              addAuditLog(`Lỗi xử lý tài liệu: ${file.name}`, "upload", `Trạng thái: ${updated.status}`)
            } else {
              const progressVal = 70 + Math.min(25, attempts * 2)
              setUploadProgress(prev => prev ? { ...prev, progress: progressVal, stepText: `Đang xử lý... (${updated.status})` } : null)
            }
          } catch {
            // Ignore polling errors, keep trying
          }
        }, 3000)
      } else if (doc.status === "indexed") {
        // Already indexed instantly
        setActiveDocs(prev => [...prev, doc.id])
        setUploadProgress(null)
        addAuditLog(`Đã indexing tài liệu: ${file.name}`, "upload", `Kích thước: ${(file.size / 1024).toFixed(0)} KB | Trạng thái: Sẵn sàng`)
        refreshAuditLogs()
      }

    } catch (err) {
      console.error("Upload failed:", err)
      const errorMsg = err instanceof ApiError ? err.detail : 'Lỗi trong quá trình tải lên!'
      setUploadProgress({
        fileName: file.name,
        progress: 100,
        stepText: errorMsg,
        isUploading: false
      })
      setTimeout(() => setUploadProgress(null), 3000)
      addAuditLog(`Lỗi tải lên tài liệu: ${file.name}`, "upload", errorMsg)
    }
  }

  const deleteDocument = async (docId: string) => {
    try {
      await documentsAPI.delete(docId)
      setDocuments(prev => prev.filter(d => d.id !== docId))
      setActiveDocs(prev => prev.filter(id => id !== docId))
      const docName = documents.find(d => d.id === docId)?.name || docId
      addAuditLog(`Đã xóa tài liệu: ${docName}`, "upload")
      refreshAuditLogs()
    } catch (err) {
      console.error("Failed to delete document:", err)
    }
  }

  const reindexDocument = async (docId: string) => {
    try {
      const updated = await documentsAPI.reindex(docId)
      setDocuments(prev => prev.map(d => d.id === docId ? updated : d))
      addAuditLog(`Đã yêu cầu reindex tài liệu: ${docId}`, "upload")
      refreshAuditLogs()
    } catch (err) {
      console.error("Failed to reindex document:", err)
    }
  }

  // Sync log edits when model configuration changes
  useEffect(() => {
    if (customModels.length > 0) {
      const lastModel = customModels[customModels.length - 1]
      addAuditLog(`Đã thêm Custom Model: ${lastModel.name}`, "config", `API Key kết thúc bằng ...${lastModel.apiKey.slice(-4) || 'None'}`)
    }
  }, [customModels, addAuditLog])

  // ============================================================
  // Auto-logout after 5 minutes of inactivity
  // ============================================================
  useEffect(() => {
    if (!user) return

    let timeoutId: NodeJS.Timeout

    const resetTimer = () => {
      if (timeoutId) clearTimeout(timeoutId)
      
      timeoutId = setTimeout(() => {
        addAuditLog("Đã tự động đăng xuất do không hoạt động trong 30 phút", "config")
        logout()
      }, 30 * 60 * 1000) // 30 minutes in milliseconds
    }

    // Events to track user activity
    const events = [
      "mousemove",
      "keydown",
      "mousedown",
      "click",
      "scroll",
      "touchstart"
    ]

    // Initialize timer
    resetTimer()

    // Attach listeners
    events.forEach(event => {
      window.addEventListener(event, resetTimer)
    })

    // Cleanup on unmount or user change
    return () => {
      if (timeoutId) clearTimeout(timeoutId)
      events.forEach(event => {
        window.removeEventListener(event, resetTimer)
      })
    }
  }, [user, logout, addAuditLog])

  return (
    <AppContext.Provider value={{
      documents,
      setDocuments,
      activeDocs,
      setActiveDocs,
      chatSessions,
      setChatSessions,
      activeSessionId,
      setActiveSessionId,
      activeSession,
      customModels,
      setCustomModels,
      ragSettings,
      setRagSettings,
      uploadProgress,
      setUploadProgress,
      showLeftSidebar,
      setShowLeftSidebar,
      showRightPanel,
      setShowRightPanel,
      rightPanelTab,
      setRightPanelTab,
      auditLogs,
      addAuditLog,
      savedResearch,
      addSavedResearch,
      handleNewChat,
      handleDeleteSession,
      handleSendMessage,
      isLlmGenerating,
      setIsLlmGenerating,
      showRagProcessId,
      setShowRagProcessId,
      processFile,
      deleteDocument,
      reindexDocument,
      loadConversation,
      user,
      isAuthLoading,
      login,
      register,
      logout,
      refreshDocuments,
      refreshChatHistory,
      refreshAuditLogs,
    }}>
      {children}
    </AppContext.Provider>
  )
}

export function useApp() {
  const context = useContext(AppContext)
  if (context === undefined) {
    throw new Error("useApp must be used within an AppContextProvider")
  }
  return context
}
