"use client"

import React, { useState } from "react"
import { Check, Sparkles, Loader2, Info } from "lucide-react"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { useApp } from "@/lib/context"
import { authAPI, ApiError } from "@/lib/api"

const FREE_FEATURES = ["Tra cứu Lai (Hybrid) / Vector / Từ khóa", "Upload tài liệu không giới hạn số lượng cơ bản"]
const PRO_FEATURES = [
  "Toàn bộ tính năng gói Free",
  "Chế độ tra cứu Nâng cao (graph tri thức, viện dẫn liên văn bản)",
  "Ưu tiên xử lý truy vấn",
]

export default function UpgradeModal({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { user, refreshUser, addAuditLog } = useApp()
  const [loading, setLoading] = useState<"pro" | "free" | null>(null)
  const [error, setError] = useState<string | null>(null)

  if (!user) return null

  const handleChangePlan = async (plan: "free" | "pro") => {
    setLoading(plan)
    setError(null)
    try {
      await authAPI.updatePlan(plan)
      await refreshUser()
      addAuditLog(
        plan === "pro" ? "Nâng cấp lên gói Pro (demo)" : "Hạ về gói Free",
        "config"
      )
      if (plan === "pro") onOpenChange(false)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Không đổi được gói")
    } finally {
      setLoading(null)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-emerald-400/70" />
            Nâng cấp gói
          </DialogTitle>
          <DialogDescription>Mở khoá Chế độ tra cứu Nâng cao và các tính năng Pro.</DialogDescription>
        </DialogHeader>

        <div className="flex items-start gap-2 p-2.5 rounded-lg bg-amber-500/[0.06] border border-amber-500/10 text-[10px] text-amber-300/80 leading-relaxed mb-3">
          <Info className="w-3.5 h-3.5 mt-0.5 shrink-0" />
          <span>
            Bản demo — đổi gói ngay lập tức, <strong>chưa tích hợp thanh toán thật</strong>. Không có giao dịch thẻ nào được thực hiện.
          </span>
        </div>

        {error && <div className="text-[11px] text-red-400/80 mb-3">{error}</div>}

        <div className="grid grid-cols-2 gap-3">
          {/* Free */}
          <div
            className={`p-4 rounded-xl border space-y-3 ${
              user.plan === "free"
                ? "border-emerald-500/30 bg-emerald-500/[0.04]"
                : "border-white/[0.06] bg-white/[0.02]"
            }`}
          >
            <div>
              <div className="text-[13px] font-semibold text-neutral-200">Free</div>
              <div className="text-[20px] font-bold text-neutral-100 mt-0.5">
                $0<span className="text-[11px] font-normal text-neutral-500">/tháng</span>
              </div>
            </div>
            <ul className="space-y-1.5">
              {FREE_FEATURES.map((f) => (
                <li key={f} className="flex items-start gap-1.5 text-[11px] text-neutral-400">
                  <Check className="w-3 h-3 mt-0.5 text-neutral-600 shrink-0" />
                  {f}
                </li>
              ))}
            </ul>
            {user.plan === "free" ? (
              <div className="text-center text-[11px] font-medium text-emerald-400 py-1.5">
                Gói hiện tại
              </div>
            ) : (
              <button
                onClick={() => handleChangePlan("free")}
                disabled={loading !== null}
                className="w-full py-1.5 rounded-lg text-[11px] font-medium border border-white/[0.08] text-neutral-300 hover:bg-white/[0.03] transition-all disabled:opacity-50"
              >
                {loading === "free" ? <Loader2 className="w-3 h-3 animate-spin mx-auto" /> : "Huỷ về Free"}
              </button>
            )}
          </div>

          {/* Pro */}
          <div
            className={`p-4 rounded-xl border space-y-3 ${
              user.plan === "pro"
                ? "border-emerald-500/30 bg-emerald-500/[0.04]"
                : "border-emerald-500/20 bg-emerald-500/[0.02]"
            }`}
          >
            <div>
              <div className="flex items-center gap-1.5 text-[13px] font-semibold text-emerald-300">
                Pro
                <Sparkles className="w-3 h-3" />
              </div>
              <div className="text-[20px] font-bold text-neutral-100 mt-0.5">
                $10<span className="text-[11px] font-normal text-neutral-500">/tháng</span>
              </div>
            </div>
            <ul className="space-y-1.5">
              {PRO_FEATURES.map((f) => (
                <li key={f} className="flex items-start gap-1.5 text-[11px] text-neutral-300">
                  <Check className="w-3 h-3 mt-0.5 text-emerald-400/70 shrink-0" />
                  {f}
                </li>
              ))}
            </ul>
            {user.plan === "pro" ? (
              <div className="text-center text-[11px] font-medium text-emerald-400 py-1.5">
                Gói hiện tại
              </div>
            ) : (
              <button
                onClick={() => handleChangePlan("pro")}
                disabled={loading !== null}
                className="w-full py-1.5 rounded-lg text-[11px] font-medium bg-emerald-500/80 text-white hover:bg-emerald-500 active:scale-[0.98] transition-all disabled:opacity-50"
              >
                {loading === "pro" ? (
                  <Loader2 className="w-3 h-3 animate-spin mx-auto" />
                ) : (
                  "Nâng cấp lên Pro"
                )}
              </button>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
