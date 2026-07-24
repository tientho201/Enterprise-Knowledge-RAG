"use client"

// Tầng RENDER của đồ thị — độc lập với schema Neo4j (nhận DTO node/link ổn định).
// Khi Provision layer xong, chỉ tầng dữ liệu đổi; component này giữ nguyên.
// autoPauseRedraw=false → canvas vẽ liên tục ⇒ đổi highlight/opacity mượt, không cần
// reheat simulation (không làm node nhảy khi highlight theo truy vấn).

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import ForceGraph2D from "react-force-graph-2d"

export interface FGNode {
  id: string
  label: string
  type: "document" | "chunk" | "provision"
  group: string
  meta?: Record<string, unknown>
  // Được react-force-graph gán khi chạy mô phỏng lực:
  x?: number
  y?: number
}

export interface FGLink {
  source: string | FGNode
  target: string | FGNode
  rel: string
}

interface Props {
  nodes: FGNode[]
  links: FGLink[]
  // Khi có tập highlight (kết quả truy vấn): node trong tập → sáng, ngoài tập → dim.
  highlightedIds?: Set<string> | null
  // Node tài liệu đang bung — vẽ vòng ngoài làm dấu hiệu (bấm lại để thu).
  expandedIds?: Set<string> | null
  selectedId?: string | null
  onNodeClick?: (node: FGNode) => void
}

const TYPE_COLOR: Record<string, string> = {
  document: "#34d399", // emerald-400
  chunk: "#38bdf8", // sky-400
  provision: "#a78bfa", // violet-400
}

function linkEndId(end: string | FGNode): string {
  return typeof end === "object" ? end.id : end
}

export default function ForceGraphView({
  nodes,
  links,
  highlightedIds,
  expandedIds,
  selectedId,
  onNodeClick,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const fgRef = useRef<any>(null)
  const [size, setSize] = useState({ w: 0, h: 0 })
  // Opacity hiện tại của từng node/cạnh — ease dần về target mỗi frame (autoPauseRedraw
  // false ⇒ vẽ liên tục) để highlight/dim mượt, không nhảy đột ngột.
  const nodeAlpha = useRef<Map<string, number>>(new Map())
  const linkAlpha = useRef<Map<string, number>>(new Map())

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const measure = () => setSize({ w: el.clientWidth, h: el.clientHeight })
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    measure()
    return () => ro.disconnect()
  }, [])

  const hasHighlight = !!highlightedIds && highlightedIds.size > 0
  const isDimmed = useCallback(
    (id: string) => hasHighlight && !highlightedIds!.has(id),
    [hasHighlight, highlightedIds]
  )

  const paintNode = useCallback(
    (node: FGNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const isDoc = node.type === "document"
      const r = isDoc ? 6 : 3.5
      const target = isDimmed(node.id) ? 0.12 : 1
      const cur = nodeAlpha.current.get(node.id) ?? target
      const alpha = cur + (target - cur) * 0.18 // ease
      nodeAlpha.current.set(node.id, alpha)
      ctx.globalAlpha = alpha

      ctx.beginPath()
      ctx.arc(node.x!, node.y!, r, 0, 2 * Math.PI)
      ctx.fillStyle = TYPE_COLOR[node.type] || "#a3a3a3"
      ctx.fill()

      // Vòng ngoài: tài liệu đang bung (dấu hiệu bấm lại để thu).
      if (expandedIds?.has(node.id)) {
        ctx.beginPath()
        ctx.arc(node.x!, node.y!, r + 3, 0, 2 * Math.PI)
        ctx.lineWidth = 1 / globalScale
        ctx.strokeStyle = "rgba(52,211,153,0.5)"
        ctx.stroke()
      }

      if (node.id === selectedId) {
        ctx.beginPath()
        ctx.arc(node.x!, node.y!, r + 1.5, 0, 2 * Math.PI)
        ctx.lineWidth = 2 / globalScale
        ctx.strokeStyle = "#ffffff"
        ctx.stroke()
      }

      const fontSize = (isDoc ? 11 : 9) / globalScale
      ctx.font = `${fontSize}px Inter, system-ui, sans-serif`
      ctx.textAlign = "center"
      ctx.textBaseline = "top"
      ctx.fillStyle = "#d4d4d4" // độ mờ do globalAlpha (eased) quản lý
      const text = node.label.length > 30 ? node.label.slice(0, 28) + "…" : node.label
      ctx.fillText(text, node.x!, node.y! + r + 1)
      ctx.globalAlpha = 1
    },
    [isDimmed, selectedId, expandedIds]
  )

  const paintPointerArea = useCallback(
    (node: FGNode, color: string, ctx: CanvasRenderingContext2D) => {
      const r = node.type === "document" ? 6 : 3.5
      ctx.fillStyle = color
      ctx.beginPath()
      ctx.arc(node.x!, node.y!, r + 2, 0, 2 * Math.PI)
      ctx.fill()
    },
    []
  )

  const linkColor = useCallback(
    (link: FGLink) => {
      const s = linkEndId(link.source)
      const t = linkEndId(link.target)
      const lit = hasHighlight && highlightedIds!.has(s) && highlightedIds!.has(t)
      // Cạnh sáng khi cả 2 đầu trúng (client tự suy — endpoint B chỉ trả node id).
      const target = hasHighlight ? (lit ? 0.55 : 0.04) : 0.22
      const key = `${s}|${t}`
      const cur = linkAlpha.current.get(key) ?? target
      const alpha = cur + (target - cur) * 0.18
      linkAlpha.current.set(key, alpha)
      const rgb = lit ? "52,211,153" : "140,140,140"
      return `rgba(${rgb},${alpha.toFixed(3)})`
    },
    [hasHighlight, highlightedIds]
  )

  // Định danh graphData chỉ đổi khi CẤU TRÚC đổi (nạp overview / bung / thu) — KHÔNG
  // đổi khi highlight, nên highlight không reheat mô phỏng (node không nhảy). Node
  // giữ nguyên object ref → giữ vị trí x/y qua các lần bung. Link truyền bản sao id
  // chuỗi để react-force-graph tự mutate bản sao, không làm hỏng state canonical.
  const graphData = useMemo(
    () => ({
      nodes,
      links: links.map((l) => ({
        source: linkEndId(l.source),
        target: linkEndId(l.target),
        rel: l.rel,
      })),
    }),
    [nodes, links]
  )

  return (
    <div ref={containerRef} className="w-full h-full">
      {size.w > 0 && (
        <ForceGraph2D
          ref={fgRef}
          width={size.w}
          height={size.h}
          graphData={graphData}
          backgroundColor="rgba(0,0,0,0)"
          nodeRelSize={5}
          nodeCanvasObject={paintNode}
          nodePointerAreaPaint={paintPointerArea}
          linkColor={linkColor}
          linkWidth={1}
          linkDirectionalParticles={0}
          autoPauseRedraw={false}
          cooldownTicks={120}
          onNodeClick={(n: FGNode) => onNodeClick?.(n)}
          onEngineStop={() => fgRef.current?.zoomToFit(400, 60)}
        />
      )}
    </div>
  )
}
