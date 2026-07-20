"use client"

import React, { useState, useRef, useEffect } from "react"
import { 
  Send, 
  Bot, 
  User, 
  Paperclip, 
  SlidersHorizontal, 
  FileText, 
  Trash2, 
  Plus, 
  ArrowRight, 
  ChevronRight, 
  ChevronDown, 
  Database, 
  Sparkles, 
  Scale, 
  ShieldAlert, 
  GitCompare, 
  Lock, 
  Settings, 
  AlertTriangle, 
  UploadCloud, 
  X, 
  Copy, 
  Check, 
  BookOpen,
  Info,
  RefreshCw,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  Eye,
  EyeOff,
  Key,
  CirclePlus
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { useApp, CustomModel } from "@/lib/context"
import { type Citation, type Document } from "@/lib/api"

// Các bước "suy nghĩ" hiển thị trong lúc chờ backend trả lời (giống thinking của
// Claude Desktop). Hiện dần từng bước rồi tự ẩn khi câu trả lời bắt đầu về.
const THINKING_STEPS = [
  "Phân tích câu hỏi",
  "Truy hồi tài liệu liên quan",
  "Xếp hạng nguồn phù hợp",
  "Tổng hợp câu trả lời",
]

function ThinkingIndicator() {
  const [step, setStep] = useState(0)
  useEffect(() => {
    const id = setInterval(
      () => setStep((s) => Math.min(s + 1, THINKING_STEPS.length - 1)),
      1400
    )
    return () => clearInterval(id)
  }, [])
  return (
    <div className="space-y-1.5 py-1">
      {THINKING_STEPS.map((label, i) => {
        if (i > step) return null // chỉ hiện các bước đã tới
        const done = i < step
        return (
          <div
            key={i}
            className={`flex items-center gap-2 text-[12px] transition-all animate-msg-in ${
              done ? "text-neutral-600" : "text-neutral-300"
            }`}
          >
            {done ? (
              <Check className="w-3 h-3 text-emerald-400/60 shrink-0" />
            ) : (
              <RefreshCw className="w-3 h-3 animate-spin text-emerald-400/70 shrink-0" />
            )}
            <span>
              {label}
              {done ? "" : "…"}
            </span>
          </div>
        )
      })}
    </div>
  )
}

export default function Page() {
  const {
    documents,
    toggleDocActive,
    activeSession,
    activeSessionId,
    customModels,
    setCustomModels,
    ragSettings,
    setRagSettings,
    uploadProgress,
    showLeftSidebar,
    setShowLeftSidebar,
    showRightPanel,
    setShowRightPanel,
    rightPanelTab,
    setRightPanelTab,
    handleSendMessage,
    isLlmGenerating,
    showRagProcessId,
    setShowRagProcessId,
    processFile
  } = useApp()

  // --- Local States for the Chat View ---
  const [inputMessage, setInputMessage] = useState<string>("")
  // Nguồn được chọn: gom TẤT CẢ chunk trích dẫn của cùng 1 tài liệu để hiện ở panel bên phải.
  const [selectedSource, setSelectedSource] = useState<{
    name: string
    documentId: string
    citations: Citation[]
  } | null>(null)
  const [copiedChunkId, setCopiedChunkId] = useState<string | null>(null)
  const [showSearchToggle, setShowSearchToggle] = useState<boolean>(false)
  const [searchToolEnabled, setSearchToolEnabled] = useState<boolean>(false)
  const [newModelName, setNewModelName] = useState<string>("")
  const [newModelApiKey, setNewModelApiKey] = useState<string>("")
  const [showAddModel, setShowAddModel] = useState<boolean>(false)
  const [visibleApiKeys, setVisibleApiKeys] = useState<Set<string>>(new Set())

  const defaultModels = [
    { value: "Gemini 1.5 Pro", label: "Gemini 1.5 Pro (Deep Reasoning)" },
    { value: "Gemini 1.5 Flash", label: "Gemini 1.5 Flash (Tốc độ cao)" },
    { value: "GPT-4o Enterprise", label: "GPT-4o Enterprise (OpenAI)" },
    { value: "Llama 3.1 70B", label: "Llama 3.1 70B (Mã nguồn mở)" },
  ]

  // Refs
  const chatEndRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Scroll to bottom on new messages
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [activeSession?.messages, isLlmGenerating])

  // Tài liệu thuộc hội thoại đang mở. Panel hiện TẤT CẢ (cả active lẫn inactive) để người
  // dùng thấy đã upload gì vào kho của đoạn chat này; tick = active (dùng cho truy vấn).
  const conversationDocs = documents.filter(d => d.conversation_id === activeSessionId)
  const activeIndexedCount = conversationDocs.filter(d => d.status === "indexed" && d.is_active).length
  const indexedCount = conversationDocs.filter(d => d.status === "indexed").length

  // --- Handlers ---
  const handleToggleDoc = (docId: string) => {
    // Đang truy vấn → khóa chọn để tránh đổi tập tài liệu giữa chừng gây lỗi.
    if (isLlmGenerating) return
    // Bật/tắt is_active (lưu ở backend). Tài liệu vẫn hiện trong panel, chỉ đổi tick.
    toggleDocActive(docId)
  }

  const handleSend = () => {
    if (!inputMessage.trim()) return
    handleSendMessage(inputMessage, searchToolEnabled)
    setInputMessage("")
  }

  const onDragOver = (e: React.DragEvent) => {
    e.preventDefault()
  }

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault()
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      processFile(e.dataTransfer.files[0])
    }
  }

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      processFile(e.target.files[0])
    }
  }

  const copyToClipboard = (text: string, chunkId: string) => {
    navigator.clipboard.writeText(text)
    setCopiedChunkId(chunkId)
    setTimeout(() => setCopiedChunkId(null), 2000)
  }

  // Render text containing citation markdown links [DocName - Article](#cite-id)
  const renderMessageContent = (content: string) => {
    if (!content) return null;

    const disclaimerText = "Câu trả lời này được tổng hợp từ Internet, không nằm trong tài liệu nội bộ của công ty...";
    const hasDisclaimer = content.startsWith(disclaimerText);
    const cleanContent = hasDisclaimer ? content.replace(disclaimerText, "").trim() : content;

    const lines = cleanContent.split('\n');
    
    const renderedLines = lines.map((line, lIdx) => {
      // Handle alert blocks
      if (line.startsWith('> [!WARNING]')) {
        return (
          <div key={lIdx} className="my-3 p-3 rounded-lg bg-amber-500/5 border border-amber-500/10 text-amber-200/80 text-[13px] flex gap-2.5 items-start">
            <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0 text-amber-400/70" />
            <div className="leading-relaxed">{line.replace('> [!WARNING]', '').trim()}</div>
          </div>
        );
      }
      if (line.startsWith('> [!TIP]')) {
        return (
          <div key={lIdx} className="my-3 p-3 rounded-lg bg-emerald-500/5 border border-emerald-500/10 text-emerald-200/80 text-[13px] flex gap-2.5 items-start">
            <Sparkles className="w-4 h-4 mt-0.5 shrink-0 text-emerald-400/60" />
            <div className="leading-relaxed">{line.replace('> [!TIP]', '').trim()}</div>
          </div>
        );
      }

      // Headers
      if (line.startsWith('### ')) {
        return <h3 key={lIdx} className="text-[13px] font-semibold text-neutral-200 mt-4 mb-1.5">{line.replace('### ', '')}</h3>;
      }
      if (line.startsWith('## ')) {
        return <h2 key={lIdx} className="text-sm font-bold text-neutral-100 mt-5 mb-2">{line.replace('## ', '')}</h2>;
      }

      // Unordered list
      if (line.startsWith('* ') || line.startsWith('- ')) {
        const restOfLine = line.substring(2);
        return (
          <li key={lIdx} className="ml-5 list-disc text-neutral-300/90 my-1 text-[13px] leading-relaxed">
            {parseCitationsAndFormatting(restOfLine)}
          </li>
        );
      }

      // Numbered list
      const numberMatch = line.match(/^(\d+)\.\s(.*)/);
      if (numberMatch) {
        return (
          <div key={lIdx} className="flex ml-1 my-2 text-neutral-300/90 text-[13px]">
            <span className="font-semibold mr-2.5 text-emerald-400/80 tabular-nums">{numberMatch[1]}.</span>
            <span className="leading-relaxed">{parseCitationsAndFormatting(numberMatch[2])}</span>
          </div>
        );
      }

      return (
        <p key={lIdx} className="my-1.5 leading-[1.7] text-neutral-300/90 text-[13px]">
          {parseCitationsAndFormatting(line)}
        </p>
      );
    });

    return (
      <>
        {hasDisclaimer && (
          <div className="my-3 p-3.5 rounded-xl bg-amber-500/5 border border-amber-500/10 text-amber-200/80 text-[13px] flex gap-2.5 items-start animate-msg-in">
            <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0 text-amber-400/70" />
            <div className="leading-relaxed font-sans">{disclaimerText}</div>
          </div>
        )}
        {renderedLines}
      </>
    );
  }

  const parseCitationsAndFormatting = (text: string) => {
    const regex = /(\*\*.*?\*\*|\[.*?\]\(#cite-.*?\))/g;
    const parts = text.split(regex);
    
    return parts.map((part, index) => {
      if (part.startsWith('**') && part.endsWith('**')) {
        return <strong key={index} className="text-neutral-100 font-semibold">{part.slice(2, -2)}</strong>;
      }
      
      // Bỏ badge trích dẫn inline — nguồn giờ gom vào dropdown "Nguồn truy vấn" đầu câu trả lời.
      if (part.match(/\[(.*?)\]\(#cite-(.*?)\)/)) {
        return null;
      }

      return part;
    });
  }

  return (
    <div className="flex-1 flex flex-row min-w-0 relative h-full overflow-hidden">
      
      {/* ===== CENTER — CHAT AREA ===== */}
      <main className="flex-1 flex flex-col min-w-0 h-full overflow-hidden z-0">
        
        {/* Header */}
        <header className="h-12 border-b border-white/[0.04] bg-[#0a0a0a]/60 backdrop-blur-md px-4 flex items-center justify-between gap-4 shrink-0">
          <div className="flex items-center gap-2">
            {!showLeftSidebar && (
              <button 
                onClick={() => setShowLeftSidebar(true)}
                className="p-1.5 rounded-lg hover:bg-white/[0.04] text-neutral-500 hover:text-neutral-300 transition-colors"
                title="Open Sidebar"
              >
                <PanelLeftOpen className="w-4 h-4" />
              </button>
            )}
            
            <div className="flex items-center gap-1.5 text-[12px] text-neutral-500">
              <Sparkles className="w-3 h-3 text-amber-400/60" />
              <span>{ragSettings.model}</span>
              <span className="text-neutral-700">·</span>
              <span className="text-neutral-600">
                {indexedCount > 0
                  ? `${activeIndexedCount}/${indexedCount} tài liệu`
                  : "Chưa có tài liệu"}
              </span>
            </div>
          </div>

          <button 
            onClick={() => setShowRightPanel(!showRightPanel)}
            className={`p-1.5 rounded-lg transition-colors ${
              showRightPanel 
                ? "bg-white/[0.06] text-neutral-300" 
                : "hover:bg-white/[0.04] text-neutral-500 hover:text-neutral-300"
            }`}
            title="Toggle Panel"
          >
            {showRightPanel ? <PanelRightClose className="w-4 h-4" /> : <PanelRightOpen className="w-4 h-4" />}
          </button>
        </header>

        {/* Messages Container */}
        <div className="flex-1 overflow-y-auto px-4 md:px-6 py-6 scrollbar-thin">
          {!activeSession || activeSession.messages.length === 0 ? (
            
            /* ===== WELCOME SCREEN ===== */
            <div className="max-w-2xl mx-auto py-16 md:py-24 flex flex-col items-center justify-center text-center space-y-10">
              <div className="relative animate-msg-in">
                <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-emerald-500/20 to-teal-600/20 border border-emerald-500/10 flex items-center justify-center">
                  <Bot className="w-7 h-7 text-emerald-400/70" />
                </div>
              </div>

              <div className="space-y-3">
                <h2 className="text-2xl md:text-3xl font-bold tracking-tight text-neutral-100">
                  Xin chào, tôi có thể giúp gì?
                </h2>
                <p className="text-neutral-500 text-sm max-w-md leading-relaxed mx-auto">
                  Trợ lý AI chuyên sâu tra cứu & phân tích tài liệu pháp lý, quy chế nội bộ doanh nghiệp. Dữ liệu được bảo mật hoàn toàn.
                </p>
              </div>

              {/* Suggestion Cards */}
              <div className="w-full space-y-3">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                  {[
                    { text: "Điều kiện thành lập doanh nghiệp xã hội", category: "Luật Doanh nghiệp", icon: "Scale" },
                    { text: "Quy định lưu trữ dữ liệu nội bộ", category: "Chính sách nội bộ", icon: "ShieldAlert" },
                    { text: "So sánh chi nhánh và văn phòng đại diện", category: "Tư vấn cấu trúc", icon: "GitCompare" },
                    { text: "Xử lý vi phạm bảo mật nghiêm trọng", category: "Quy chế kỷ luật", icon: "Lock" }
                  ].map((prompt, pIdx) => {
                    const icons: Record<string, React.ReactNode> = {
                      ShieldAlert: <ShieldAlert className="w-4 h-4 text-emerald-400/50" />,
                      GitCompare: <GitCompare className="w-4 h-4 text-violet-400/50" />,
                      Scale: <Scale className="w-4 h-4 text-amber-400/50" />,
                      Lock: <Lock className="w-4 h-4 text-sky-400/50" />,
                    }
                    return (
                      <div
                        key={pIdx}
                        onClick={() => handleSendMessage(prompt.text)}
                        className="suggestion-card p-4 rounded-xl text-left cursor-pointer flex flex-col gap-2"
                      >
                        <div className="flex items-center justify-between">
                          <span className="text-[10px] font-medium px-2 py-0.5 rounded-md bg-white/[0.03] text-neutral-500 border border-white/[0.04]">
                            {prompt.category}
                          </span>
                          {icons[prompt.icon]}
                        </div>
                        <p className="text-[13px] text-neutral-300 leading-relaxed line-clamp-2">
                          {prompt.text}
                        </p>
                        <div className="text-[11px] text-neutral-600 flex items-center gap-1 mt-0.5">
                          Hỏi ngay <ArrowRight className="w-2.5 h-2.5" />
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>

          ) : (

            /* ===== CHAT MESSAGES ===== */
            <div className="max-w-3xl mx-auto space-y-6">
              {activeSession.messages.map((message) => {
                const isAi = message.role === "assistant";
                // Nguồn tham chiếu: gộp trùng theo tài liệu (nhiều chunk cùng 1 doc
                // → chỉ hiện 1 nguồn), tránh danh sách lặp lại cùng tên tài liệu.
                const uniqueCitations = (message.citations ?? []).filter(
                  (c, i, arr) =>
                    arr.findIndex(
                      (x) =>
                        (x.document_id || x.document_name) ===
                        (c.document_id || c.document_name)
                    ) === i
                );
                return (
                  <div key={message.id} className="space-y-2 animate-msg-in">
                    
                    {/* Message */}
                    <div className={`flex gap-3 items-start ${isAi ? "" : "flex-row-reverse"}`}>
                      
                      {/* Avatar */}
                      <div className={`w-7 h-7 rounded-full shrink-0 flex items-center justify-center ${
                        isAi 
                          ? "bg-white/[0.04] border border-white/[0.06]" 
                          : "bg-emerald-500/20 border border-emerald-500/15"
                      }`}>
                        {isAi 
                          ? <Bot className="w-3.5 h-3.5 text-emerald-400/70" /> 
                          : <User className="w-3.5 h-3.5 text-emerald-300/70" />
                        }
                      </div>

                      {/* Content */}
                      <div className={`max-w-[85%] rounded-2xl px-4 py-3 ${
                        isAi 
                          ? "bg-transparent" 
                          : "bg-white/[0.04] border border-white/[0.05] text-neutral-200"
                      }`}>
                        {isAi ? (
                          <div>
                            {/* Nguồn truy vấn — ĐẶT TRÊN câu trả lời, bấm để xổ dropdown */}
                            {uniqueCitations.length > 0 && (
                              <div className="mb-2.5 border border-white/[0.04] bg-white/[0.01] rounded-xl overflow-hidden">
                                <button
                                  onClick={() => setShowRagProcessId(showRagProcessId === message.id ? null : message.id)}
                                  className="w-full px-3 py-2 flex items-center justify-between text-[12px] text-neutral-500 hover:text-neutral-300 hover:bg-white/[0.02] transition-colors"
                                >
                                  <span className="flex items-center gap-1.5">
                                    <Database className="w-3.5 h-3.5 text-violet-400/50" />
                                    <span>Nguồn truy vấn ({uniqueCitations.length})</span>
                                  </span>
                                  {showRagProcessId === message.id ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                                </button>

                                {showRagProcessId === message.id && (
                                  <div className="p-3 border-t border-white/[0.03] space-y-2 text-[12px]">
                                    {uniqueCitations.map((citation, cIdx) => (
                                      <button
                                        key={citation.chunk_id || cIdx}
                                        onClick={() => setSelectedSource({
                                          name: citation.document_name,
                                          documentId: citation.document_id,
                                          // Gom tất cả chunk cùng tài liệu (theo document_id, fallback tên)
                                          citations: (message.citations ?? []).filter(c =>
                                            (c.document_id || c.document_name) === (citation.document_id || citation.document_name)
                                          ),
                                        })}
                                        className="w-full text-left flex flex-col gap-1 px-3 py-2 rounded-lg bg-white/[0.02] border border-white/[0.05] hover:border-white/[0.1] hover:bg-white/[0.03] transition-colors group"
                                      >
                                        <div className="flex items-center gap-1.5">
                                          <span className="flex items-center justify-center w-4 h-4 rounded bg-violet-500/10 text-[9px] font-bold text-violet-400/70 shrink-0">
                                            {cIdx + 1}
                                          </span>
                                          <FileText className="w-3 h-3 text-violet-400/50 shrink-0" />
                                          <span className="text-[12px] font-medium text-neutral-300 truncate">{citation.document_name}</span>
                                          {citation.section_title && (
                                            <span className="text-[10px] text-emerald-400/60 font-mono truncate max-w-[100px]">· {citation.section_title}</span>
                                          )}
                                          {(() => {
                                            const cnt = (message.citations ?? []).filter(c => (c.document_id || c.document_name) === (citation.document_id || citation.document_name)).length
                                            return cnt > 1 ? (
                                              <span className="text-[9px] text-neutral-500 font-mono shrink-0 ml-1">{cnt} đoạn</span>
                                            ) : null
                                          })()}
                                          <ChevronRight className="w-3 h-3 text-neutral-600 ml-auto shrink-0 group-hover:text-neutral-400" />
                                        </div>
                                        {citation.content_snippet && (
                                          <p className="text-[11px] text-neutral-500 leading-relaxed line-clamp-2 pl-[22px]">
                                            {citation.content_snippet}
                                          </p>
                                        )}
                                      </button>
                                    ))}
                                  </div>
                                )}
                              </div>
                            )}

                            {message.isStreaming && !message.content ? (
                              // Đang chờ backend: hiện các bước "suy nghĩ", tự ẩn khi có câu trả lời
                              <ThinkingIndicator />
                            ) : (
                              <>
                                {renderMessageContent(message.content)}
                                {message.isStreaming && (
                                  <span className="inline-block w-[3px] h-4 bg-emerald-400/70 ml-0.5 rounded-full animate-blink-cursor" />
                                )}
                              </>
                            )}
                          </div>
                        ) : (
                          <p className="whitespace-pre-wrap leading-relaxed text-[14px]">{message.content}</p>
                        )}

                        {/* Timestamp */}
                        <div className="text-[10px] text-neutral-600 text-right mt-2 font-mono">
                          {message.timestamp}
                        </div>
                      </div>
                    </div>

                  </div>
                )
              })}
            </div>
          )}
          <div ref={chatEndRef} />
        </div>

        {/* ===== INPUT BAR ===== */}
        <footer className="p-4 bg-[#0a0a0a]/85 border-t border-white/[0.02] shrink-0">
          <div className="max-w-3xl mx-auto space-y-2">
            <div className="input-container rounded-2xl border border-white/[0.06] bg-white/[0.02] flex flex-col p-1">
              
              {/* Textarea */}
              <textarea
                value={inputMessage}
                onChange={(e) => setInputMessage(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault()
                    handleSend()
                  }
                }}
                placeholder="Hỏi về quy chế, điều luật doanh nghiệp..."
                className="w-full bg-transparent border-0 ring-0 focus:outline-none focus:ring-0 text-[14px] text-neutral-200 px-3 py-2.5 resize-none h-[56px] placeholder:text-neutral-600"
              />

              {/* Search Toggle Panel */}
              {showSearchToggle && (
                <div className="flex items-center justify-between px-3 py-2 bg-white/[0.01] border-t border-white/[0.03] animate-msg-in">
                  <div className="flex items-center gap-2">
                    <Sparkles className={`w-3.5 h-3.5 ${searchToolEnabled ? "text-emerald-400 animate-pulse" : "text-neutral-500"}`} />
                    <span className="text-[12px] font-medium text-neutral-300">Tìm kiếm Internet khi không tìm thấy tài liệu</span>
                  </div>
                  
                  {/* Switch Toggle */}
                  <button
                    onClick={() => setSearchToolEnabled(!searchToolEnabled)}
                    className={`w-9 h-5 rounded-full p-0.5 transition-all relative cursor-pointer ${
                      searchToolEnabled ? "bg-emerald-500/80" : "bg-white/[0.08]"
                    }`}
                  >
                    <div
                      className={`w-4 h-4 rounded-full bg-white shadow-md transition-all absolute top-0.5 ${
                        searchToolEnabled ? "left-[18px]" : "left-0.5"
                      }`}
                    />
                  </button>
                </div>
              )}

              {/* Toolbar */}
              <div className="flex items-center justify-between px-2 pt-1 border-t border-white/[0.03]">
                <div className="flex items-center gap-1">
                  <button 
                    onClick={() => setShowSearchToggle(!showSearchToggle)}
                    className={`p-1.5 rounded-lg transition-colors cursor-pointer ${
                      showSearchToggle 
                        ? "bg-emerald-500/10 text-emerald-400" 
                        : "text-neutral-600 hover:text-neutral-300 hover:bg-white/[0.04]"
                    }`}
                    title="Tìm kiếm Internet fallback"
                  >
                    <Plus className="w-4 h-4" />
                  </button>

                  <button 
                    onClick={() => {
                      setShowRightPanel(true)
                      setRightPanelTab("docs")
                    }}
                    className="p-1.5 rounded-lg text-neutral-600 hover:text-neutral-300 hover:bg-white/[0.04] transition-colors cursor-pointer"
                    title="Upload / Chọn tài liệu"
                  >
                    <Paperclip className="w-4 h-4" />
                  </button>
                  
                  <span className="text-[10px] text-neutral-600 select-none ml-1">
                    Enter để gửi · Shift+Enter xuống dòng
                  </span>
                </div>

                {/* Send Button */}
                <button
                  onClick={handleSend}
                  disabled={!inputMessage.trim() || isLlmGenerating}
                  className={`p-2 rounded-xl transition-all ${
                    inputMessage.trim() && !isLlmGenerating
                      ? "bg-emerald-500/80 text-white hover:bg-emerald-500 active:scale-95"
                      : "bg-white/[0.03] text-neutral-700 cursor-not-allowed"
                  }`}
                >
                  <Send className="w-4 h-4" />
                </button>
              </div>
            </div>

            {/* Disclaimer */}
            <div className="text-[10px] text-neutral-600 text-center leading-normal">
              Enterprise Knowledge RAG có thể mắc sai sót. Hãy đối chiếu với văn bản gốc.
            </div>
          </div>
        </footer>
      </main>

      {/* ===== RIGHT PANEL ===== */}
      {showRightPanel && (
        <aside className="w-[300px] border-l border-white/[0.04] bg-[#0f0f0f]/80 backdrop-blur-xl shrink-0 flex flex-col h-full overflow-hidden">
          
          {/* Tabs */}
          <div className="flex border-b border-white/[0.04] p-2 gap-1 shrink-0">
            <button
              onClick={() => setRightPanelTab("docs")}
              className={`flex-1 py-1.5 text-center text-[12px] font-medium rounded-lg flex items-center justify-center gap-1.5 transition-all ${
                rightPanelTab === "docs"
                  ? "bg-white/[0.06] text-neutral-200"
                  : "text-neutral-500 hover:text-neutral-300"
              }`}
            >
              <FileText className="w-3.5 h-3.5" />
              Tài liệu
            </button>
            <button
              onClick={() => setRightPanelTab("settings")}
              className={`flex-1 py-1.5 text-center text-[12px] font-medium rounded-lg flex items-center justify-center gap-1.5 transition-all ${
                rightPanelTab === "settings"
                  ? "bg-white/[0.06] text-neutral-200"
                  : "text-neutral-500 hover:text-neutral-300"
              }`}
            >
              <Settings className="w-3.5 h-3.5" />
              Cấu hình
            </button>
            
            <button 
              onClick={() => setShowRightPanel(false)}
              className="p-1 rounded-md text-neutral-600 hover:text-neutral-300 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* TAB: Documents */}
          {rightPanelTab === "docs" && (
            <div className="flex-1 overflow-y-auto p-4 flex flex-col justify-between space-y-5 scrollbar-thin">
              
              {/* Document List */}
              <div className="space-y-3">
                <div className="flex justify-between items-center text-[10px] font-semibold text-neutral-500 uppercase tracking-wider">
                  <span>Kho tài liệu ({conversationDocs.length})</span>
                  {isLlmGenerating && (
                    <span className="text-amber-400/70 normal-case font-normal">Đang truy vấn — khóa chọn</span>
                  )}
                </div>

                {conversationDocs.length === 0 && (
                  <p className="text-[11px] text-neutral-600 leading-relaxed py-2">
                    Chưa có tài liệu nào trong hội thoại này. Tải tài liệu lên (bên dưới) để dùng cho câu trả lời.
                  </p>
                )}

                <div className={`space-y-1.5 max-h-[320px] overflow-y-auto pr-1 scrollbar-thin ${isLlmGenerating ? "opacity-60 pointer-events-none" : ""}`}>
                  {conversationDocs.map((doc) => {
                    const isIndexed = doc.status === "indexed";
                    // checkbox = active (chỉ doc đã index xong mới chọn được cho RAG).
                    const isChecked = isIndexed && doc.is_active;
                    return (
                      <div
                        key={doc.id}
                        onClick={() => isIndexed && handleToggleDoc(doc.id)}
                        title={isIndexed ? (doc.is_active ? "Bấm để bỏ chọn (không dùng cho truy vấn)" : "Bấm để chọn dùng cho truy vấn") : "Tài liệu chưa xử lý xong"}
                        className={`p-3 rounded-xl border text-[12px] transition-all flex items-start justify-between gap-3 ${
                          !isIndexed
                            ? "cursor-not-allowed opacity-60 bg-transparent border-white/[0.04] text-neutral-500"
                            : isChecked
                              ? "cursor-pointer bg-white/[0.03] border-emerald-500/15 text-neutral-200"
                              : "cursor-pointer bg-transparent border-white/[0.04] text-neutral-400 hover:bg-white/[0.02]"
                        }`}
                      >
                        <div className="min-w-0 flex-1 space-y-1">
                          <div className="flex items-center gap-1.5 font-medium text-neutral-300">
                            <FileText className={`w-3.5 h-3.5 shrink-0 ${isChecked ? "text-emerald-400/60" : "text-neutral-600"}`} />
                            <span className="truncate">{doc.name}</span>
                          </div>
                          <p className="text-[10px] text-neutral-600 line-clamp-1 leading-normal ml-5">
                            {doc.source || `${doc.type.toUpperCase()} document`}
                          </p>
                          <div className="flex items-center gap-2 text-[9px] text-neutral-600 font-mono ml-5">
                            <span className="uppercase">{doc.type}</span>
                            <span className="text-neutral-700">·</span>
                            <span>
                              {doc.file_size 
                                ? (doc.file_size > 1024 * 1024 
                                    ? (doc.file_size / (1024 * 1024)).toFixed(1) + " MB" 
                                    : (doc.file_size / 1024).toFixed(0) + " KB")
                                : "N/A"}
                            </span>
                          </div>
                        </div>

                        {/* Checkbox (indexed) hoặc badge trạng thái (chưa xong) */}
                        {isIndexed ? (
                          <div className={`w-4 h-4 rounded-md border mt-0.5 flex items-center justify-center shrink-0 transition-all ${
                            isChecked
                              ? "bg-emerald-500/80 border-emerald-500/80 text-white"
                              : "border-white/[0.1] bg-transparent"
                          }`}>
                            {isChecked && <Check className="w-2.5 h-2.5 stroke-[3px]" />}
                          </div>
                        ) : doc.status === "failed" ? (
                          <div className="flex items-center gap-1 text-[9px] font-medium text-red-400/80 shrink-0 mt-0.5">
                            <AlertTriangle className="w-3 h-3" />
                            <span>Lỗi</span>
                          </div>
                        ) : (
                          <div className="flex items-center gap-1 text-[9px] font-medium text-amber-400/80 shrink-0 mt-0.5">
                            <RefreshCw className="w-3 h-3 animate-spin" />
                            <span>Đang xử lý</span>
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>

              {/* Upload Zone */}
              <div className="space-y-3 border-t border-white/[0.04] pt-4">
                <div className="text-[10px] font-semibold text-neutral-500 uppercase tracking-wider">
                  Tải lên tài liệu mới
                </div>

                <div
                  onDragOver={onDragOver}
                  onDrop={onDrop}
                  onClick={() => fileInputRef.current?.click()}
                  className="border border-dashed border-white/[0.06] bg-white/[0.01] hover:bg-white/[0.03] hover:border-white/[0.1] rounded-xl p-5 text-center cursor-pointer transition-all flex flex-col items-center justify-center gap-2"
                >
                  <input
                    type="file"
                    ref={fileInputRef}
                    onChange={handleFileChange}
                    className="hidden"
                    accept=".pdf,.docx,.txt"
                  />
                  <UploadCloud className="w-7 h-7 text-neutral-600" />
                  <div>
                    <p className="text-[12px] font-medium text-neutral-400">Nhấp hoặc kéo thả</p>
                    <p className="text-[10px] text-neutral-600 mt-0.5">.pdf, .docx, .txt · Tối đa 15MB</p>
                  </div>
                </div>

                {/* Upload Progress */}
                {uploadProgress && (
                  <div className="p-3 bg-white/[0.02] border border-white/[0.04] rounded-xl space-y-2">
                    <div className="flex justify-between items-center text-[12px]">
                      <span className="font-medium text-neutral-300 truncate max-w-[170px]">
                        {uploadProgress.fileName}
                      </span>
                      <span className="text-[10px] font-mono text-emerald-400/70 font-bold">
                        {uploadProgress.progress}%
                      </span>
                    </div>

                    {/* Progress Bar */}
                    <div className="w-full h-1 bg-white/[0.04] rounded-full overflow-hidden">
                      <div 
                        className="h-full bg-gradient-to-r from-emerald-500/70 to-teal-500/70 transition-all duration-300 rounded-full"
                        style={{ width: `${uploadProgress.progress}%` }}
                      />
                    </div>

                    <div className="flex items-center gap-1.5 text-[10px] text-neutral-500">
                      <RefreshCw className="w-2.5 h-2.5 animate-gentle-spin text-emerald-400/60" />
                      <span className="truncate">{uploadProgress.stepText}</span>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* TAB: Settings */}
          {rightPanelTab === "settings" && (
            <div className="flex-1 overflow-y-auto p-4 space-y-5 text-[12px] scrollbar-thin">
              
              {/* ===== MODEL SELECTION ===== */}
              <div className="space-y-2">
                <label className="font-medium text-neutral-400 text-[11px] uppercase tracking-wider">Mô hình LLM</label>
                <select
                  value={ragSettings.model}
                  onChange={(e) => setRagSettings({ ...ragSettings, model: e.target.value })}
                  className="w-full bg-white/[0.03] border border-white/[0.06] rounded-lg p-2.5 text-neutral-200 focus:outline-none focus:border-emerald-500/20 text-[13px]"
                >
                  <optgroup label="Mặc định">
                    {defaultModels.map((m) => (
                      <option key={m.value} value={m.value}>{m.label}</option>
                    ))}
                  </optgroup>
                  {customModels.length > 0 && (
                    <optgroup label="Model của bạn">
                      {customModels.map((m) => (
                        <option key={m.id} value={m.name}>{m.name}</option>
                      ))}
                    </optgroup>
                  )}
                </select>

                {/* Selected custom model API key indicator */}
                {customModels.find(m => m.name === ragSettings.model) && (
                  <div className="flex items-center gap-1.5 text-[10px] text-emerald-400/60">
                    <Key className="w-3 h-3" />
                    <span>API Key đã được cấu hình cho model này</span>
                  </div>
                )}
              </div>

              {/* ===== CUSTOM MODELS MANAGEMENT ===== */}
              <div className="space-y-2.5 border-t border-white/[0.04] pt-4">
                <div className="flex items-center justify-between">
                  <label className="font-medium text-neutral-400 text-[11px] uppercase tracking-wider">Model tùy chỉnh</label>
                  <button
                    onClick={() => setShowAddModel(!showAddModel)}
                    className={`flex items-center gap-1 text-[11px] font-medium px-2 py-1 rounded-lg transition-all ${
                      showAddModel 
                        ? 'bg-white/[0.06] text-neutral-200' 
                        : 'text-emerald-400/70 hover:text-emerald-400 hover:bg-white/[0.03]'
                    }`}
                  >
                    {showAddModel ? <X className="w-3 h-3" /> : <CirclePlus className="w-3 h-3" />}
                    {showAddModel ? 'Hủy' : 'Thêm'}
                  </button>
                </div>

                {/* Add new model form */}
                {showAddModel && (
                  <div className="space-y-2 p-3 bg-white/[0.02] border border-white/[0.05] rounded-xl animate-msg-in">
                    <div className="space-y-1">
                      <label className="text-[10px] text-neutral-500">Tên model</label>
                      <input
                        type="text"
                        value={newModelName}
                        onChange={(e) => setNewModelName(e.target.value)}
                        placeholder="vd: Claude 3.5 Sonnet..."
                        className="w-full bg-white/[0.03] border border-white/[0.06] rounded-lg px-2.5 py-2 text-neutral-200 focus:outline-none focus:border-emerald-500/20 text-[12px] placeholder:text-neutral-600"
                      />
                    </div>
                    <div className="space-y-1">
                      <label className="text-[10px] text-neutral-500">API Key</label>
                      <div className="relative">
                        <input
                          type={visibleApiKeys.has('new') ? 'text' : 'password'}
                          value={newModelApiKey}
                          onChange={(e) => setNewModelApiKey(e.target.value)}
                          placeholder="sk-..."
                          className="w-full bg-white/[0.03] border border-white/[0.06] rounded-lg px-2.5 py-2 pr-9 text-neutral-200 focus:outline-none focus:border-emerald-500/20 text-[12px] font-mono placeholder:text-neutral-600"
                        />
                        <button
                          onClick={() => {
                            const next = new Set(visibleApiKeys);
                            if (next.has('new')) next.delete('new'); else next.add('new');
                            setVisibleApiKeys(next);
                          }}
                          className="absolute right-2 top-1/2 -translate-y-1/2 text-neutral-600 hover:text-neutral-300 transition-colors"
                        >
                          {visibleApiKeys.has('new') ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                        </button>
                      </div>
                    </div>
                    <button
                      onClick={() => {
                        if (!newModelName.trim() || !newModelApiKey.trim()) return;
                        const newModel: CustomModel = {
                          id: `model-${Date.now()}`,
                          name: newModelName.trim(),
                          apiKey: newModelApiKey.trim(),
                        };
                        setCustomModels(prev => [...prev, newModel]);
                        setRagSettings({ ...ragSettings, model: newModel.name });
                        setNewModelName('');
                        setNewModelApiKey('');
                        setShowAddModel(false);
                        const next = new Set(visibleApiKeys);
                        next.delete('new');
                        setVisibleApiKeys(next);
                      }}
                      disabled={!newModelName.trim() || !newModelApiKey.trim()}
                      className={`w-full py-2 rounded-lg text-[12px] font-medium transition-all ${
                        newModelName.trim() && newModelApiKey.trim()
                          ? 'bg-emerald-500/80 text-white hover:bg-emerald-500 active:scale-[0.98]'
                          : 'bg-white/[0.03] text-neutral-600 cursor-not-allowed'
                      }`}
                    >
                      Thêm model
                    </button>
                  </div>
                )}

                {/* Custom models list */}
                {customModels.length > 0 && (
                  <div className="space-y-1.5">
                    {customModels.map((model) => {
                      const isSelected = ragSettings.model === model.name;
                      const isKeyVisible = visibleApiKeys.has(model.id);
                      return (
                        <div
                          key={model.id}
                          className={`p-2.5 rounded-xl border transition-all ${
                            isSelected
                              ? 'bg-emerald-500/[0.04] border-emerald-500/15'
                              : 'bg-white/[0.01] border-white/[0.04] hover:bg-white/[0.02]'
                          }`}
                        >
                          <div className="flex items-center justify-between mb-1.5">
                            <button
                              onClick={() => setRagSettings({ ...ragSettings, model: model.name })}
                              className="flex items-center gap-1.5 text-[12px] font-medium text-neutral-200 hover:text-white transition-colors"
                            >
                              <Sparkles className={`w-3 h-3 ${isSelected ? 'text-emerald-400/70' : 'text-neutral-600'}`} />
                              {model.name}
                            </button>
                            <button
                              onClick={() => {
                                setCustomModels(prev => prev.filter(m => m.id !== model.id));
                                if (ragSettings.model === model.name) {
                                  setRagSettings({ ...ragSettings, model: defaultModels[0].value });
                                }
                              }}
                              className="p-1 rounded-md text-neutral-600 hover:text-red-400 hover:bg-white/[0.04] transition-all"
                              title="Xóa model"
                            >
                              <Trash2 className="w-3 h-3" />
                            </button>
                          </div>

                          {/* API Key display */}
                          <div className="flex items-center gap-1.5">
                            <Key className="w-3 h-3 text-neutral-600 shrink-0" />
                            <span className="text-[10px] font-mono text-neutral-500 flex-1 truncate">
                              {isKeyVisible ? model.apiKey : '•'.repeat(Math.min(model.apiKey.length, 32))}
                            </span>
                            <button
                              onClick={() => {
                                const next = new Set(visibleApiKeys);
                                  if (next.has(model.id)) next.delete(model.id); else next.add(model.id);
                                  setVisibleApiKeys(next);
                              }}
                              className="text-neutral-600 hover:text-neutral-300 transition-colors shrink-0"
                            >
                              {isKeyVisible ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
                            </button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* ===== SEARCH MODE ===== */}
              <div className="space-y-1.5 border-t border-white/[0.04] pt-4">
                <label className="font-medium text-neutral-400 text-[11px] uppercase tracking-wider">Chế độ tra cứu</label>
                <div className="grid grid-cols-3 gap-1">
                  {["Lai (Hybrid)", "Vector", "Từ khóa"].map((mode) => {
                    const isSel = ragSettings.searchMode === mode;
                    return (
                      <button
                        key={mode}
                        onClick={() => setRagSettings({ ...ragSettings, searchMode: mode })}
                        className={`py-2 rounded-lg text-[11px] font-medium border transition-all ${
                          isSel
                            ? "bg-emerald-500/[0.08] border-emerald-500/20 text-emerald-300"
                            : "bg-white/[0.02] border-white/[0.04] text-neutral-500 hover:text-neutral-300"
                        }`}
                      >
                        {mode}
                      </button>
                    )
                  })}
                </div>
              </div>

              {/* ===== TOP K ===== */}
              <div className="space-y-1.5">
                <div className="flex justify-between font-medium">
                  <span className="text-neutral-400 text-[11px] uppercase tracking-wider">Top K</span>
                  <span className="text-emerald-400/70 font-mono text-[12px]">{ragSettings.topK} chunks</span>
                </div>
                <input
                  type="range"
                  min="1"
                  max="10"
                  value={ragSettings.topK}
                  onChange={(e) => setRagSettings({ ...ragSettings, topK: parseInt(e.target.value) })}
                  className="w-full accent-emerald-500 cursor-pointer"
                />
              </div>

              {/* ===== SIMILARITY THRESHOLD ===== */}
              <div className="space-y-1.5">
                <div className="flex justify-between font-medium">
                  <span className="text-neutral-400 text-[11px] uppercase tracking-wider">Ngưỡng tương đồng</span>
                  <span className="text-emerald-400/70 font-mono text-[12px]">{ragSettings.similarityThreshold}</span>
                </div>
                <input
                  type="range"
                  min="0.1"
                  max="0.8"
                  step="0.05"
                  value={ragSettings.similarityThreshold}
                  onChange={(e) => setRagSettings({ ...ragSettings, similarityThreshold: parseFloat(e.target.value) })}
                  className="w-full accent-emerald-500 cursor-pointer"
                />
              </div>

              {/* ===== SYSTEM PROMPT ===== */}
              <div className="space-y-1.5">
                <label className="font-medium text-neutral-400 text-[11px] uppercase tracking-wider">System Prompt</label>
                <textarea
                  value={ragSettings.systemPrompt}
                  onChange={(e) => setRagSettings({ ...ragSettings, systemPrompt: e.target.value })}
                  className="w-full bg-white/[0.03] border border-white/[0.06] rounded-lg p-2.5 text-neutral-300 focus:outline-none focus:border-emerald-500/20 h-28 resize-none text-[12px] leading-relaxed"
                />
              </div>

              {/* Info */}
              <div className="p-3 bg-white/[0.02] border border-white/[0.04] rounded-lg text-[10px] text-neutral-500 flex gap-2 items-start leading-relaxed">
                <Info className="w-3.5 h-3.5 mt-0.5 text-emerald-500/40 shrink-0" />
                <span>Cấu hình sẽ áp dụng cho lượt hội thoại tiếp theo. API Key được lưu cục bộ trên trình duyệt.</span>
              </div>
            </div>
          )}
        </aside>
      )}

      {/* ===== CITATION DETAIL DRAWER ===== */}
      {selectedSource && (
        <div className="fixed inset-0 z-50 flex justify-end overlay-backdrop">
          <div className="absolute inset-0" onClick={() => setSelectedSource(null)} />

          <div className="relative w-full max-w-lg h-full bg-[#111111] border-l border-white/[0.06] shadow-2xl flex flex-col z-10 animate-slide-in-right">

            <div className="p-4 border-b border-white/[0.04] flex items-center justify-between">
              <div className="flex items-center gap-2 min-w-0">
                <BookOpen className="w-4 h-4 text-emerald-400/60 shrink-0" />
                <h3 className="font-bold text-neutral-200 text-sm truncate">Trích dẫn nguồn</h3>
              </div>
              <button
                onClick={() => setSelectedSource(null)}
                className="p-1.5 rounded-lg hover:bg-white/[0.04] text-neutral-500 hover:text-neutral-200 transition-colors shrink-0"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-5 space-y-5 scrollbar-thin">

              {/* Document header */}
              <div className="glass-card p-4 rounded-xl space-y-1">
                <div className="flex items-start gap-2">
                  <FileText className="w-4 h-4 text-violet-400/60 mt-0.5 shrink-0" />
                  <div className="min-w-0">
                    <h4 className="font-bold text-neutral-100 text-sm break-words">{selectedSource.name}</h4>
                    <p className="text-[11px] text-neutral-500 mt-0.5">
                      Document ID: {selectedSource.documentId} · {selectedSource.citations.length} đoạn trích
                    </p>
                  </div>
                </div>
              </div>

              {/* Danh sách TẤT CẢ đoạn trích (chunk) của tài liệu này */}
              <div className="space-y-3">
                <span className="text-[10px] font-semibold text-neutral-500 uppercase tracking-wider">
                  Các đoạn trích dẫn ({selectedSource.citations.length})
                </span>

                {selectedSource.citations.map((cit, i) => (
                  <div key={cit.chunk_id || i} className="bg-white/[0.02] border border-white/[0.04] rounded-xl p-4 space-y-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="flex items-center gap-1.5 text-[11px] text-neutral-400 min-w-0">
                        <span className="flex items-center justify-center w-4 h-4 rounded bg-violet-500/10 text-[9px] font-bold text-violet-400/70 shrink-0">
                          {i + 1}
                        </span>
                        {cit.section_title
                          ? <span className="text-emerald-400/70 font-mono truncate">{cit.section_title}</span>
                          : <span className="text-neutral-600 font-mono truncate">chunk {cit.chunk_id.slice(0, 8)}</span>}
                        {cit.page_number && <span className="text-neutral-600 shrink-0">· tr.{cit.page_number}</span>}
                      </span>

                      <button
                        onClick={() => copyToClipboard(cit.content_snippet, cit.chunk_id)}
                        className="flex items-center gap-1 text-[11px] text-neutral-500 hover:text-emerald-400 transition-colors shrink-0"
                      >
                        {copiedChunkId === cit.chunk_id ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                        <span>{copiedChunkId === cit.chunk_id ? "Đã chép" : "Chép"}</span>
                      </button>
                    </div>

                    <div className="text-neutral-300 text-[13px] leading-relaxed whitespace-pre-wrap select-text">
                      {cit.content_snippet}
                    </div>

                    {cit.source_link && (
                      <a href={cit.source_link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-[11px] text-emerald-400/80 hover:text-emerald-400 underline break-all">
                        <Sparkles className="w-3 h-3 shrink-0" />
                        {cit.source_link}
                      </a>
                    )}
                  </div>
                ))}
              </div>

            </div>

            {/* Footer */}
            <div className="p-4 border-t border-white/[0.04] flex gap-2">
              <Button
                onClick={() => {
                  setInputMessage(prev => prev + ` Dựa trên thông tin tại ${selectedSource.name}:`);
                  setSelectedSource(null);
                }}
                className="flex-1 bg-emerald-500/80 hover:bg-emerald-500 text-white text-[12px] py-2 rounded-xl font-medium border-0 cursor-pointer"
              >
                Trích soạn thảo tiếp
              </Button>
              <Button
                onClick={() => setSelectedSource(null)}
                variant="outline"
                className="bg-transparent border-white/[0.06] text-neutral-400 hover:text-neutral-200 hover:bg-white/[0.04] text-[12px] py-2 rounded-xl"
              >
                Đóng
              </Button>
            </div>

          </div>
        </div>
      )}
    </div>
  )
}
