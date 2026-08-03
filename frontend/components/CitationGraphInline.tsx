"use client"

// Đồ thị dẫn chiếu — hiện NGAY DƯỚI câu trả lời trong bong bóng chat khi search_mode
// "Nâng cao" (search_mode="advanced") trả về citation_graph_path/nodes. Đây là đồ thị
// của MỘT câu trả lời (đường traverse cụ thể, thường 3-15 node) — KHÔNG phải trang
// khám phá toàn graph (đó là app/advanced-interface + components/ForceGraphView dùng
// riêng, component này chỉ TÁI DÙNG phần render lực của ForceGraphView).

import { useMemo, useState } from "react"
import dynamic from "next/dynamic"
import { Waypoints, ChevronDown, ChevronRight, X, Plus, Loader2, FileWarning } from "lucide-react"
import type { FGNode, FGLink } from "./ForceGraphView"
import type { CitationGraphStep, CitationGraphNode, SuggestedDocument } from "@/lib/api"

// react-force-graph dùng canvas + đọc window — phải load client-only (mirror
// app/advanced-interface/page.tsx).
const ForceGraphView = dynamic(() => import("./ForceGraphView"), { ssr: false })

const NODE_TYPE_COLOR: Record<CitationGraphNode["node_type"], string> = {
  anchor: "#34d399", // emerald-400 — điểm neo (khớp dense search trực tiếp)
  in_context: "#38bdf8", // sky-400 — lấy qua viện dẫn, đã góp nội dung vào câu trả lời
  out_of_scope: "#71717a", // zinc-500 — chưa góp nội dung (placeholder hoặc chưa gắn hội thoại)
}

const NODE_TYPE_LEGEND: { type: CitationGraphNode["node_type"]; label: string }[] = [
  { type: "anchor", label: "Điểm neo" },
  { type: "in_context", label: "Qua viện dẫn" },
  { type: "out_of_scope", label: "Chưa gắn · chưa có" },
]

interface Props {
  path: CitationGraphStep[]
  nodes: CitationGraphNode[]
  suggestedDocuments: SuggestedDocument[]
  // document_id của các tài liệu ĐÃ gắn vào hội thoại hiện tại — ẩn nút "Thêm vào hội
  // thoại" cho suggestion nào đã gắn rồi (vd LegalDocument đã in-scope qua Provision khác).
  attachedDocumentIds: Set<string>
  onAttachDocument: (documentId: string) => Promise<void>
}

