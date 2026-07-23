"use client"

import React, { useState, useRef } from "react"
import { useRouter } from "next/navigation"
import {
  FileText,
  Search,
  UploadCloud,
  Check,
  Trash2,
  Database,
  Calendar,
  HardDrive,
  Layers,
  Info,
  BookOpen,
  X,
  PanelLeftOpen,
  RefreshCw,
  MessageSquare,
  ChevronDown
} from "lucide-react"
import { useApp } from "@/lib/context"
import { Button } from "@/components/ui/button"
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogFooter,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogAction,
  AlertDialogCancel,
} from "@/components/ui/alert-dialog"
import { type Document } from "@/lib/api"

export default function DocumentLibrary() {
  const {
    documents,
    uploadProgress,
    processFile,
    deleteDocument,
    reindexDocument,
    toggleDocActive,
    setDocConversations,
    chatSessions,
    showLeftSidebar,
    setShowLeftSidebar,
    setActiveSessionId,
    loadConversation,
  } = useApp()

  // Hội thoại đã lưu (bỏ session mới chưa lưu "new-...") để gắn tài liệu
  const savedConversations = chatSessions.filter(s => !s.id.startsWith("new-"))

  const router = useRouter()

  const [searchQuery, setSearchQuery] = useState("")
  const [filterType, setFilterType] = useState<"all" | "pdf" | "docx" | "txt">("all")
  const [selectedDocForDetail, setSelectedDocForDetail] = useState<Document | null>(null)
  // Tài liệu đang trong quá trình xóa — blur card + khóa thao tác ngay khi bấm xóa,
  // thay vì đợi request DELETE (soft-delete + audit log) hoàn tất mới phản hồi UI.
  const [deletingIds, setDeletingIds] = useState<Set<string>>(new Set())
  // Tài liệu đang chờ xác nhận xóa (hộp thoại Hủy / Xác nhận)
  const [docPendingDelete, setDocPendingDelete] = useState<{ id: string; name: string } | null>(null)

  const fileInputRef = useRef<HTMLInputElement>(null)

  // Calculate statistics
  const totalFiles = documents.length
  const activeFiles = documents.filter(d => d.is_active).length
  const totalChunks = documents.length // We don't have local chunk count from API
  
  // Format total size (e.g. "4.45 MB")
  const totalSize = documents.reduce((acc, doc) => {
    return acc + (doc.file_size || 0);
  }, 0)
  const totalSizeStr = totalSize > 1024 * 1024 
    ? (totalSize / (1024 * 1024)).toFixed(1) + " MB"
    : (totalSize / 1024).toFixed(0) + " KB"

  // Handle Drag & Drop
  const onDragOver = (e: React.DragEvent) => {
    e.preventDefault()
  }

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault()
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      // Upload ở trang thư viện → không gắn hội thoại nào (vào kho tổng)
      processFile(e.dataTransfer.files[0], false)
    }
  }

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      processFile(e.target.files[0], false)
    }
  }

  const handleToggleDoc = (docId: string) => {
    toggleDocActive(docId)
  }

  // Bật/tắt gắn tài liệu vào 1 hội thoại (checklist multi-select)
  const handleToggleDocConversation = (doc: Document, conversationId: string) => {
    const current = doc.conversations.map(c => c.id)
    const next = current.includes(conversationId)
      ? current.filter(id => id !== conversationId)
      : [...current, conversationId]
    setDocConversations(doc.id, next)
  }

  // Mở hộp thoại xác nhận (Hủy / Xác nhận) trước khi xóa
  const handleDeleteDoc = (docId: string, docName: string) => {
    setDocPendingDelete({ id: docId, name: docName })
  }

  // Người dùng bấm "Xác nhận" trong hộp thoại
  const confirmDeleteDoc = async () => {
    if (!docPendingDelete) return
    const { id: docId } = docPendingDelete
    setDocPendingDelete(null)
    // Blur + khóa card ngay lập tức để người dùng thấy phản hồi tức thì, không đợi request xong
    setDeletingIds(prev => new Set(prev).add(docId))
    try {
      await deleteDocument(docId)
      // Thành công: doc đã bị lọc khỏi `documents` trong context → card tự unmount, không cần dọn deletingIds
    } catch {
      alert("Không thể xóa tài liệu. Vui lòng thử lại.")
      setDeletingIds(prev => {
        const next = new Set(prev)
        next.delete(docId)
        return next
      })
    }
  }

  // Nhảy tới hội thoại đã gắn tài liệu
  const handleJumpToConversation = (conversationId: string) => {
    setActiveSessionId(conversationId)
    loadConversation(conversationId)
    router.push("/")
  }

  // Filter documents
  const filteredDocs = documents.filter(doc => {
    const matchesSearch = doc.name.toLowerCase().includes(searchQuery.toLowerCase())
    const matchesType = filterType === "all" || doc.type === filterType
    return matchesSearch && matchesType
  })

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden">
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
          <h2 className="text-sm font-semibold text-neutral-200">
            Thư viện tài liệu
          </h2>
        </div>
        
        <div className="text-[11px] text-neutral-500 hidden sm:block">
          Kho lưu trữ tri thức hệ thống RAG
        </div>
      </header>

      {/* Main Workspace */}
      <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-6 scrollbar-thin">
        
        {/* ===== STATS DASHBOARD ===== */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <div className="glass-card p-4 rounded-xl flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-emerald-500/10 border border-emerald-500/15 flex items-center justify-center shrink-0">
              <FileText className="w-5 h-5 text-emerald-400/80" />
            </div>
            <div>
              <div className="text-[10px] text-neutral-500 font-semibold uppercase tracking-wider">Tổng tài liệu</div>
              <div className="text-xl font-bold text-neutral-100 font-mono mt-0.5">{totalFiles}</div>
            </div>
          </div>

          <div className="glass-card p-4 rounded-xl flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-teal-500/10 border border-teal-500/15 flex items-center justify-center shrink-0">
              <Check className="w-5 h-5 text-teal-400/80" />
            </div>
            <div>
              <div className="text-[10px] text-neutral-500 font-semibold uppercase tracking-wider">Đang hoạt động</div>
              <div className="text-xl font-bold text-neutral-100 font-mono mt-0.5">{activeFiles} <span className="text-xs text-neutral-500 font-normal">/ {totalFiles}</span></div>
            </div>
          </div>

          <div className="glass-card p-4 rounded-xl flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-sky-500/10 border border-sky-500/15 flex items-center justify-center shrink-0">
              <Layers className="w-5 h-5 text-sky-400/80" />
            </div>
            <div>
              <div className="text-[10px] text-neutral-500 font-semibold uppercase tracking-wider">Phân mảnh vector</div>
              <div className="text-xl font-bold text-neutral-100 font-mono mt-0.5">{totalChunks} <span className="text-[10px] text-neutral-500 font-normal uppercase">docs</span></div>
            </div>
          </div>

          <div className="glass-card p-4 rounded-xl flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-violet-500/10 border border-violet-500/15 flex items-center justify-center shrink-0">
              <HardDrive className="w-5 h-5 text-violet-400/80" />
            </div>
            <div>
              <div className="text-[10px] text-neutral-500 font-semibold uppercase tracking-wider">Kích thước DB</div>
              <div className="text-xl font-bold text-neutral-100 font-mono mt-0.5">{totalSizeStr}</div>
            </div>
          </div>
        </div>

        {/* ===== SEARCH & FILTER ZONE ===== */}
        <div className="flex flex-col md:flex-row gap-3">
          {/* Search bar */}
          <div className="flex-1 relative">
            <Search className="w-4 h-4 text-neutral-500 absolute left-3.5 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Tìm kiếm tài liệu theo tên, mã hiệu, mô tả..."
              className="w-full bg-[#0f0f0f]/60 backdrop-blur-md border border-white/[0.06] rounded-xl pl-10 pr-4 py-2.5 text-[13px] text-neutral-200 focus:outline-none focus:border-emerald-500/20 placeholder:text-neutral-600 transition-colors"
            />
          </div>

          {/* Type filters */}
          <div className="flex bg-[#0f0f0f]/60 backdrop-blur-md border border-white/[0.06] rounded-xl p-1 gap-1 shrink-0 self-start">
            {[
              { label: "Tất cả", value: "all" },
              { label: "PDF", value: "pdf" },
              { label: "DOCX", value: "docx" },
              { label: "TXT", value: "txt" }
            ].map((pill) => {
              const isSel = filterType === pill.value;
              return (
                <button
                  key={pill.value}
                  onClick={() => setFilterType(pill.value as any)}
                  className={`px-3 py-1.5 rounded-lg text-[12px] font-medium transition-all cursor-pointer ${
                    isSel 
                      ? "bg-white/[0.06] text-neutral-100" 
                      : "text-neutral-500 hover:text-neutral-300"
                  }`}
                >
                  {pill.label}
                </button>
              )
            })}
          </div>
        </div>

        {/* ===== UPLOAD ZONE AND LIST GRID ===== */}
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-6 items-start">
          
          {/* Document list */}
          <div className="xl:col-span-2 space-y-3">
            <h3 className="text-[11px] font-semibold text-neutral-500 uppercase tracking-wider mb-2">
              Danh sách tài liệu ({filteredDocs.length})
            </h3>

            {filteredDocs.length === 0 ? (
              <div className="text-center py-16 bg-[#0f0f0f]/20 border border-dashed border-white/[0.04] rounded-2xl">
                <FileText className="w-10 h-10 text-neutral-700 mx-auto mb-3" />
                <p className="text-[13px] text-neutral-500">Không tìm thấy tài liệu phù hợp</p>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {filteredDocs.map((doc) => {
                  const isChecked = doc.is_active;
                  const isDeleting = deletingIds.has(doc.id);
                  return (
                    <div
                      key={doc.id}
                      className={`glass-card p-4 rounded-xl border transition-all duration-300 flex flex-col justify-between gap-4 group ${
                        isChecked
                          ? "border-emerald-500/10 hover:border-emerald-500/20"
                          : "border-white/[0.04] hover:border-white/[0.08]"
                      } ${isDeleting ? "opacity-40 blur-[1.5px] grayscale pointer-events-none select-none" : ""}`}
                    >
                      <div className="space-y-2.5">
                        <div className="flex items-start justify-between gap-3">
                          <div className="flex flex-col gap-2 min-w-0">
                            <div className="flex items-center gap-1.5 font-medium text-neutral-300">
                              <FileText className={`w-3.5 h-3.5 shrink-0 ${isChecked ? "text-emerald-400/60" : "text-neutral-600"}`} />
                              <span className="truncate">{doc.name}</span>
                            </div>
                            <span className="text-[9px] font-mono text-neutral-500 uppercase">{doc.type} · {doc.file_size ? (doc.file_size > 1024*1024 ? (doc.file_size/(1024*1024)).toFixed(1)+' MB' : (doc.file_size/1024).toFixed(0)+' KB') : 'N/A'}</span>
                          </div>

                          {/* Toggle Active Switch */}
                          <button
                            onClick={() => handleToggleDoc(doc.id)}
                            className={`px-2 py-0.5 rounded text-[9px] font-bold tracking-wider uppercase border transition-all ${
                              isChecked
                                ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-400"
                                : "bg-white/[0.02] border-white/[0.06] text-neutral-500 hover:text-neutral-300"
                            }`}
                          >
                            {isChecked ? "Active" : "Inactive"}
                          </button>
                        </div>

                        {/* Status Badge */}
                        <div className="flex items-center gap-1.5 text-[10px]">
                          <span className={`px-2 py-0.5 rounded text-[9px] font-bold tracking-wider uppercase border ${
                            doc.status === 'indexed' ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400' :
                            doc.status === 'processing' ? 'bg-amber-500/10 border-amber-500/20 text-amber-400' :
                            doc.status === 'pending' ? 'bg-sky-500/10 border-sky-500/20 text-sky-400' :
                            'bg-red-500/10 border-red-500/20 text-red-400'
                          }`}>
                            {doc.status}
                          </span>
                        </div>

                        <p className="text-[11px] text-neutral-400/80 leading-relaxed line-clamp-2">
                          {doc.source || `${doc.type.toUpperCase()} document`}
                        </p>

                        {/* Hội thoại đã gắn — chip, bấm để nhảy tới, nút X để gỡ. 1 tài liệu có thể gắn nhiều hội thoại. */}
                        {doc.conversations.length > 0 && (
                          <div className="flex flex-wrap gap-1.5">
                            {doc.conversations.map(c => (
                              <div
                                key={c.id}
                                className="flex items-center gap-1 text-[10px] bg-sky-500/5 hover:bg-sky-500/10 border border-sky-500/10 rounded pl-1.5 pr-1 py-0.5 transition-colors max-w-full"
                              >
                                <button
                                  onClick={() => handleJumpToConversation(c.id)}
                                  title="Mở hội thoại đã gắn tài liệu này"
                                  className="flex items-center gap-1 min-w-0 text-sky-400/70 hover:text-sky-300 cursor-pointer"
                                >
                                  <MessageSquare className="w-2.5 h-2.5 shrink-0" />
                                  <span className="truncate max-w-[100px]">{c.title || "Hội thoại"}</span>
                                </button>
                                <button
                                  onClick={() => handleToggleDocConversation(doc, c.id)}
                                  title="Gỡ tài liệu khỏi hội thoại này"
                                  className="shrink-0 p-0.5 rounded text-neutral-600 hover:text-red-400 hover:bg-white/[0.06] cursor-pointer"
                                >
                                  <X className="w-2.5 h-2.5" />
                                </button>
                              </div>
                            ))}
                          </div>
                        )}

                        {/* Gắn tài liệu vào (thêm) hội thoại — dropdown thay vì list mở sẵn, tránh bị che khi nhiều hội thoại */}
                        {savedConversations.length > 0 && (
                          <details className="group/conv relative">
                            <summary
                              className="flex items-center justify-between gap-2 list-none cursor-pointer bg-[#0f0f0f]/60 border border-white/[0.06] rounded-lg px-2 py-1.5 text-[10px] text-neutral-400 hover:border-sky-500/20 hover:text-neutral-300 transition-colors [&::-webkit-details-marker]:hidden"
                              title="Gắn tài liệu vào một hoặc nhiều hội thoại"
                            >
                              <span>Gắn vào hội thoại…</span>
                              <ChevronDown className="w-3 h-3 shrink-0 text-neutral-500 transition-transform group-open/conv:rotate-180" />
                            </summary>
                            <div className="absolute z-20 mt-1 w-full border border-white/[0.08] rounded-lg bg-[#131313] shadow-xl max-h-40 overflow-y-auto scrollbar-thin">
                              {savedConversations.map(s => {
                                const checked = doc.conversations.some(c => c.id === s.id)
                                return (
                                  <label
                                    key={s.id}
                                    className="flex items-center gap-2 px-2 py-1.5 text-[10px] text-neutral-400 hover:bg-white/[0.04] cursor-pointer"
                                  >
                                    <input
                                      type="checkbox"
                                      checked={checked}
                                      onChange={() => handleToggleDocConversation(doc, s.id)}
                                      className="accent-sky-500 cursor-pointer"
                                    />
                                    <span className="truncate">{s.title || "Hội thoại"}</span>
                                  </label>
                                )
                              })}
                            </div>
                          </details>
                        )}
                      </div>

                      {/* Footer Info */}
                      <div className="flex items-center justify-between pt-3 border-t border-white/[0.04] text-[10px] text-neutral-500 font-mono">
                        <div className="flex items-center gap-1.5">
                          <Calendar className="w-3 h-3 text-neutral-600" />
                          <span>{new Date(doc.created_at).toLocaleDateString()}</span>
                        </div>
                        
                        <div className="flex items-center gap-2">
                          {doc.status === 'failed' && (
                            <button
                              onClick={() => reindexDocument(doc.id)}
                              disabled={isDeleting}
                              className="text-[11px] text-amber-400/70 hover:text-amber-400 transition-colors font-sans flex items-center gap-1 cursor-pointer disabled:cursor-not-allowed"
                            >
                              <RefreshCw className="w-3 h-3" />
                              <span>Reindex</span>
                            </button>
                          )}

                          <button
                            onClick={() => handleDeleteDoc(doc.id, doc.name)}
                            disabled={isDeleting}
                            className="p-1 rounded text-neutral-600 hover:text-red-400 hover:bg-white/[0.04] transition-all cursor-pointer disabled:cursor-not-allowed disabled:hover:text-neutral-600 disabled:hover:bg-transparent"
                            title="Xóa tài liệu"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          {/* Upload panel */}
          <div className="space-y-4">
            <h3 className="text-[11px] font-semibold text-neutral-500 uppercase tracking-wider">
              Tải tài liệu mới
            </h3>

            <div className="glass-card p-5 rounded-xl border border-white/[0.04] space-y-4">
              <div
                onDragOver={onDragOver}
                onDrop={onDrop}
                onClick={() => fileInputRef.current?.click()}
                className="border border-dashed border-white/[0.08] bg-white/[0.01] hover:bg-white/[0.03] hover:border-white/[0.12] rounded-xl p-8 text-center cursor-pointer transition-all flex flex-col items-center justify-center gap-3 group"
              >
                <input
                  type="file"
                  ref={fileInputRef}
                  onChange={handleFileChange}
                  className="hidden"
                  accept=".pdf,.docx,.txt"
                />
                <div className="w-12 h-12 rounded-full bg-emerald-500/5 group-hover:bg-emerald-500/10 flex items-center justify-center transition-all border border-emerald-500/[0.05]">
                  <UploadCloud className="w-6 h-6 text-emerald-400/60" />
                </div>
                <div>
                  <p className="text-[13px] font-medium text-neutral-300">Nhấp chọn hoặc Kéo thả</p>
                  <p className="text-[10px] text-neutral-600 mt-1">Hỗ trợ PDF, DOCX, TXT tối đa 15MB</p>
                </div>
              </div>

              {/* Uploading progress indicator */}
              {uploadProgress && (
                <div className="p-3 bg-white/[0.02] border border-white/[0.04] rounded-xl space-y-2 animate-msg-in">
                  <div className="flex justify-between items-center text-[12px]">
                    <span className="font-medium text-neutral-300 truncate max-w-[170px]">
                      {uploadProgress.fileName}
                    </span>
                    <span className="text-[10px] font-mono text-emerald-400/70 font-bold">
                      {uploadProgress.progress}%
                    </span>
                  </div>

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

              {/* RAG pipeline processing explanation */}
              <div className="p-3.5 bg-violet-500/[0.02] border border-violet-500/[0.06] rounded-xl flex gap-2.5 items-start text-[11px] text-neutral-400 leading-relaxed">
                <Info className="w-4 h-4 text-violet-400/50 mt-0.5 shrink-0" />
                <div>
                  <p className="font-semibold text-neutral-300 mb-0.5">Quy trình RAG Indexing:</p>
                  Tài liệu tải lên sẽ tự động chạy qua pipeline: Đọc nội dung ➜ Tách nhỏ văn bản (Chunking) ➜ Tạo vector nhúng (Embedding) ➜ Lưu trữ vào Vector Database (Milvus/Qdrant) để sẵn sàng tìm kiếm.
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Hộp thoại xác nhận xóa tài liệu — Hủy / Xác nhận */}
      <AlertDialog
        open={docPendingDelete !== null}
        onOpenChange={(open) => !open && setDocPendingDelete(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xóa tài liệu?</AlertDialogTitle>
            <AlertDialogDescription>
              Bạn có chắc muốn xóa tài liệu &quot;{docPendingDelete?.name}&quot;? Hành động này không thể hoàn tác.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction onClick={confirmDeleteDoc}>Xác nhận</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
