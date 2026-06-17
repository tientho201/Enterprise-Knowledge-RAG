"use client"

import React, { useState } from "react"
import { 
  History, 
  Search, 
  Activity, 
  Cpu, 
  Layers, 
  Timer, 
  Trash2, 
  Upload, 
  Sliders, 
  Sparkles, 
  BookOpen, 
  Database,
  PanelLeftOpen
} from "lucide-react"
import { useApp } from "@/lib/context"
import { Button } from "@/components/ui/button"

export default function WorkHistory() {
  const { 
    auditLogs, 
    chatSessions, 
    documents,
    showLeftSidebar,
    setShowLeftSidebar,
    addAuditLog 
  } = useApp()

  const [searchQuery, setSearchQuery] = useState("")
  const [filterType, setFilterType] = useState<"all" | "upload" | "query" | "research" | "config">("all")

  // Deriving metrics
  const totalQueries = auditLogs.filter(l => l.type === "query").length
  const totalUploads = documents.length
  const avgLatency = "620 ms"
  
  // Calculate mock tokens
  const totalTokens = chatSessions.reduce((acc, sess) => {
    return acc + sess.messages.reduce((mAcc, msg) => {
      if (msg.ragResponse?.tokensCount) {
        return mAcc + msg.ragResponse.tokensCount.prompt + msg.ragResponse.tokensCount.completion
      }
      return mAcc
    }, 0)
  }, 1480) // 1480 is base historical tokens

  // Filter logs
  const filteredLogs = auditLogs.filter(log => {
    const matchesSearch = log.action.toLowerCase().includes(searchQuery.toLowerCase()) || 
                          (log.details && log.details.toLowerCase().includes(searchQuery.toLowerCase()))
    const matchesType = filterType === "all" || log.type === filterType
    return matchesSearch && matchesType
  })

  // Types helper
  const logTypesMeta: Record<string, { label: string, color: string, icon: any }> = {
    upload: { label: "Tài liệu", color: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20", icon: Upload },
    query: { label: "Tra cứu AI", color: "text-violet-400 bg-violet-500/10 border-violet-500/20", icon: Sparkles },
    research: { label: "Nghiên cứu", color: "text-amber-400 bg-amber-500/10 border-amber-500/20", icon: BookOpen },
    config: { label: "Cấu hình", color: "text-sky-400 bg-sky-500/10 border-sky-500/20", icon: Sliders }
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
            Lịch sử làm việc
          </h2>
        </div>
        <div className="text-[11px] text-neutral-500 hidden sm:block">
          Nhật ký hoạt động và giám sát tài nguyên RAG
        </div>
      </header>

      {/* Main Workspace */}
      <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-6 scrollbar-thin">
        
        {/* ===== METRICS METADATA ===== */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <div className="glass-card p-4 rounded-xl flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-violet-500/10 border border-violet-500/15 flex items-center justify-center shrink-0">
              <Activity className="w-5 h-5 text-violet-400/80" />
            </div>
            <div>
              <div className="text-[10px] text-neutral-500 font-semibold uppercase tracking-wider">Số lượt tra cứu</div>
              <div className="text-xl font-bold text-neutral-100 font-mono mt-0.5">{totalQueries}</div>
            </div>
          </div>

          <div className="glass-card p-4 rounded-xl flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-emerald-500/10 border border-emerald-500/15 flex items-center justify-center shrink-0">
              <Upload className="w-5 h-5 text-emerald-400/80" />
            </div>
            <div>
              <div className="text-[10px] text-neutral-500 font-semibold uppercase tracking-wider">Tài liệu đã nạp</div>
              <div className="text-xl font-bold text-neutral-100 font-mono mt-0.5">{totalUploads}</div>
            </div>
          </div>

          <div className="glass-card p-4 rounded-xl flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-sky-500/10 border border-sky-500/15 flex items-center justify-center shrink-0">
              <Timer className="w-5 h-5 text-sky-400/80" />
            </div>
            <div>
              <div className="text-[10px] text-neutral-500 font-semibold uppercase tracking-wider font-sans">Thời gian xử lý avg</div>
              <div className="text-xl font-bold text-neutral-100 font-mono mt-0.5">{avgLatency}</div>
            </div>
          </div>

          <div className="glass-card p-4 rounded-xl flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-amber-500/10 border border-amber-500/15 flex items-center justify-center shrink-0">
              <Cpu className="w-5 h-5 text-amber-400/80" />
            </div>
            <div>
              <div className="text-[10px] text-neutral-500 font-semibold uppercase tracking-wider">Lượng tokens dùng</div>
              <div className="text-xl font-bold text-neutral-100 font-mono mt-0.5">{totalTokens}</div>
            </div>
          </div>
        </div>

        {/* ===== SEARCH & FILTER WORK History ===== */}
        <div className="flex flex-col md:flex-row gap-3">
          {/* Search Logs */}
          <div className="flex-1 relative">
            <Search className="w-4 h-4 text-neutral-500 absolute left-3.5 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Tìm kiếm hành động, kết quả trong log..."
              className="w-full bg-[#0f0f0f]/60 border border-white/[0.06] rounded-xl pl-10 pr-4 py-2.5 text-[13px] text-neutral-200 focus:outline-none focus:border-emerald-500/20 placeholder:text-neutral-600 transition-colors"
            />
          </div>

          {/* Filter Pills */}
          <div className="flex bg-[#0f0f0f]/60 border border-white/[0.06] rounded-xl p-1 gap-1 shrink-0 overflow-x-auto max-w-full scrollbar-none self-start">
            {[
              { label: "Tất cả", value: "all" },
              { label: "Tài liệu", value: "upload" },
              { label: "AI Search", value: "query" },
              { label: "Nghiên cứu", value: "research" },
              { label: "Cấu hình", value: "config" }
            ].map((pill) => {
              const isSel = filterType === pill.value;
              return (
                <button
                  key={pill.value}
                  onClick={() => setFilterType(pill.value as any)}
                  className={`px-3 py-1.5 rounded-lg text-[12px] font-medium transition-all whitespace-nowrap cursor-pointer ${
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

        {/* ===== TIMELINE AUDIT LOG LIST ===== */}
        <div className="glass-card border border-white/[0.04] rounded-xl overflow-hidden p-5">
          <div className="flex justify-between items-center mb-6">
            <h3 className="text-[11px] font-semibold text-neutral-500 uppercase tracking-wider flex items-center gap-1.5">
              <History className="w-4 h-4 text-neutral-600" />
              <span>Nhật ký kiểm toán ({filteredLogs.length})</span>
            </h3>
          </div>

          {filteredLogs.length === 0 ? (
            <div className="text-center py-16 text-neutral-600 text-[13px]">
              Không có nhật ký hoạt động nào phù hợp.
            </div>
          ) : (
            <div className="relative pl-6 border-l border-white/[0.04] space-y-6">
              
              {filteredDocsTimeline(filteredLogs, logTypesMeta)}
              
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function filteredDocsTimeline(logs: any[], meta: Record<string, { label: string, color: string, icon: any }>) {
  return logs.map((log) => {
    const typeMeta = meta[log.type] || { label: "Khác", color: "text-neutral-400 bg-neutral-500/10 border-neutral-500/20", icon: Activity }
    const Icon = typeMeta.icon
    
    return (
      <div key={log.id} className="relative animate-msg-in">
        
        {/* Timeline bullet dot with icon */}
        <div className={`absolute -left-[38px] top-0 w-6 h-6 rounded-full border flex items-center justify-center shrink-0 ${typeMeta.color} bg-[#0a0a0a]`}>
          <Icon className="w-3 h-3" />
        </div>

        {/* Log content */}
        <div className="bg-white/[0.01] border border-white/[0.04] rounded-xl p-3.5 hover:border-white/[0.08] transition-all space-y-1.5">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-1.5">
            
            {/* Title / Action */}
            <div className="font-bold text-[13px] text-neutral-200 leading-normal">
              {log.action}
            </div>

            {/* Time and Badge */}
            <div className="flex items-center gap-2 shrink-0">
              <span className="text-[9px] font-mono text-neutral-600 font-semibold">{log.timestamp}</span>
              <span className={`px-2 py-0.5 rounded text-[8px] font-bold uppercase tracking-wider border shrink-0 ${typeMeta.color}`}>
                {typeMeta.label}
              </span>
            </div>
          </div>

          {/* Detailed description */}
          {log.details && (
            <p className="text-[11px] text-neutral-500 leading-relaxed font-sans">
              {log.details}
            </p>
          )}
        </div>
      </div>
    )
  })
}
