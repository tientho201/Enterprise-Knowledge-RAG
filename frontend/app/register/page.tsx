"use client"

import React, { useEffect, useRef, useState } from "react"
import Link from "next/link"
import { useApp } from "@/lib/context"
import { Zap, User, Mail, Lock, Eye, EyeOff, ArrowRight, AlertCircle, RefreshCw, ShieldCheck } from "lucide-react"

const RESEND_COOLDOWN_SECONDS = 60

export default function RegisterPage() {
  const { register, verifyOtp, resendOtp } = useApp()
  const [step, setStep] = useState<"form" | "otp">("form")
  const [name, setName] = useState("")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  // ── OTP step ──
  const [otpCode, setOtpCode] = useState("")
  const [otpError, setOtpError] = useState<string | null>(null)
  const [isVerifying, setIsVerifying] = useState(false)
  const [resendCooldown, setResendCooldown] = useState(0)
  const [isResending, setIsResending] = useState(false)
  const cooldownTimer = useRef<ReturnType<typeof setInterval> | null>(null)

  const startCooldown = () => {
    setResendCooldown(RESEND_COOLDOWN_SECONDS)
    if (cooldownTimer.current) clearInterval(cooldownTimer.current)
    cooldownTimer.current = setInterval(() => {
      setResendCooldown((s) => {
        if (s <= 1 && cooldownTimer.current) {
          clearInterval(cooldownTimer.current)
        }
        return Math.max(0, s - 1)
      })
    }, 1000)
  }

  useEffect(() => {
    return () => {
      if (cooldownTimer.current) clearInterval(cooldownTimer.current)
    }
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name || !email || !password || !confirmPassword) {
      setError("Vui lòng điền đầy đủ các trường thông tin!")
      return
    }
    if (password !== confirmPassword) {
      setError("Mật khẩu xác nhận không trùng khớp!")
      return
    }
    if (password.length < 8) {
      setError("Mật khẩu phải chứa ít nhất 8 ký tự!")
      return
    }

    setError(null)
    setIsLoading(true)

    const res = await register(name, email, password)
    setIsLoading(false)
    if (!res.success) {
      setError(res.error || "Đăng ký thất bại!")
      return
    }
    setStep("otp")
    startCooldown()
  }

  const handleVerifyOtp = async (e: React.FormEvent) => {
    e.preventDefault()
    if (otpCode.length !== 6) {
      setOtpError("Mã OTP gồm 6 chữ số!")
      return
    }
    setOtpError(null)
    setIsVerifying(true)
    const res = await verifyOtp(email, otpCode)
    setIsVerifying(false)
    if (!res.success) {
      setOtpError(res.error || "Xác minh OTP thất bại!")
    }
    // Thành công: AuthGuard tự chuyển hướng khi phát hiện token đã được set.
  }

  const handleResendOtp = async () => {
    if (resendCooldown > 0 || isResending) return
    setIsResending(true)
    setOtpError(null)
    const res = await resendOtp(email)
    setIsResending(false)
    if (!res.success) {
      setOtpError(res.error || "Không thể gửi lại mã OTP!")
      return
    }
    startCooldown()
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
            <h3 className="text-lg font-semibold text-neutral-200">
              {step === "form" ? "Đăng ký tài khoản" : "Xác minh email"}
            </h3>
            <p className="text-xs text-neutral-500 font-sans">
              {step === "form"
                ? "Tạo tài khoản mới để bắt đầu sử dụng"
                : `Nhập mã OTP 6 số vừa được gửi tới ${email}`}
            </p>
          </div>

          {step === "otp" ? (
            <form onSubmit={handleVerifyOtp} className="space-y-4">
              {otpError && (
                <div className="p-3.5 rounded-xl bg-red-500/5 border border-red-500/10 text-red-200/80 text-[13px] flex gap-2.5 items-start animate-msg-in">
                  <AlertCircle className="w-4 h-4 mt-0.5 shrink-0 text-red-400/80" />
                  <div className="leading-relaxed">{otpError}</div>
                </div>
              )}

              <div className="space-y-1.5">
                <label className="text-[11px] font-semibold text-neutral-400 uppercase tracking-wider">Mã OTP</label>
                <div className="relative">
                  <input
                    type="text"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    maxLength={6}
                    value={otpCode}
                    onChange={(e) => setOtpCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                    placeholder="000000"
                    className="w-full bg-white/[0.02] hover:bg-white/[0.04] border border-white/[0.06] focus:border-emerald-500/30 rounded-xl px-3.5 py-2.5 pl-10 text-[15px] tracking-[0.4em] text-neutral-200 placeholder:text-neutral-600 focus:outline-none focus:ring-2 focus:ring-emerald-500/5 transition-all"
                    disabled={isVerifying}
                  />
                  <ShieldCheck className="w-4 h-4 text-neutral-600 absolute left-3.5 top-1/2 -translate-y-1/2" />
                </div>
              </div>

              <button
                type="submit"
                disabled={isVerifying}
                className={`w-full py-2.5 px-4 rounded-xl text-xs font-semibold tracking-wide text-white transition-all flex items-center justify-center gap-2 cursor-pointer ${
                  isVerifying
                    ? "bg-emerald-500/50 cursor-not-allowed"
                    : "bg-gradient-to-r from-emerald-500/80 to-teal-500/80 hover:from-emerald-500 hover:to-teal-500 shadow-md shadow-emerald-500/10 active:scale-[0.98]"
                }`}
              >
                {isVerifying ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    Đang xác minh...
                  </>
                ) : (
                  <>
                    Xác nhận
                    <ArrowRight className="w-3.5 h-3.5" />
                  </>
                )}
              </button>

              <button
                type="button"
                onClick={handleResendOtp}
                disabled={resendCooldown > 0 || isResending}
                className="w-full py-2 text-[12px] text-neutral-500 hover:text-emerald-400/80 transition-colors disabled:hover:text-neutral-500 cursor-pointer disabled:cursor-not-allowed flex items-center justify-center gap-1.5"
              >
                {isResending ? (
                  <RefreshCw className="w-3 h-3 animate-spin" />
                ) : resendCooldown > 0 ? (
                  `Gửi lại mã sau ${resendCooldown}s`
                ) : (
                  "Gửi lại mã OTP"
                )}
              </button>
            </form>
          ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Error Message */}
            {error && (
              <div className="p-3.5 rounded-xl bg-red-500/5 border border-red-500/10 text-red-200/80 text-[13px] flex gap-2.5 items-start animate-msg-in">
                <AlertCircle className="w-4 h-4 mt-0.5 shrink-0 text-red-400/80" />
                <div className="leading-relaxed">{error}</div>
              </div>
            )}

            {/* Full Name Field */}
            <div className="space-y-1.5">
              <label className="text-[11px] font-semibold text-neutral-400 uppercase tracking-wider">Họ và tên</label>
              <div className="relative">
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Nguyễn Văn A"
                  className="w-full bg-white/[0.02] hover:bg-white/[0.04] border border-white/[0.06] focus:border-emerald-500/30 rounded-xl px-3.5 py-2.5 pl-10 text-[13px] text-neutral-200 placeholder:text-neutral-600 focus:outline-none focus:ring-2 focus:ring-emerald-500/5 transition-all"
                  disabled={isLoading}
                />
                <User className="w-4 h-4 text-neutral-600 absolute left-3.5 top-1/2 -translate-y-1/2" />
              </div>
            </div>

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
              <label className="text-[11px] font-semibold text-neutral-400 uppercase tracking-wider">Mật khẩu</label>
              <div className="relative">
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Tối thiểu 8 ký tự"
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

            {/* Confirm Password Field */}
            <div className="space-y-1.5">
              <label className="text-[11px] font-semibold text-neutral-400 uppercase tracking-wider">Xác nhận mật khẩu</label>
              <div className="relative">
                <input
                  type={showPassword ? "text" : "password"}
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="Nhập lại mật khẩu"
                  className="w-full bg-white/[0.02] hover:bg-white/[0.04] border border-white/[0.06] focus:border-emerald-500/30 rounded-xl px-3.5 py-2.5 pl-10 pr-10 text-[13px] text-neutral-200 placeholder:text-neutral-600 focus:outline-none focus:ring-2 focus:ring-emerald-500/5 transition-all"
                  disabled={isLoading}
                />
                <Lock className="w-4 h-4 text-neutral-600 absolute left-3.5 top-1/2 -translate-y-1/2" />
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
                  Đang đăng ký...
                </>
              ) : (
                <>
                  Đăng ký
                  <ArrowRight className="w-3.5 h-3.5" />
                </>
              )}
            </button>
          </form>
          )}

          {/* Footer Card */}
          <div className="text-center text-[12px] text-neutral-500 pt-2 border-t border-white/[0.04]">
            {step === "otp" ? (
              <button
                type="button"
                onClick={() => setStep("form")}
                className="text-emerald-400/80 hover:text-emerald-400 font-medium transition-colors cursor-pointer"
              >
                &larr; Quay lại chỉnh sửa thông tin đăng ký
              </button>
            ) : (
              <>
                Đã có tài khoản?{" "}
                <Link href="/login" className="text-emerald-400/80 hover:text-emerald-400 font-medium transition-colors">
                  Đăng nhập
                </Link>
              </>
            )}
          </div>

        </div>

      </div>
    </div>
  )
}
