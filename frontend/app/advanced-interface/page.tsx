"use client"

import React, { useCallback, useEffect, useMemo, useState } from "react"
import dynamic from "next/dynamic"
import {
  Network,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  RefreshCw,
  Lock,
  Sparkles,
  FileText,
  Boxes,
  Info,
} from "lucide-react"
import { useApp } from "@/lib/context"
import { graphAPI, ApiError, type GraphOverview } from "@/lib/api"
import type { FGNode, FGLink } from "@/components/ForceGraphView"
import UpgradeModal from "@/components/UpgradeModal"

// react-force-graph dùng canvas/window → phải tắt SSR.
const ForceGraphView = dynamic(() => import("@/components/ForceGraphView"), {
  ssr: false,
  loading: () => (
    <div className="w-full h-full flex items-center justify-center text-neutral-600 text-xs">
      <RefreshCw className="w-4 h-4 animate-spin mr-2" /> Đang tải trình vẽ đồ thị...
    </div>
  ),
})

interface GraphData {
  nodes: FGNode[]
  links: FGLink[]
}

export default function AdvancedInterface() {
  const {
    user,
    chatSessions,
    activeSessionId,
    showLeftSidebar,
    setShowLeftSidebar,
  } = useApp()

  const [showUpgrade, setShowUpgrade] = useState(false)

  // ── Bộ chọn hội thoại (nguồn phạm vi Endpoint A) ──────────────────────────
  // Chỉ hội thoại đã lưu (id không bắt đầu "new-") mới có tài liệu ở backend.
  const savedSessions = useMemo(
    () => chatSessions.filter((s) => !s.id.startsWith("new-")),
    [chatSessions]
  )
  const [convId, setConvId] = useState<string>("")

  useEffect(() => {
    if (convId && savedSessions.some((s) => s.id === convId)) return
    const preferred =
      savedSessions.find((s) => s.id === activeSessionId)?.id || savedSessions[0]?.id || ""
    setConvId(preferred)
  }, [savedSessions, activeSessionId, convId])

  // ── State đồ thị (cấu trúc — nạp 1 lần / mỗi lần đổi hội thoại) ────────────
  const [graph, setGraph] = useState<GraphData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedNode, setSelectedNode] = useState<FGNode | null>(null)
  const [showDetail, setShowDetail] = useState(true)

  const canUse = !!user?.canUseAdvancedSearch

  const loadOverview = useCallback(async (conversationId: string) => {
    setLoading(true)
    setError(null)
    setSelectedNode(null)
    try {
      const data: GraphOverview = await graphAPI.overview(conversationId)
      setGraph({
        nodes: data.nodes.map((n) => ({ ...n })),
        links: data.edges.map((e) => ({ source: e.source, target: e.target, rel: e.rel })),
      })
    } catch (err) {
      const msg = err instanceof ApiError ? err.detail : "Không tải được đồ thị."
      setError(msg)
      setGraph(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!canUse || !convId) {
      setGraph(null)
      return
    }
    loadOverview(convId)
  }, [canUse, convId, loadOverview])

  // ── Gate UI ───────────────────────────────────────────────────────────────
  if (!canUse) {
    return (
      <div className="flex-1 flex flex-col h-full overflow-hidden">
        <PageHeader showLeftSidebar={showLeftSidebar} setShowLeftSidebar={setShowLeftSidebar} />
        <div className="flex-1 flex flex-col items-center justify-center text-center px-6 gap-4">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-emerald-500/20 to-teal-600/20 border border-emerald-500/20 flex items-center justify-center">
            <Lock className="w-6 h-6 text-emerald-400/80" />
          </div>
          <div className="space-y-1.5 max-w-md">
            <h3 className="text-base font-semibold text-neutral-200">
              Giao diện nâng cao chỉ dành cho gói Pro
            </h3>
            <p className="text-[13px] text-neutral-500 leading-relaxed">
              Trực quan hóa đồ thị tri thức của tài liệu — xem cấu trúc, bung từng nhánh và
              làm nổi bật nội dung liên quan tới truy vấn. Nâng cấp để mở khóa.
            </p>
          </div>
          <button
            onClick={() => setShowUpgrade(true)}
            className="flex items-center gap-2 px-4 py-2 rounded-xl bg-emerald-500/80 hover:bg-emerald-500 text-white text-[13px] font-medium transition-all active:scale-95"
          >
            <Sparkles className="w-4 h-4" />
            Nâng cấp lên Pro
          </button>
        </div>
        <UpgradeModal open={showUpgrade} onOpenChange={setShowUpgrade} />
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden">
      <PageHeader showLeftSidebar={showLeftSidebar} setShowLeftSidebar={setShowLeftSidebar}>
        {/* Bộ chọn hội thoại */}
        <div className="flex items-center gap-2">
          <label className="text-[11px] text-neutral-500 hidden sm:block">Hội thoại:</label>
          <select
            value={convId}
            onChange={(e) => setConvId(e.target.value)}
            className="bg-[#0f0f0f]/70 border border-white/[0.06] rounded-lg px-2.5 py-1.5 text-[12px] text-neutral-200 focus:outline-none focus:border-emerald-500/25 max-w-[240px]"
          >
            {savedSessions.length === 0 && <option value="">— Chưa có hội thoại đã lưu —</option>}
            {savedSessions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.title}
              </option>
            ))}
          </select>
          <button
            onClick={() => convId && loadOverview(convId)}
            disabled={!convId || loading}
            className="p-1.5 rounded-lg hover:bg-white/[0.05] text-neutral-500 hover:text-neutral-300 transition-colors disabled:opacity-40"
            title="Tải lại đồ thị"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </PageHeader>

      <div className="flex-1 flex overflow-hidden relative">
        {/* ── Canvas đồ thị ─────────────────────────────────────────────── */}
        <div className="flex-1 relative min-w-0">
          {!convId ? (
            <EmptyState
              icon={<Network className="w-6 h-6 opacity-30 text-emerald-400" />}
              text="Chọn một hội thoại đã lưu để xem đồ thị tài liệu của nó."
            />
          ) : loading ? (
            <EmptyState
              icon={<RefreshCw className="w-6 h-6 animate-spin text-emerald-400/60" />}
              text="Đang dựng đồ thị..."
            />
          ) : error ? (
            <EmptyState
              icon={<Info className="w-6 h-6 opacity-40 text-red-400" />}
              text={error}
            />
          ) : graph && graph.nodes.length > 0 ? (
            <ForceGraphView
              nodes={graph.nodes}
              links={graph.links}
              selectedId={selectedNode?.id ?? null}
              onNodeClick={(n) => {
                setSelectedNode(n)
                setShowDetail(true)
              }}
            />
          ) : (
            <EmptyState
              icon={<Network className="w-6 h-6 opacity-30 text-emerald-400" />}
              text="Hội thoại này chưa có tài liệu nào được lập chỉ mục vào đồ thị."
            />
          )}

          {/* Chú thích: giai đoạn Chunk không có cạnh giữa các tài liệu */}
          {graph && graph.nodes.length > 0 && graph.links.length === 0 && (
            <div className="absolute bottom-3 left-3 max-w-[320px] text-[10px] text-neutral-500 bg-[#0f0f0f]/80 border border-white/[0.06] rounded-lg px-2.5 py-1.5 leading-relaxed">
              Mỗi node là một tài liệu. Chưa hiển thị cạnh viện dẫn giữa các tài liệu ở giai
              đoạn này — bấm vào một tài liệu để xem chi tiết.
            </div>
          )}

          {/* Nút mở panel chi tiết khi đang thu */}
          {!showDetail && (
            <button
              onClick={() => setShowDetail(true)}
              className="absolute top-3 right-3 p-1.5 rounded-lg bg-[#0f0f0f]/80 border border-white/[0.06] hover:bg-white/[0.05] text-neutral-400 transition-colors"
              title="Mở panel chi tiết"
            >
              <PanelRightOpen className="w-4 h-4" />
            </button>
          )}
        </div>

        {/* ── Panel chi tiết (thu/mở được) ──────────────────────────────── */}
        {showDetail && (
          <aside className="w-[300px] border-l border-white/[0.04] bg-[#0a0a0a]/50 flex flex-col shrink-0">
            <div className="p-3 border-b border-white/[0.04] flex items-center justify-between">
              <h3 className="text-[11px] font-bold text-neutral-400 uppercase tracking-wider">
                Chi tiết
              </h3>
              <button
                onClick={() => setShowDetail(false)}
                className="p-1 rounded-md hover:bg-white/[0.05] text-neutral-500 hover:text-neutral-300 transition-colors"
                title="Thu gọn panel"
              >
                <PanelRightClose className="w-4 h-4" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-3 scrollbar-thin">
              {selectedNode ? (
                <NodeDetail node={selectedNode} />
              ) : (
                <p className="text-[12px] text-neutral-600 leading-relaxed pt-2">
                  Bấm vào một node trên đồ thị để xem thông tin của nó tại đây.
                </p>
              )}
            </div>
          </aside>
        )}
      </div>

      <UpgradeModal open={showUpgrade} onOpenChange={setShowUpgrade} />
    </div>
  )
}

