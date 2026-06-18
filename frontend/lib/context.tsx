"use client"

import React, { createContext, useContext, useState, useEffect } from "react"
import { 
  initialDocuments, 
  getMockRAGResponse, 
  simulateDocumentProcessing,
  MockDocument, 
  RAGResponse,
  DocumentChunk
} from "./mockRag"

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  isStreaming?: boolean;
  timestamp: string;
  ragResponse?: RAGResponse;
}

export interface User {
  id: string;
  name: string;
  email: string;
  avatarUrl?: string;
}

export interface ChatSession {
  id: string;
  title: string;
  messages: Message[];
  activeDocs: string[];
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
  documents: MockDocument[];
  setDocuments: React.Dispatch<React.SetStateAction<MockDocument[]>>;
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
  handleSendMessage: (messageText: string) => void;
  isLlmGenerating: boolean;
  setIsLlmGenerating: React.Dispatch<React.SetStateAction<boolean>>;
  activeRagProcess: RAGResponse | null;
  setActiveRagProcess: React.Dispatch<React.SetStateAction<RAGResponse | null>>;
  showRagProcessId: string | null;
  setShowRagProcessId: React.Dispatch<React.SetStateAction<string | null>>;
  processFile: (file: File) => Promise<void>;
  user: User | null;
  login: (email: string, password: string) => Promise<{ success: boolean; error?: string }>;
  register: (name: string, email: string, password: string) => Promise<{ success: boolean; error?: string }>;
  logout: () => void;
}

const AppContext = createContext<AppContextType | undefined>(undefined)