export default function CitationGraphInline({
  path,
  nodes,
  suggestedDocuments,
  attachedDocumentIds,
  onAttachDocument,
}: Props) {
  const [expanded, setExpanded] = useState(false)
  const [selectedAddr, setSelectedAddr] = useState<string | null>(null)
  const [attachingId, setAttachingId] = useState<string | null>(null)

  // Chỉ vẽ node THỰC SỰ tham gia ít nhất 1 cạnh của đường traverse này — loại anchor
  // lạc (dense search trúng nhưng không viện dẫn/được viện dẫn gì) khỏi canvas, tránh
  // đồ thị rỗng gây hiểu lầm "không có gì" khi thực ra chỉ 1 node cô lập.
  const { visibleNodes, fgNodes, fgLinks } = useMemo(() => {
    const inEdge = new Set(path.flatMap((s) => [s.from_address, s.to_address]))
    const visible = nodes.filter((n) => inEdge.has(n.address))
    const byAddr = new Map(visible.map((n) => [n.address, n]))
    const fn: FGNode[] = visible.map((n) => ({
      id: n.address,
      label: n.label,
      type: n.node_type === "anchor" ? "document" : "provision",
      group: n.node_type,
      color: NODE_TYPE_COLOR[n.node_type],
      dashed: n.node_type === "out_of_scope",
      radius: n.node_type === "anchor" ? 7 : 4.5,
    }))
    const fl: FGLink[] = path
      .filter((s) => byAddr.has(s.from_address) && byAddr.has(s.to_address))
      .map((s) => ({ source: s.from_address, target: s.to_address, rel: s.relation }))
    return { visibleNodes: visible, fgNodes: fn, fgLinks: fl }
  }, [path, nodes])

  if (visibleNodes.length === 0) return null

  const selectedNode = selectedAddr ? nodes.find((n) => n.address === selectedAddr) : null

  const handleAttach = async (documentId: string) => {
    setAttachingId(documentId)
    try {
      await onAttachDocument(documentId)
    } finally {
      setAttachingId(null)
    }
  }

  return (
    <div className="mt-2.5 border border-white/[0.04] bg-white/[0.01] rounded-xl overflow-hidden">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full px-3 py-2 flex items-center justify-between text-[12px] text-neutral-500 hover:text-neutral-300 hover:bg-white/[0.02] transition-colors"
      >
        <span className="flex items-center gap-1.5">
          <Waypoints className="w-3.5 h-3.5 text-sky-400/50" />
          <span>
            Đồ thị dẫn chiếu · {visibleNodes.length} điều khoản · {path.length} liên kết
          </span>
        </span>
        {expanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
      </button>

      {expanded && (
        <div className="border-t border-white/[0.03]">
          <div className="h-56 relative">
            <ForceGraphView
              nodes={fgNodes}
              links={fgLinks}
              selectedId={selectedAddr}
              onNodeClick={(n) => setSelectedAddr(n.id)}
            />
          </div>

          {/* Legend */}
          <div className="flex items-center gap-3 px-3 py-1.5 border-t border-white/[0.03] text-[10px] text-neutral-500">
            {NODE_TYPE_LEGEND.map((l) => (
              <span key={l.type} className="flex items-center gap-1">
                <span
                  className="inline-block w-2 h-2 rounded-full"
                  style={{
                    backgroundColor: NODE_TYPE_COLOR[l.type],
                    ...(l.type === "out_of_scope"
                      ? { border: `1px dashed ${NODE_TYPE_COLOR[l.type]}`, backgroundColor: "transparent" }
                      : {}),
                  }}
                />
                {l.label}
              </span>
            ))}
          </div>

          {/* Node detail panel — thay cho popover neo theo canvas (đơn giản, ổn định hơn) */}
          {selectedNode && (
            <div className="p-3 border-t border-white/[0.03] text-[12px] space-y-2 bg-white/[0.015]">
              <div className="flex items-start justify-between gap-2">
                <span className="font-medium text-neutral-300 leading-relaxed">{selectedNode.label}</span>
                <button
                  onClick={() => setSelectedAddr(null)}
                  className="shrink-0 text-neutral-600 hover:text-neutral-300"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>

              {selectedNode.content ? (
                <p className="text-neutral-400 leading-relaxed whitespace-pre-wrap max-h-40 overflow-y-auto scrollbar-thin">
                  {selectedNode.content}
                </p>
              ) : selectedNode.in_library && selectedNode.document_id ? (
                <div className="flex items-center justify-between gap-2 text-neutral-500">
                  <span>Đã có trong thư viện, chưa gắn vào hội thoại này.</span>
                  {attachedDocumentIds.has(selectedNode.document_id) ? (
                    <span className="text-emerald-400/70 shrink-0">Đã gắn</span>
                  ) : (
                    <button
                      onClick={() => handleAttach(selectedNode.document_id!)}
                      disabled={attachingId === selectedNode.document_id}
                      className="shrink-0 flex items-center gap-1 px-2 py-1 rounded-md bg-emerald-500/10 text-emerald-400/80 border border-emerald-500/15 hover:bg-emerald-500/15 transition-colors disabled:opacity-50"
                    >
                      {attachingId === selectedNode.document_id ? (
                        <Loader2 className="w-3 h-3 animate-spin" />
                      ) : (
                        <Plus className="w-3 h-3" />
                      )}
                      Thêm vào hội thoại
                    </button>
                  )}
                </div>
              ) : (
                <div className="flex items-center gap-1.5 text-neutral-500">
                  <FileWarning className="w-3.5 h-3.5 text-amber-400/50 shrink-0" />
                  <span>Chưa có trong thư viện — văn bản đích chưa được tải lên.</span>
                </div>
              )}
            </div>
          )}

          {/* Tài liệu được viện dẫn nhưng chưa gắn hội thoại/chưa có trong thư viện */}
          {suggestedDocuments.length > 0 && (
            <div className="p-3 border-t border-white/[0.03] flex flex-wrap gap-1.5">
              {suggestedDocuments.map((s) => {
                const attached = s.document_id ? attachedDocumentIds.has(s.document_id) : false
                return (
                  <div
                    key={s.document_code}
                    className="flex items-center gap-1.5 pl-2.5 pr-1.5 py-1 rounded-lg bg-white/[0.02] border border-white/[0.05] text-[11px] text-neutral-400"
                  >
                    <span className="truncate max-w-[160px]">{s.name || s.document_code}</span>
                    {!s.in_library ? (
                      <span className="text-amber-400/60 text-[10px] shrink-0">chưa có</span>
                    ) : attached ? (
                      <span className="text-emerald-400/70 text-[10px] shrink-0">đã gắn</span>
                    ) : (
                      <button
                        onClick={() => handleAttach(s.document_id!)}
                        disabled={attachingId === s.document_id}
                        className="shrink-0 flex items-center justify-center w-5 h-5 rounded bg-emerald-500/10 text-emerald-400/80 hover:bg-emerald-500/15 transition-colors disabled:opacity-50"
                        title="Thêm vào hội thoại"
                      >
                        {attachingId === s.document_id ? (
                          <Loader2 className="w-3 h-3 animate-spin" />
                        ) : (
                          <Plus className="w-3 h-3" />
                        )}
                      </button>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
