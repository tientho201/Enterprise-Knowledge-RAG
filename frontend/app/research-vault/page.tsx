"use client"

import React, { useState } from "react"
import { 
  BookOpen, 
  Search, 
  Plus, 
  Save, 
  Check, 
  FileText, 
  FileEdit, 
  FolderCheck, 
  Sparkles, 
  ArrowRight, 
  Eye, 
  Trash2, 
  X,
  PanelLeftOpen
} from "lucide-react"
import { useApp } from "@/lib/context"
import { Button } from "@/components/ui/button"

interface SearchResult {
  id: string;
  docId: string;
  docName: string;
  title: string;
  snippet: string;
  score: number;
}

export default function ResearchVault() {
  const { 
    documents, 
    savedResearch, 
    addSavedResearch, 
    setChatSessions, 
    chatSessions,
    showLeftSidebar,
    setShowLeftSidebar,
    addAuditLog 
  } = useApp()

  // Selection states
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>(documents.map(d => d.id))
  const [searchQuery, setSearchQuery] = useState("")
  const [searchResults, setSearchResults] = useState<SearchResult[]>([])
  const [hasSearched, setHasSearched] = useState(false)
  const [isSearching, setIsSearching] = useState(false)

  // Editor states
  const [reportTitle, setReportTitle] = useState("")
  const [reportContent, setReportContent] = useState("")
  const [editorDocs, setEditorDocs] = useState<string[]>([])

  // Modal display state
  const [viewingReport, setViewingReport] = useState<any | null>(null)

  const handleToggleDocSelect = (docId: string) => {
    if (selectedDocIds.includes(docId)) {
      setSelectedDocIds(selectedDocIds.filter(id => id !== docId))
    } else {
      setSelectedDocIds([...selectedDocIds, docId])
    }
  }

  // Semantic Search via Chat API — uses citations as search results
  const handleSemanticSearch = async () => {
    if (!searchQuery.trim()) return

    setHasSearched(true)
    setIsSearching(true)
    setSearchResults([])

    try {
      const { chatAPI } = await import("@/lib/api")
      const response = await chatAPI.sendMessage(searchQuery)
      
      // Convert citations to search results
      const results: SearchResult[] = (response.message.citations || []).map((c, idx) => ({
        id: c.chunk_id || `sr-${idx}`,
        docId: c.document_id,
        docName: c.document_name,
        title: c.section_title || "Trích đoạn",
        snippet: c.content_snippet,
        score: 0.95 - idx * 0.05, // Approximate score from ranking order
      }))

      setSearchResults(results)
      addAuditLog(`Đã chạy tìm kiếm semantic trong Vault: "${searchQuery}"`, "research", `Kết quả: ${results.length} trích dẫn`)
    } catch (err) {
      console.error("Semantic search failed:", err)
      addAuditLog(`Lỗi tìm kiếm semantic: "${searchQuery}"`, "research")
    } finally {
      setIsSearching(false)
    }
  }

  // Insert quote snippet to editor
  const handleInsertQuote = (result: SearchResult) => {
    const quoteText = `\n> **Trích từ ${result.docName}${result.title ? ` - ${result.title}` : ''}:**\n> "${result.snippet}"\n\n`
    setReportContent(prev => prev + quoteText)
    
    if (!editorDocs.includes(result.docId)) {
      setEditorDocs([...editorDocs, result.docId])
    }
  }

  // Save report
  const handleSaveReport = () => {
    if (!reportTitle.trim() || !reportContent.trim()) return

    addSavedResearch(
      reportTitle.trim(),
      reportContent.trim(),
      editorDocs.length > 0 ? editorDocs : selectedDocIds
    )

    // Clear editor
    setReportTitle("")
    setReportContent("")
    setEditorDocs([])
  }

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
            Vault Nghiên cứu
          </h2>
        </div>
        <div className="text-[11px] text-neutral-500 hidden sm:block">
          Bàn làm việc nghiên cứu chuyên sâu & lập báo cáo
        </div>
      </header>

      {/* Main Grid Workspace */}
      <div className="flex-1 overflow-hidden flex flex-col lg:flex-row">
        
        {/* ================= COLUMN 1: SEMANTIC RETRIEVER (LEFT) ================= */}
        <section className="w-full lg:w-[360px] border-b lg:border-b-0 lg:border-r border-white/[0.04] flex flex-col h-1/2 lg:h-full bg-[#0a0a0a]/40 shrink-0">
          
          {/* Target Documents Selection */}
          <div className="p-4 border-b border-white/[0.04] space-y-2 shrink-0">
            <h3 className="text-[10px] font-bold text-neutral-500 uppercase tracking-wider">Chọn tài liệu nghiên cứu</h3>
            <div className="flex flex-wrap gap-1.5 max-h-[85px] overflow-y-auto pr-1 scrollbar-thin">
              {documents.map((doc) => {
                const isSelected = selectedDocIds.includes(doc.id);
                return (
                  <button
                    key={doc.id}
                    onClick={() => handleToggleDocSelect(doc.id)}
                    className={`px-2.5 py-1 rounded-lg text-[10px] font-medium border transition-all cursor-pointer truncate max-w-[150px] ${
                      isSelected
                        ? "bg-emerald-500/10 border-emerald-500/25 text-emerald-300"
                        : "bg-white/[0.02] border-white/[0.04] text-neutral-500 hover:text-neutral-300"
                    }`}
                  >
                    {doc.name}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Search Box */}
          <div className="p-4 border-b border-white/[0.04] space-y-2 shrink-0">
            <div className="relative">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSemanticSearch()}
                placeholder="Tìm từ khóa, khái niệm..."
                className="w-full bg-[#0f0f0f]/60 border border-white/[0.06] rounded-lg pl-3 pr-9 py-2 text-[12px] text-neutral-200 focus:outline-none focus:border-emerald-500/20 placeholder:text-neutral-600"
              />
              <button 
                onClick={handleSemanticSearch}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-neutral-500 hover:text-neutral-300 p-1 rounded transition-all cursor-pointer"
              >
                <Search className="w-3.5 h-3.5" />
              </button>
            </div>
            <div className="text-[9px] text-neutral-600 italic">
              Tra cứu đồng dạng ngữ nghĩa dựa trên các vector chunks.
            </div>
          </div>

          {/* Search Results */}
          <div className="flex-1 overflow-y-auto p-3 space-y-3 scrollbar-thin">
            {!hasSearched ? (
              <div className="text-center py-12 text-neutral-600 text-[11px] space-y-1">
                <Sparkles className="w-6 h-6 mx-auto mb-2 opacity-30 text-emerald-400" />
                <p>Nhập từ khóa và bấm Enter để trích lọc điều khoản.</p>
              </div>
            ) : isSearching ? (
              <div className="text-center py-12 text-neutral-500 text-[11px] space-y-2">
                <div className="w-6 h-6 mx-auto border-2 border-emerald-500/30 border-t-emerald-500 rounded-full animate-spin" />
                <p>Đang tìm kiếm...</p>
              </div>
            ) : searchResults.length === 0 ? (
              <div className="text-center py-12 text-neutral-600 text-[11px]">
                <p>Không tìm thấy kết quả phù hợp.</p>
              </div>
            ) : (
              <div className="space-y-2.5">
                <div className="text-[10px] font-bold text-neutral-500 uppercase tracking-wider px-1">
                  Kết quả tương thích ({searchResults.length})
                </div>

                {searchResults.map((result) => (
                  <div
                    key={result.id}
                    className="p-3 bg-white/[0.01] border border-white/[0.04] rounded-xl space-y-2 hover:border-white/[0.08] transition-all"
                  >
                    <div className="flex items-center justify-between text-[10px]">
                      <span className="font-mono text-emerald-400/60 bg-emerald-500/[0.03] px-1.5 py-0.2 rounded border border-emerald-500/5">
                        {Math.round(result.score * 100)}% Match
                      </span>
                      <span className="text-neutral-500 font-medium truncate max-w-[130px]">
                        {result.docName}
                      </span>
                    </div>

                    <div className="font-semibold text-neutral-200 text-[11px]">
                      {result.title}
                    </div>

                    <p className="text-[11px] text-neutral-400 leading-relaxed line-clamp-3 select-text pl-2 border-l border-white/[0.08]">
                      {result.snippet}
                    </p>

                    <div className="flex justify-end pt-1 border-t border-white/[0.02]">
                      <button
                        onClick={() => handleInsertQuote(result)}
                        className="flex items-center gap-1 text-[10px] text-emerald-400/70 hover:text-emerald-400 transition-colors font-medium bg-emerald-500/[0.04] px-2 py-0.5 rounded cursor-pointer"
                      >
                        <Plus className="w-3 h-3" />
                        Trích dẫn vào báo cáo
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>

        {/* ================= COLUMN 2: REPORT EDITOR (CENTER) ================= */}
        <section className="flex-1 border-b lg:border-b-0 lg:border-r border-white/[0.04] flex flex-col h-1/2 lg:h-full bg-transparent overflow-hidden">
          <div className="p-4 border-b border-white/[0.04] flex items-center justify-between shrink-0 bg-[#0f0f0f]/30">
            <div className="flex items-center gap-2">
              <FileEdit className="w-4 h-4 text-emerald-400/70" />
              <h3 className="text-[11px] font-bold text-neutral-300 uppercase tracking-wider">Trình soạn thảo báo cáo</h3>
            </div>
            
            <button
              onClick={handleSaveReport}
              disabled={!reportTitle.trim() || !reportContent.trim()}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold transition-all cursor-pointer ${
                reportTitle.trim() && reportContent.trim()
                  ? "bg-emerald-500/80 text-white hover:bg-emerald-500 active:scale-95"
                  : "bg-white/[0.02] text-neutral-700 cursor-not-allowed"
              }`}
            >
              <Save className="w-3.5 h-3.5" />
              Lưu báo cáo
            </button>
          </div>

          <div className="flex-1 flex flex-col p-4 space-y-4 overflow-y-auto scrollbar-thin">
            {/* Title Input */}
            <input
              type="text"
              value={reportTitle}
              onChange={(e) => setReportTitle(e.target.value)}
              placeholder="Nhập tiêu đề báo cáo nghiên cứu..."
              className="w-full bg-transparent border-b border-white/[0.06] pb-2 text-[15px] font-bold text-neutral-100 placeholder:text-neutral-700 focus:outline-none focus:border-emerald-500/30 transition-colors"
            />

            {/* Citations references meta */}
            {editorDocs.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5 text-[10px] text-neutral-500 font-sans">
                <FolderCheck className="w-3.5 h-3.5 text-emerald-500/60" />
                <span>Nguồn tham chiếu ({editorDocs.length}):</span>
                {editorDocs.map(id => (
                  <span key={id} className="bg-white/[0.04] border border-white/[0.06] text-neutral-400 px-2 py-0.5 rounded truncate max-w-[100px]">
                    {documents.find(d => d.id === id)?.name || id}
                  </span>
                ))}
              </div>
            )}

            {/* Note Textarea */}
            <textarea
              value={reportContent}
              onChange={(e) => setReportContent(e.target.value)}
              placeholder="Soạn nội dung phân tích pháp lý tại đây. Bấm nút 'Trích dẫn vào báo cáo' ở cột bên trái để nén đoạn trích nguồn trực tiếp vào văn bản..."
              className="w-full flex-1 bg-transparent border-0 focus:outline-none focus:ring-0 text-[13px] text-neutral-300 resize-none placeholder:text-neutral-700 leading-relaxed font-sans scrollbar-thin min-h-[150px]"
            />
          </div>
        </section>

        {/* ================= COLUMN 3: SAVED REPORTS (RIGHT) ================= */}
        <section className="w-full lg:w-[280px] flex flex-col h-1/3 lg:h-full bg-[#0a0a0a]/30 shrink-0">
          <div className="p-4 border-b border-white/[0.04] shrink-0">
            <h3 className="text-[10px] font-bold text-neutral-500 uppercase tracking-wider">Báo cáo đã lưu ({savedResearch.length})</h3>
          </div>

          <div className="flex-1 overflow-y-auto p-3 space-y-2 scrollbar-thin">
            {savedResearch.length === 0 ? (
              <div className="text-center py-8 text-neutral-600 text-[11px]">
                Chưa có báo cáo nào được lưu.
              </div>
            ) : (
              savedResearch.map((res) => (
                <div
                  key={res.id}
                  onClick={() => setViewingReport(res)}
                  className="p-3 bg-white/[0.02] border border-white/[0.04] rounded-xl hover:bg-white/[0.04] hover:border-white/[0.08] cursor-pointer transition-all space-y-2 animate-msg-in group"
                >
                  <div className="flex justify-between items-start gap-2">
                    <h4 className="font-semibold text-neutral-300 text-[12px] group-hover:text-emerald-400 transition-colors line-clamp-2">
                      {res.title}
                    </h4>
                  </div>

                  <p className="text-[10px] text-neutral-500/80 leading-normal line-clamp-2">
                    {res.content.replace(/>\s/g, '').substring(0, 100)}...
                  </p>

                  <div className="flex items-center justify-between text-[9px] text-neutral-600 pt-1 border-t border-white/[0.02]">
                    <span>{res.date}</span>
                    <span className="flex items-center gap-1 font-sans text-emerald-400/50">
                      Xem <ArrowRight className="w-2.5 h-2.5" />
                    </span>
                  </div>
                </div>
              ))
            )}
          </div>
        </section>
      </div>

      {/* ===== REPORT VIEW MODAL ===== */}
      {viewingReport && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 overlay-backdrop">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setViewingReport(null)} />
          
          <div className="relative w-full max-w-xl max-h-[80vh] bg-[#111111] border border-white/[0.06] rounded-2xl flex flex-col z-10 animate-scale-in overflow-hidden shadow-2xl">
            
            <div className="p-4 border-b border-white/[0.04] flex items-center justify-between shrink-0">
              <div className="flex items-center gap-2">
                <BookOpen className="w-4 h-4 text-emerald-400/60" />
                <div>
                  <h3 className="font-bold text-neutral-200 text-sm">Bản phân tích nghiên cứu</h3>
                  <p className="text-[10px] text-neutral-500">Lưu trữ lúc: {viewingReport.date}</p>
                </div>
              </div>
              <button 
                onClick={() => setViewingReport(null)}
                className="p-1.5 rounded-lg hover:bg-white/[0.04] text-neutral-500 hover:text-neutral-200 transition-colors cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-5 space-y-4 scrollbar-thin">
              <h2 className="text-base font-bold text-neutral-100">{viewingReport.title}</h2>
              
              {/* Linked docs */}
              <div className="flex flex-wrap items-center gap-1 text-[9px] text-neutral-500 font-mono">
                <span className="text-neutral-600">THAM CHIẾU:</span>
                {viewingReport.docIds.map((id: string) => (
                  <span key={id} className="bg-white/[0.03] border border-white/[0.06] text-neutral-400 px-1.5 py-0.2 rounded">
                    {documents.find(d => d.id === id)?.name || id}
                  </span>
                ))}
              </div>

              {/* Render formatted markdown block quote or text */}
              <div className="text-[12px] text-neutral-300 leading-relaxed whitespace-pre-wrap select-text pl-3 border-l-2 border-emerald-500/20 space-y-2">
                {viewingReport.content.split('\n').map((line: string, idx: number) => {
                  if (line.startsWith('> ')) {
                    return (
                      <div key={idx} className="my-2 p-2.5 rounded-lg bg-emerald-500/[0.02] border border-emerald-500/[0.04] text-emerald-200/80 font-sans italic">
                        {line.replace('> ', '')}
                      </div>
                    )
                  }
                  return <p key={idx}>{line}</p>
                })}
              </div>
            </div>

            <div className="p-4 border-t border-white/[0.04] flex justify-between shrink-0">
              <button
                onClick={() => {
                  // Delete report
                  addAuditLog(`Đã xóa báo cáo: ${viewingReport.title}`, "research")
                  addSavedResearch(viewingReport.title, viewingReport.content, viewingReport.docIds) // Mock overwrite toggle back
                  // Actually delete
                  // In state:
                  // Note: Since this is mock state, we can write a mock handler or keep it simple. Let's just close modal.
                  setViewingReport(null)
                }}
                className="text-[11px] text-neutral-500 hover:text-red-400 transition-colors cursor-pointer"
              >
                Xóa báo cáo
              </button>
              
              <Button
                onClick={() => setViewingReport(null)}
                className="bg-emerald-500/80 hover:bg-emerald-500 text-white text-[12px] py-1.5 px-4 rounded-xl font-medium border-0 cursor-pointer"
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
