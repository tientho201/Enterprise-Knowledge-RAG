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
  Check,
  Search,
  X,
} from "lucide-react"
import { useApp } from "@/lib/context"
import { graphAPI, ApiError, type GraphOverview } from "@/lib/api"
import type { FGNode, FGLink } from "@/components/ForceGraphView"

// Suy id đầu mút của link (react-force-graph thay string bằng object node sau mô phỏng).
function linkEndId(end: string | FGNode): string {
  return typeof end === "object" ? end.id : end
}

interface ExpandInfo {
  truncated: boolean
  total: number
  returned: number
}
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
  // pickedConvId = lựa chọn tường minh của user ở dropdown; convId = giá trị hiệu lực
  // (derived, không dùng effect để tránh cascading render) — mặc định về hội thoại đang
  // mở, rồi tới hội thoại đã lưu đầu tiên.
  const [pickedConvId, setPickedConvId] = useState<string | null>(null)
  const convId = useMemo(() => {
    if (pickedConvId && savedSessions.some((s) => s.id === pickedConvId)) return pickedConvId
    return savedSessions.find((s) => s.id === activeSessionId)?.id || savedSessions[0]?.id || ""
  }, [pickedConvId, savedSessions, activeSessionId])

  // ── State đồ thị (cấu trúc — nạp 1 lần / mỗi lần đổi hội thoại) ────────────
  const [graph, setGraph] = useState<GraphData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedNode, setSelectedNode] = useState<FGNode | null>(null)
  const [showDetail, setShowDetail] = useState(true)
  // Tài liệu đang bung → thông tin cắt (nếu có). expandingId: đang gọi expand.
  const [expandedDocs, setExpandedDocs] = useState<Map<string, ExpandInfo>>(new Map())
  const [expandingId, setExpandingId] = useState<string | null>(null)
  // Tài liệu bị ẩn khỏi đồ thị (client-side, KHÔNG refetch) — checkbox chọn nội dung.
  const [hiddenDocIds, setHiddenDocIds] = useState<Set<string>>(new Set())
  // Highlight theo truy vấn (Endpoint B) — null = không có, Set = id node trúng.
  const [queryText, setQueryText] = useState("")
  const [highlightedIds, setHighlightedIds] = useState<Set<string> | null>(null)
  const [highlighting, setHighlighting] = useState(false)

  const canUse = !!user?.canUseAdvancedSearch

  const loadOverview = useCallback(async (conversationId: string) => {
    setLoading(true)
    setError(null)
    setSelectedNode(null)
    setExpandedDocs(new Map())
    setHiddenDocIds(new Set())
    setQueryText("")
    setHighlightedIds(null)
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
    // Fetch-on-dependency-change hợp lệ: nạp lại đồ thị mỗi khi đổi hội thoại. loadOverview
    // set loading=true đồng bộ (spinner) — chấp nhận 1 lần render thừa, đúng pattern data-fetch
    // effect của repo (xem context.tsx). Quy tắc set-state-in-effect quá gắt cho case này.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (canUse && convId) loadOverview(convId)
  }, [canUse, convId, loadOverview])

  // ── Bung / thu 1 tài liệu (lazy, thêm/bớt vài chục node — không nạp lại graph) ──
  const toggleExpand = useCallback(
    async (docId: string) => {
      if (expandedDocs.has(docId)) {
        // Thu: bỏ chunk node của tài liệu này + link liên quan.
        setGraph((prev) => {
          if (!prev) return prev
          const nodes = prev.nodes.filter((n) => !(n.type === "chunk" && n.group === docId))
          const kept = new Set(nodes.map((n) => n.id))
          const links = prev.links.filter(
            (l) => kept.has(linkEndId(l.source)) && kept.has(linkEndId(l.target))
          )
          return { nodes, links }
        })
        setExpandedDocs((prev) => {
          const next = new Map(prev)
          next.delete(docId)
          return next
        })
        return
      }

      if (!convId) return
      setExpandingId(docId)
      try {
        const data = await graphAPI.expand(docId, convId)
        setGraph((prev) => {
          const base = prev ?? { nodes: [], links: [] }
          const existing = new Set(base.nodes.map((n) => n.id))
          const newNodes = data.nodes.filter((n) => !existing.has(n.id)).map((n) => ({ ...n }))
          // Cạnh chứa (tài liệu → chunk) dựng ở client để chunk bám vào node tài liệu.
          const containment: FGLink[] = data.nodes.map((n) => ({
            source: docId,
            target: n.id,
            rel: "CONTAINS",
          }))
          const intra: FGLink[] = data.edges.map((e) => ({
            source: e.source,
            target: e.target,
            rel: e.rel,
          }))
          return {
            nodes: [...base.nodes, ...newNodes],
            links: [...base.links, ...containment, ...intra],
          }
        })
        setExpandedDocs((prev) =>
          new Map(prev).set(docId, {
            truncated: data.truncated,
            total: data.total,
            returned: data.returned,
          })
        )
      } catch (err) {
        setError(err instanceof ApiError ? err.detail : "Không bung được tài liệu.")
      } finally {
        setExpandingId(null)
      }
    },
    [convId, expandedDocs]
  )

  const handleNodeClick = useCallback(
    (node: FGNode) => {
      setSelectedNode(node)
      setShowDetail(true)
      if (node.type === "document") toggleExpand(node.id)
    },
    [toggleExpand]
  )

  const expandedIds = useMemo(() => new Set(expandedDocs.keys()), [expandedDocs])
  const truncatedDocs = useMemo(
    () => Array.from(expandedDocs.values()).filter((i) => i.truncated),
    [expandedDocs]
  )

  // Danh sách tài liệu (node document) để hiện checkbox chọn nội dung.
  const docChecklist = useMemo(
    () => (graph ? graph.nodes.filter((n) => n.type === "document") : []),
    [graph]
  )

  // Đồ thị hiển thị = ẩn tài liệu bị bỏ chọn + chunk của chúng + link liên quan. CHỈ
  // lọc ở client (không gọi lại API) — bật/tắt tức thì, giữ nguyên state đã nạp.
  const visibleGraph = useMemo<GraphData>(() => {
    if (!graph) return { nodes: [], links: [] }
    if (hiddenDocIds.size === 0) return graph
    const nodes = graph.nodes.filter((n) => !hiddenDocIds.has(n.group))
    const kept = new Set(nodes.map((n) => n.id))
    const links = graph.links.filter(
      (l) => kept.has(linkEndId(l.source)) && kept.has(linkEndId(l.target))
    )
    return { nodes, links }
  }, [graph, hiddenDocIds])

  const toggleDocVisible = useCallback((docId: string) => {
    setHiddenDocIds((prev) => {
      const next = new Set(prev)
      if (next.has(docId)) next.delete(docId)
      else next.add(docId)
      return next
    })
  }, [])

  const setAllDocsVisible = useCallback(
    (visible: boolean) => {
      setHiddenDocIds(visible ? new Set() : new Set(docChecklist.map((d) => d.id)))
    },
    [docChecklist]
  )

  // ── Truy vấn → highlight (Endpoint B) — chỉ đổi trạng thái visual graph có sẵn ──
  const runHighlight = useCallback(async () => {
    const q = queryText.trim()
    if (!q) {
      setHighlightedIds(null)
      return
    }
    if (!convId) return
    setHighlighting(true)
    try {
      const { nodeIds } = await graphAPI.highlight(convId, q)
      setHighlightedIds(new Set(nodeIds))
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Không chạy được truy vấn.")
    } finally {
      setHighlighting(false)
    }
  }, [queryText, convId])

  const clearHighlight = useCallback(() => {
    setQueryText("")
    setHighlightedIds(null)
  }, [])

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
            onChange={(e) => setPickedConvId(e.target.value)}
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

      {/* Thanh truy vấn — làm nổi bật nội dung liên quan (Endpoint B) */}
      <div className="px-4 py-2 border-b border-white/[0.04] bg-[#0a0a0a]/40 flex items-center gap-2 shrink-0">
        <div className="relative flex-1 max-w-md">
          <Search className="w-3.5 h-3.5 text-neutral-500 absolute left-2.5 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={queryText}
            onChange={(e) => setQueryText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && runHighlight()}
            placeholder="Làm nổi bật nội dung liên quan tới truy vấn..."
            disabled={!convId}
            className="w-full bg-[#0f0f0f]/70 border border-white/[0.06] rounded-lg pl-8 pr-8 py-1.5 text-[12px] text-neutral-200 focus:outline-none focus:border-emerald-500/25 placeholder:text-neutral-600 disabled:opacity-40"
          />
          {(queryText || highlightedIds) && (
            <button
              onClick={clearHighlight}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 rounded text-neutral-500 hover:text-neutral-300"
              title="Xóa highlight"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
        <button
          onClick={runHighlight}
          disabled={!convId || highlighting || !queryText.trim()}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-500/80 hover:bg-emerald-500 text-white text-[12px] font-medium transition-all active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {highlighting ? (
            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <Search className="w-3.5 h-3.5" />
          )}
          Làm nổi bật
        </button>
        {highlightedIds && (
          <span className="text-[11px] text-neutral-500 hidden sm:block">
            {highlightedIds.size} node trúng
          </span>
        )}
      </div>

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
              nodes={visibleGraph.nodes}
              links={visibleGraph.links}
              expandedIds={expandedIds}
              highlightedIds={highlightedIds}
              selectedId={selectedNode?.id ?? null}
              onNodeClick={handleNodeClick}
            />
          ) : (
            <EmptyState
              icon={<Network className="w-6 h-6 opacity-30 text-emerald-400" />}
              text="Hội thoại này chưa có tài liệu nào được lập chỉ mục vào đồ thị."
            />
          )}

          {/* Chú thích: giai đoạn Chunk không có cạnh giữa các tài liệu */}
          {graph && graph.nodes.length > 0 && expandedDocs.size === 0 && (
            <div className="absolute bottom-3 left-3 max-w-[320px] text-[10px] text-neutral-500 bg-[#0f0f0f]/80 border border-white/[0.06] rounded-lg px-2.5 py-1.5 leading-relaxed">
              Mỗi node là một tài liệu. Bấm vào một tài liệu để bung các đoạn nội dung bên
              trong; bấm lại để thu gọn.
            </div>
          )}

          {/* Đang bung 1 tài liệu */}
          {expandingId && (
            <div className="absolute bottom-3 left-3 flex items-center gap-2 text-[10px] text-neutral-400 bg-[#0f0f0f]/80 border border-white/[0.06] rounded-lg px-2.5 py-1.5">
              <RefreshCw className="w-3 h-3 animate-spin text-emerald-400/60" />
              Đang bung tài liệu...
            </div>
          )}

          {/* Cảnh báo bị cắt do trần cứng backend */}
          {truncatedDocs.length > 0 && (
            <div className="absolute top-3 left-3 max-w-[340px] flex items-start gap-2 text-[10px] text-amber-300/90 bg-amber-500/[0.06] border border-amber-500/20 rounded-lg px-2.5 py-1.5 leading-relaxed">
              <Info className="w-3.5 h-3.5 shrink-0 mt-0.5 text-amber-400/80" />
              <span>
                Một số tài liệu quá lớn nên chỉ hiển thị{" "}
                {truncatedDocs.map((d) => `${d.returned}/${d.total}`).join(", ")} đoạn. Bỏ bớt
                tài liệu hoặc thu gọn để đồ thị nhẹ hơn.
              </span>
            </div>
          )}

          {/* Tất cả tài liệu đang bị ẩn */}
          {graph && graph.nodes.length > 0 && visibleGraph.nodes.length === 0 && (
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
              <p className="text-[12px] text-neutral-500 bg-[#0f0f0f]/80 border border-white/[0.06] rounded-lg px-3 py-2">
                Tất cả tài liệu đang bị ẩn — tick lại ở bảng điều khiển để hiển thị.
              </p>
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

        {/* ── Panel phải (thu/mở được): bộ lọc tài liệu + chi tiết ──────── */}
        {showDetail && (
          <aside className="w-[300px] border-l border-white/[0.04] bg-[#0a0a0a]/50 flex flex-col shrink-0">
            <div className="p-3 border-b border-white/[0.04] flex items-center justify-between">
              <h3 className="text-[11px] font-bold text-neutral-400 uppercase tracking-wider">
                Bảng điều khiển
              </h3>
              <button
                onClick={() => setShowDetail(false)}
                className="p-1 rounded-md hover:bg-white/[0.05] text-neutral-500 hover:text-neutral-300 transition-colors"
                title="Thu gọn panel"
              >
                <PanelRightClose className="w-4 h-4" />
              </button>
            </div>

            {/* Bộ chọn tài liệu hiển thị (checkbox) */}
            {docChecklist.length > 0 && (
              <DocFilter
                docs={docChecklist}
                hiddenDocIds={hiddenDocIds}
                onToggle={toggleDocVisible}
                onSetAll={setAllDocsVisible}
              />
            )}

            {/* Chi tiết node */}
            <div className="flex-1 overflow-y-auto p-3 scrollbar-thin border-t border-white/[0.04]">
              <div className="text-[10px] font-bold text-neutral-500 uppercase tracking-wider mb-2">
                Chi tiết
              </div>
              {selectedNode ? (
                <NodeDetail node={selectedNode} />
              ) : (
                <p className="text-[12px] text-neutral-600 leading-relaxed">
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

function DocFilter({
  docs,
  hiddenDocIds,
  onToggle,
  onSetAll,
}: {
  docs: FGNode[]
  hiddenDocIds: Set<string>
  onToggle: (id: string) => void
  onSetAll: (visible: boolean) => void
}) {
  const allVisible = hiddenDocIds.size === 0
  return (
    <div className="p-3 space-y-2">
      <div className="flex items-center justify-between">
        <div className="text-[10px] font-bold text-neutral-500 uppercase tracking-wider">
          Tài liệu ({docs.length})
        </div>
        <button
          onClick={() => onSetAll(!allVisible)}
          className="text-[10px] text-emerald-400/70 hover:text-emerald-400 transition-colors"
        >
          {allVisible ? "Bỏ chọn tất cả" : "Chọn tất cả"}
        </button>
      </div>
      <div className="space-y-1 max-h-[180px] overflow-y-auto scrollbar-thin pr-1">
        {docs.map((doc) => {
          const visible = !hiddenDocIds.has(doc.id)
          const count =
            typeof doc.meta?.chunk_count === "number" ? doc.meta.chunk_count : null
          return (
            <button
              key={doc.id}
              onClick={() => onToggle(doc.id)}
              className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-white/[0.03] transition-colors text-left group"
            >
              <span
                className={`w-3.5 h-3.5 rounded border flex items-center justify-center shrink-0 transition-colors ${
                  visible
                    ? "bg-emerald-500/80 border-emerald-500/80"
                    : "border-white/[0.15] bg-transparent"
                }`}
              >
                {visible && <Check className="w-2.5 h-2.5 text-white" strokeWidth={3} />}
              </span>
              <span
                className={`text-[12px] truncate flex-1 ${
                  visible ? "text-neutral-300" : "text-neutral-600"
                }`}
              >
                {doc.label}
              </span>
              {count !== null && (
                <span className="text-[9px] text-neutral-600 shrink-0">{count}</span>
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}

function NodeDetail({ node }: { node: FGNode }) {
  const isDoc = node.type === "document"
  const chunkCount = typeof node.meta?.chunk_count === "number" ? node.meta.chunk_count : null
  const content = typeof node.meta?.content === "string" ? node.meta.content : null
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
      {isDoc && chunkCount !== null && (
        <div className="text-[11px] text-neutral-500">
          {chunkCount} đoạn nội dung được lập chỉ mục. Bấm node để bung/thu.
        </div>
      )}
      {content && (
        <div className="pt-2 border-t border-white/[0.05]">
          <div className="text-[10px] uppercase tracking-wider text-neutral-600 font-semibold mb-1.5">
            Nguyên văn
          </div>
          <p className="text-[12px] text-neutral-300 leading-relaxed whitespace-pre-wrap select-text">
            {content}
          </p>
        </div>
      )}
    </div>
  )
}
