"use client"

import React, { useState } from "react"
import Link from "next/link"
import { useApp } from "@/lib/context"
import { Zap, Mail, Lock, Eye, EyeOff, ArrowRight, AlertCircle, RefreshCw } from "lucide-react"

export default function LoginPage() {
  const { login } = useApp()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!email || !password) {
      setError("Vui lòng điền đầy đủ thông tin!")
      return
    }
    setError(null)
    setIsLoading(true)

    const res = await login(email, password)
    setIsLoading(false)
    if (!res.success) {
      setError(res.error || "Có lỗi xảy ra!")
    }
  }

  const handleQuickLogin = async () => {
    setEmail("admin@enterprise.com")
    setPassword("admin123")
    setError(null)
    setIsLoading(true)

    const res = await login("admin@enterprise.com", "admin123")
    setIsLoading(false)
    if (!res.success) {
      setError(res.error || "Có lỗi xảy ra!")
    }
  }

  return (
    <div className="flex-1 flex items-center justify-center min-h-screen px-4 py-12 relative z-10">
      <div className="w-full max-w-[420px] space-y-6">
        
        {/* Logo and Brand */}
        <div className="flex flex-col items-center text-center space-y-2 mb-2 animate-msg-in">
          <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center shadow-lg shadow-emerald-500/20">
            <Zap className="w-6 h-6 text-white" />
          </div>
          <h2 className="text-xl font-bold text-neutral-100 tracking-tight">
            Knowledge RAG
          </h2>
          <p className="text-xs text-neutral-500">
            Hệ thống Tra cứu &amp; Phân tích Pháp lý AI Doanh nghiệp
          </p>
        </div>

        {/* Card Form */}
        <div className="glass-panel rounded-2xl p-6 md:p-8 space-y-6 shadow-2xl relative overflow-hidden border-white/[0.06] bg-white/[0.02] backdrop-blur-xl animate-msg-in [animation-delay:100ms]">
          
          <div className="space-y-1">
            <h3 className="text-lg font-semibold text-neutral-200">Đăng nhập</h3>
            <p className="text-xs text-neutral-500">Truy cập để bắt đầu làm việc với AI trợ lý</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Error Message */}
            {error && (
              <div className="p-3.5 rounded-xl bg-red-500/5 border border-red-500/10 text-red-200/80 text-[13px] flex gap-2.5 items-start animate-msg-in">
                <AlertCircle className="w-4 h-4 mt-0.5 shrink-0 text-red-400/80" />
                <div className="leading-relaxed">{error}</div>
              </div>
            )}

            {/* Email Field */}
            <div className="space-y-1.5">
              <label className="text-[11px] font-semibold text-neutral-400 uppercase tracking-wider">Email công việc</label>
              <div className="relative">
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="name@enterprise.com"
                  className="w-full bg-white/[0.02] hover:bg-white/[0.04] border border-white/[0.06] focus:border-emerald-500/30 rounded-xl px-3.5 py-2.5 pl-10 text-[13px] text-neutral-200 placeholder:text-neutral-600 focus:outline-none focus:ring-2 focus:ring-emerald-500/5 transition-all"
                  disabled={isLoading}
                />
                <Mail className="w-4 h-4 text-neutral-600 absolute left-3.5 top-1/2 -translate-y-1/2" />
              </div>
            </div>

            {/* Password Field */}
            <div className="space-y-1.5">
              <div className="flex justify-between items-center">
                <label className="text-[11px] font-semibold text-neutral-400 uppercase tracking-wider">Mật khẩu</label>
              </div>
              <div className="relative">
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full bg-white/[0.02] hover:bg-white/[0.04] border border-white/[0.06] focus:border-emerald-500/30 rounded-xl px-3.5 py-2.5 pl-10 pr-10 text-[13px] text-neutral-200 placeholder:text-neutral-600 focus:outline-none focus:ring-2 focus:ring-emerald-500/5 transition-all"
                  disabled={isLoading}
                />
                <Lock className="w-4 h-4 text-neutral-600 absolute left-3.5 top-1/2 -translate-y-1/2" />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3.5 top-1/2 -translate-y-1/2 text-neutral-600 hover:text-neutral-300 transition-colors"
                  disabled={isLoading}
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {/* Submit Button */}
            <button
              type="submit"
              disabled={isLoading}
              className={`w-full py-2.5 px-4 rounded-xl text-xs font-semibold tracking-wide text-white transition-all flex items-center justify-center gap-2 cursor-pointer ${
                isLoading
                  ? "bg-emerald-500/50 cursor-not-allowed"
                  : "bg-gradient-to-r from-emerald-500/80 to-teal-500/80 hover:from-emerald-500 hover:to-teal-500 shadow-md shadow-emerald-500/10 active:scale-[0.98]"
              }`}
            >
              {isLoading ? (
                <>
                  <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                  Đang đăng nhập...
                </>
              ) : (
                <>
                  Đăng nhập
                  <ArrowRight className="w-3.5 h-3.5" />
                </>
              )}
            </button>

            {/* Quick Admin Login Option */}
            <button
              type="button"
              onClick={handleQuickLogin}
              disabled={isLoading}
              className="w-full py-2.5 px-4 rounded-xl text-xs font-semibold tracking-wide border border-emerald-500/20 text-emerald-400 bg-emerald-500/[0.02] hover:bg-emerald-500/[0.06] transition-all flex items-center justify-center gap-2 cursor-pointer"
            >
              <Zap className="w-3.5 h-3.5 text-emerald-400" />
              Đăng nhập nhanh (Admin)
            </button>
          </form>
          
          {/* Footer Card */}
          <div className="text-center text-[12px] text-neutral-500">
            Chưa có tài khoản?{" "}
            <Link href="/register" className="text-emerald-400/80 hover:text-emerald-400 font-medium transition-colors">
              Đăng ký ngay
            </Link>
          </div>

        </div>

      </div>
    </div>
  )
}