// ── Header dùng chung ───────────────────────────────────────────────────────
function PageHeader({
  showLeftSidebar,
  setShowLeftSidebar,
  children,
}: {
  showLeftSidebar: boolean
  setShowLeftSidebar: (v: boolean) => void
  children?: React.ReactNode
}) {
  return (
    <header className="h-12 border-b border-white/[0.04] bg-[#0a0a0a]/60 backdrop-blur-md px-4 flex items-center justify-between gap-4 shrink-0">
      <div className="flex items-center gap-2">
        {!showLeftSidebar && (
          <button
            onClick={() => setShowLeftSidebar(true)}
            className="p-1.5 rounded-lg hover:bg-white/[0.04] text-neutral-500 hover:text-neutral-300 transition-colors"
            title="Mở Sidebar"
          >
            <PanelLeftOpen className="w-4 h-4" />
          </button>
        )}
        <Network className="w-4 h-4 text-emerald-400/70" />
        <h2 className="text-sm font-semibold text-neutral-200">Giao diện nâng cao</h2>
      </div>
      {children}
    </header>
  )
}

function EmptyState({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <div className="w-full h-full flex flex-col items-center justify-center gap-3 text-center px-6">
      {icon}
      <p className="text-[12px] text-neutral-500 max-w-xs leading-relaxed">{text}</p>
    </div>
  )
}

function NodeDetail({ node }: { node: FGNode }) {
  const isDoc = node.type === "document"
  const chunkCount = typeof node.meta?.chunk_count === "number" ? node.meta.chunk_count : null
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        {isDoc ? (
          <FileText className="w-4 h-4 text-emerald-400/80 shrink-0" />
        ) : (
          <Boxes className="w-4 h-4 text-sky-400/80 shrink-0" />
        )}
        <span className="text-[10px] uppercase tracking-wider text-neutral-500 font-semibold">
          {isDoc ? "Tài liệu" : "Đoạn nội dung"}
        </span>
      </div>
      <div className="text-[13px] font-semibold text-neutral-200 leading-snug break-words">
        {node.label}
      </div>
      {chunkCount !== null && (
        <div className="text-[11px] text-neutral-500">
          {chunkCount} đoạn nội dung được lập chỉ mục.
        </div>
      )}
    </div>
  )
}