export function AppContextProvider({ children }: { children: React.ReactNode }) {
  // --- States ---
  const [documents, setDocuments] = useState<MockDocument[]>(initialDocuments)
  const [activeDocs, setActiveDocs] = useState<string[]>(initialDocuments.map(d => d.id))
  
  const [chatSessions, setChatSessions] = useState<ChatSession[]>([
    {
      id: "session-1",
      title: "Tìm hiểu Doanh nghiệp Xã hội",
      activeDocs: ["ldn-2020"],
      messages: [
        {
          id: "m1",
          role: "user",
          content: "Điều kiện để doanh nghiệp được công nhận là doanh nghiệp xã hội?",
          timestamp: "15:00"
        },
        {
          id: "m2",
          role: "assistant",
          content: `Dựa trên **Luật Doanh nghiệp 2020**, cụ thể là tại [Luật Doanh nghiệp 2020 - Điều 5](#cite-ldn-c1) (Độ tương đồng: 96%), một doanh nghiệp để được công nhận là **Doanh nghiệp xã hội** phải đáp ứng đầy đủ **03 tiêu chí cốt lõi** sau đây:

1. **Về hình thức pháp lý**: Doanh nghiệp phải được đăng ký thành lập theo đúng quy định của Luật này (có thể là Công ty TNHH, Công ty Cổ phần, v.v.).
2. **Mục tiêu hoạt động**: Mục tiêu chính khi thành lập và vận hành là nhằm **giải quyết các vấn đề xã hội, môi trường** vì lợi ích cộng đồng.
3. **Cam kết tái đầu tư tài chính**: Doanh nghiệp phải sử dụng **ít nhất 51% tổng lợi nhuận sau thuế hằng năm** để tái đầu tư phục vụ trực tiếp cho các mục tiêu xã hội, môi trường như đã đăng ký.

Ngoài ra, người đại diện theo pháp luật của doanh nghiệp xã hội có nghĩa vụ tuân thủ các quy chế giám sát nghiêm ngặt từ cơ quan quản lý và các bên tài trợ. Nếu thay đổi mục tiêu hoặc không duy trì cam kết lợi nhuận, doanh nghiệp phải thông báo để chuyển đổi hình thức hoạt động.`,
          timestamp: "15:00",
          ragResponse: {
            answer: `Dựa trên **Luật Doanh nghiệp 2020**, cụ thể là tại [Luật Doanh nghiệp 2020 - Điều 5](#cite-ldn-c1) (Độ tương đồng: 96%), một doanh nghiệp để được công nhận là **Doanh nghiệp xã hội** phải đáp ứng đầy đủ **03 tiêu chí cốt lõi** sau đây:

1. **Về hình thức pháp lý**: Doanh nghiệp phải được đăng ký thành lập theo đúng quy định của Luật này (có thể là Công ty TNHH, Công ty Cổ phần, v.v.).
2. **Mục tiêu hoạt động**: Mục tiêu chính khi thành lập và vận hành là nhằm **giải quyết các vấn đề xã hội, môi trường** vì lợi ích cộng đồng.
3. **Cam kết tái đầu tư tài chính**: Doanh nghiệp phải sử dụng **ít nhất 51% tổng lợi nhuận sau thuế hằng năm** để tái đầu tư phục vụ trực tiếp cho các mục tiêu xã hội, môi trường như đã đăng ký.

Ngoài ra, người đại diện theo pháp luật của doanh nghiệp xã hội có nghĩa vụ tuân thủ các quy chế giám sát nghiêm ngặt từ cơ quan quản lý và các bên tài trợ. Nếu thay đổi mục tiêu hoặc không duy trì cam kết lợi nhuận, doanh nghiệp phải thông báo để chuyển đổi hình thức hoạt động.`,
            processingTimeMs: 680,
            tokensCount: { prompt: 250, completion: 480 },
            steps: [
              { name: 'Phân tích & Dịch câu hỏi (Query Expansion)', status: 'completed', details: 'Từ khóa chính: "doanh nghiệp xã hội" | Chế độ: Hybrid' },
              { name: 'Truy xuất tài liệu từ Vector DB', status: 'completed', details: 'Tìm thấy 3 chunks. Lọc lại 1 chunks phù hợp (Threshold > 0.3)' },
              { name: 'Đánh giá xếp hạng chéo (Reranking)', status: 'completed', details: 'Sử dụng mô hình GPT-4o Reranker' },
              { name: 'Tạo Prompt ngữ cảnh & Gửi LLM', status: 'completed', details: 'Context size: ~320 ký tự.' }
            ],
            citations: [
              {
                id: 'ldn-c1',
                docId: 'ldn-2020',
                docName: 'Luật Doanh nghiệp 2020',
                title: 'Điều 5: Tiêu chí, quyền và nghĩa vụ của doanh nghiệp xã hội',
                article: 'Điều 5',
                clause: 'Khoản 1',
                snippet: 'Doanh nghiệp xã hội phải đáp ứng các tiêu chí sau đây: a) Là doanh nghiệp được đăng ký thành lập theo quy định của Luật này; b) Mục tiêu hoạt động nhằm giải quyết vấn đề xã hội, môi trường vì lợi ích cộng đồng; c) Sử dụng ít nhất 51% tổng lợi nhuận sau thuế hằng năm của doanh nghiệp để tái đầu tư nhằm thực hiện mục tiêu xã hội, môi trường như đã đăng ký.',
                score: 0.96
              }
            ]
          }
        }
      ]
    },
    {
      id: "session-2",
      title: "Chính sách bảo mật nội bộ",
      activeDocs: ["qcbm-2025"],
      messages: []
    }
  ])
  
  const [activeSessionId, setActiveSessionId] = useState<string>("session-1")
  const [customModels, setCustomModels] = useState<CustomModel[]>([])
  const [showLeftSidebar, setShowLeftSidebar] = useState<boolean>(true)
  const [showRightPanel, setShowRightPanel] = useState<boolean>(true)
  const [rightPanelTab, setRightPanelTab] = useState<"docs" | "settings">("docs")
  const [isLlmGenerating, setIsLlmGenerating] = useState<boolean>(false)
  const [activeRagProcess, setActiveRagProcess] = useState<RAGResponse | null>(null)
  const [showRagProcessId, setShowRagProcessId] = useState<string | null>("m2")

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

  // --- Auth State & Operations ---
  const [user, setUser] = useState<User | null>(null)

  useEffect(() => {
    // 1. Ensure mock users list exists in localStorage
    const existingUsers = localStorage.getItem("rag_users")
    if (!existingUsers) {
      const demoUsers = [
        {
          id: "user-demo",
          name: "Admin User",
          email: "admin@enterprise.com",
          password: "admin123"
        }
      ]
      localStorage.setItem("rag_users", JSON.stringify(demoUsers))
    }

    // 2. Load current user
    const currentUser = localStorage.getItem("current_rag_user")
    if (currentUser) {
      try {
        setUser(JSON.parse(currentUser))
      } catch (e) {
        console.error("Failed to parse current user", e)
      }
    }
  }, [])

  const login = async (email: string, password: string) => {
    const usersStr = localStorage.getItem("rag_users") || "[]"
    let users = []
    try {
      users = JSON.parse(usersStr)
    } catch (e) {
      users = []
    }

    const matchedUser = users.find((u: any) => u.email.toLowerCase() === email.toLowerCase() && u.password === password)
    if (matchedUser) {
      const userInfo = {
        id: matchedUser.id,
        name: matchedUser.name,
        email: matchedUser.email,
        avatarUrl: matchedUser.avatarUrl || `https://api.dicebear.com/7.x/initials/svg?seed=${encodeURIComponent(matchedUser.name)}`
      }
      setUser(userInfo)
      localStorage.setItem("current_rag_user", JSON.stringify(userInfo))
      addAuditLog(`Người dùng ${matchedUser.name} đăng nhập thành công`, "config", `Email: ${email}`)
      return { success: true }
    } else {
      return { success: false, error: "Email hoặc mật khẩu không chính xác!" }
    }
  }

  const register = async (name: string, email: string, password: string) => {
    const usersStr = localStorage.getItem("rag_users") || "[]"
    let users = []
    try {
      users = JSON.parse(usersStr)
    } catch (e) {
      users = []
    }

    if (users.some((u: any) => u.email.toLowerCase() === email.toLowerCase())) {
      return { success: false, error: "Email này đã được sử dụng!" }
    }

    const newUser = {
      id: `user-${Date.now()}`,
      name,
      email,
      password,
      avatarUrl: `https://api.dicebear.com/7.x/initials/svg?seed=${encodeURIComponent(name)}`
    }

    users.push(newUser)
    localStorage.setItem("rag_users", JSON.stringify(users))

    const userInfo = {
      id: newUser.id,
      name: newUser.name,
      email: newUser.email,
      avatarUrl: newUser.avatarUrl
    }
    setUser(userInfo)
    localStorage.setItem("current_rag_user", JSON.stringify(userInfo))
    addAuditLog(`Đăng ký tài khoản mới thành công`, "config", `Name: ${name} | Email: ${email}`)
    return { success: true }
  }

  const logout = () => {
    setUser(null)
    localStorage.removeItem("current_rag_user")
    addAuditLog(`Đã đăng xuất tài khoản`, "config")
  }

  // Audit Logs State
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([
    {
      id: "log-1",
      action: "Khởi tạo hệ thống Enterprise Knowledge RAG",
      type: "config",
      timestamp: "16:00:10",
      details: "Mô hình mặc định: Gemini 1.5 Flash. Hệ thống vector database sẵn sàng."
    },
    {
      id: "log-2",
      action: "Đã indexing tài liệu: Luật Doanh nghiệp 2020",
      type: "upload",
      timestamp: "16:01:25",
      details: "Mã: 59/2020/QH14 | Kích thước: 1.2 MB | Đã tách làm 3 chunks."
    },
    {
      id: "log-3",
      action: "Đã indexing tài liệu: Bộ luật Dân sự 2015",
      type: "upload",
      timestamp: "16:02:10",
      details: "Mã: 91/2015/QH13 | Kích thước: 2.8 MB | Đã tách làm 3 chunks."
    },
    {
      id: "log-4",
      action: "Đã indexing tài liệu: Quy chế bảo mật thông tin nội bộ",
      type: "upload",
      timestamp: "16:03:00",
      details: "Mã: QC-BM-01/2025 | Kích thước: 450 KB | Đã tách làm 2 chunks."
    },
    {
      id: "log-5",
      action: "Chạy truy vấn RAG: Điều kiện doanh nghiệp xã hội",
      type: "query",
      timestamp: "16:05:00",
      details: "Model: Gemini 1.5 Flash | Thời gian xử lý: 680ms | Tìm thấy 1 trích dẫn phù hợp."
    }
  ])

  // Saved Research State
  const [savedResearch, setSavedResearch] = useState<SavedResearch[]>([
    {
      id: "res-1",
      title: "Điều kiện & Nghĩa vụ của Doanh nghiệp Xã hội",
      content: `Dựa trên phân tích Điều 5 Luật Doanh nghiệp 2020:
- Doanh nghiệp phải đăng ký thành lập theo luật định.
- Mục tiêu giải quyết các vấn đề xã hội/môi trường.
- Cam kết giữ lại ít nhất 51% lợi nhuận sau thuế hàng năm để tái đầu tư vào mục tiêu xã hội.
- Cần ký thỏa thuận cam kết và nộp cho cơ quan đăng ký kinh doanh.`,
      date: "2026-06-17 15:30",
      docIds: ["ldn-2020"]
    }
  ])

  // Computed state
  const activeSession = chatSessions.find(s => s.id === activeSessionId) || chatSessions[0]

  // --- Helpers ---
  const addAuditLog = (action: string, type: AuditLog["type"], details?: string) => {
    const newLog: AuditLog = {
      id: `log-${Date.now()}`,
      action,
      type,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
      details
    }
    setAuditLogs(prev => [newLog, ...prev])
  }

  const addSavedResearch = (title: string, content: string, docIds: string[]) => {
    const newRes: SavedResearch = {
      id: `res-${Date.now()}`,
      title,
      content,
      date: new Date().toISOString().replace('T', ' ').substring(0, 16),
      docIds
    }
    setSavedResearch(prev => [newRes, ...prev])
    addAuditLog(`Đã lưu báo cáo nghiên cứu: ${title}`, "research", `Liên kết với ${docIds.length} tài liệu.`)
  }

  const handleNewChat = () => {
    const newSessionId = `session-${Date.now()}`
    const newSession: ChatSession = {
      id: newSessionId,
      title: "Hội thoại mới",
      activeDocs: documents.map(d => d.id),
      messages: []
    }
    setChatSessions([newSession, ...chatSessions])
    setActiveSessionId(newSessionId)
    addAuditLog("Đã tạo hội thoại mới", "query", `ID: ${newSessionId}`)
  }

  const handleDeleteSession = (id: string, e?: React.MouseEvent) => {
    if (e) e.stopPropagation()
    const updated = chatSessions.filter(s => s.id !== id)
    if (updated.length === 0) {
      const fallbackId = `session-${Date.now()}`
      setChatSessions([{
        id: fallbackId,
        title: "Hội thoại mới",
        activeDocs: documents.map(d => d.id),
        messages: []
      }])
      setActiveSessionId(fallbackId)
    } else {
      setChatSessions(updated)
      if (activeSessionId === id) {
        setActiveSessionId(updated[0].id)
      }
    }
    addAuditLog("Đã xóa hội thoại", "query", `ID hội thoại: ${id}`)
  }

  const handleSendMessage = (messageText: string) => {
    if (!messageText.trim() || isLlmGenerating) return

    // 1. Append user message
    const userMsgId = `u-${Date.now()}`
    const userMessage: Message = {
      id: userMsgId,
      role: "user",
      content: messageText,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    }

    const updatedMessages = [...activeSession.messages, userMessage]
    
    // Update active chat session title if it was default
    let updatedTitle = activeSession.title
    if (activeSession.title === "Hội thoại mới" || activeSession.messages.length === 0) {
      updatedTitle = messageText.length > 22 ? messageText.substring(0, 20) + "..." : messageText
    }

    setChatSessions(prev => prev.map(s => 
      s.id === activeSessionId 
        ? { ...s, title: updatedTitle, messages: updatedMessages }
        : s
    ))

    setIsLlmGenerating(true)

    // 2. Generate simulated RAG response
    const ragResult = getMockRAGResponse(
      messageText,
      activeDocs,
      {
        searchMode: ragSettings.searchMode,
        model: ragSettings.model,
        topK: ragSettings.topK,
        similarityThreshold: ragSettings.similarityThreshold
      }
    )

    // Show step-by-step loading panel
    setActiveRagProcess(ragResult)
    const assistantMsgId = `a-${Date.now()}`
    setShowRagProcessId(assistantMsgId)

    // Start with empty message and stream it
    const assistantMessage: Message = {
      id: assistantMsgId,
      role: "assistant",
      content: "",
      isStreaming: true,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      ragResponse: ragResult
    }

    setChatSessions(prev => prev.map(s => 
      s.id === activeSessionId 
        ? { ...s, messages: [...updatedMessages, assistantMessage] }
        : s
    ))

    // Stream the text output word by word
    const textToStream = ragResult.answer
    let currentText = ""
    const textArray = textToStream.split(" ")
    let wordIndex = 0

    const streamInterval = setInterval(() => {
      if (wordIndex < textArray.length) {
        currentText += (wordIndex === 0 ? "" : " ") + textArray[wordIndex]
        
        setChatSessions(prev => prev.map(s => 
          s.id === activeSessionId 
            ? {
                ...s,
                messages: s.messages.map(m => 
                  m.id === assistantMsgId 
                    ? { ...m, content: currentText }
                    : m
                )
              }
            : s
        ))
        wordIndex++
      } else {
        clearInterval(streamInterval)
        
        // Finalize message status (set isStreaming to false)
        setChatSessions(prev => prev.map(s => 
          s.id === activeSessionId 
            ? {
                ...s,
                messages: s.messages.map(m => 
                  m.id === assistantMsgId 
                    ? { ...m, isStreaming: false }
                    : m
                )
              }
            : s
        ))
        
        setIsLlmGenerating(false)
        addAuditLog(
          `Chạy truy vấn RAG: "${messageText.length > 30 ? messageText.substring(0, 30) + '...' : messageText}"`,
          "query",
          `Model: ${ragSettings.model} | Thời gian: ${ragResult.processingTimeMs}ms | Trích dẫn: ${ragResult.citations.length}`
        )
      }
    }, 45)
  }

  const processFile = async (file: File) => {
    if (uploadProgress?.isUploading) return;

    setUploadProgress({
      fileName: file.name,
      progress: 0,
      stepText: 'Đang chuẩn bị file...',
      isUploading: true
    })

    try {
      const newDoc = await simulateDocumentProcessing(
        file.name,
        file.size,
        (stepIndex, stepText) => {
          setUploadProgress(prev => {
            if (!prev) return null;
            const newProgress = Math.round(((stepIndex + 1) / 7) * 100);
            return {
              ...prev,
              progress: newProgress,
              stepText: stepText
            };
          });
        }
      )

      // Add newly indexed document to state
      setDocuments(prev => [...prev, newDoc])
      setActiveDocs(prev => [...prev, newDoc.id])
      
      // Reset upload state
      setUploadProgress(null)
      addAuditLog(`Đã indexing tài liệu: ${file.name}`, "upload", `Kích thước: ${(file.size / 1024).toFixed(0)} KB | Trạng thái: Sẵn sàng`)
    } catch (err) {
      console.error(err)
      setUploadProgress({
        fileName: file.name,
        progress: 100,
        stepText: 'Lỗi trong quá trình xử lý tài liệu!',
        isUploading: false
      })
      setTimeout(() => setUploadProgress(null), 3000)
      addAuditLog(`Lỗi xử lý tài liệu: ${file.name}`, "upload", "Quá trình indexing thất bại.")
    }
  }

  // Sync log edits when model configuration changes
  useEffect(() => {
    if (customModels.length > 0) {
      const lastModel = customModels[customModels.length - 1]
      addAuditLog(`Đã thêm Custom Model: ${lastModel.name}`, "config", `API Key kết thúc bằng ...${lastModel.apiKey.slice(-4) || 'None'}`)
    }
  }, [customModels])

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
      activeRagProcess,
      setActiveRagProcess,
      showRagProcessId,
      setShowRagProcessId,
      processFile,
      user,
      login,
      register,
      logout
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
