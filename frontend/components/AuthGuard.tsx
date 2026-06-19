"use client"

import React, { useEffect, useState } from "react"
import { usePathname, useRouter } from "next/navigation"
import { useApp } from "@/lib/context"
import { getAccessToken } from "@/lib/api"
import Sidebar from "@/components/Sidebar"
import { RefreshCw } from "lucide-react"

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const { user, isAuthLoading } = useApp()
  const router = useRouter()
  const pathname = usePathname()
  const [isMounted, setIsMounted] = useState(false)

  useEffect(() => {
    setIsMounted(true)
  }, [])

  useEffect(() => {
    if (!isMounted || isAuthLoading) return

    const isAuthPage = pathname === "/login" || pathname === "/register"
    const hasToken = !!getAccessToken()

    if (!hasToken && !isAuthPage) {
      router.push("/login")
    } else if (hasToken && isAuthPage) {
      router.push("/")
    }
  }, [user, pathname, isMounted, isAuthLoading, router])

  // Simple loading state during mount (hydration) or token verification
  if (!isMounted || isAuthLoading) {
    return (
      <div className="h-screen w-screen bg-[#0a0a0a] flex flex-col items-center justify-center text-neutral-400 gap-4">
        <RefreshCw className="w-8 h-8 animate-spin text-emerald-400/60" />
        <div className="text-sm font-medium tracking-wide">Đang xác thực phiên đăng nhập...</div>
      </div>
    )
  }

  const isAuthPage = pathname === "/login" || pathname === "/register"
  const hasToken = !!getAccessToken()

  // If not logged in and not on login/register page, show loading while redirecting
  if (!hasToken && !isAuthPage) {
    return (
      <div className="h-screen w-screen bg-[#0a0a0a] flex flex-col items-center justify-center text-neutral-400 gap-4">
        <RefreshCw className="w-8 h-8 animate-spin text-emerald-400/60" />
        <div className="text-sm font-medium tracking-wide">Yêu cầu đăng nhập...</div>
      </div>
    )
  }

  // If logged in and on login/register page, show loading while redirecting to home
  if (hasToken && isAuthPage) {
    return (
      <div className="h-screen w-screen bg-[#0a0a0a] flex flex-col items-center justify-center text-neutral-400 gap-4">
        <RefreshCw className="w-8 h-8 animate-spin text-emerald-400/60" />
        <div className="text-sm font-medium tracking-wide font-sans">Đang chuyển hướng...</div>
      </div>
    )
  }

  // Core layout manager
  return (
    <div className="bg-[#0a0a0a] h-screen text-neutral-100 relative overflow-hidden flex font-sans dot-bg w-full">
      {/* ===== BACKGROUND AMBIENT ORBS ===== */}
      <div className="orb-1 w-[600px] h-[600px] bg-emerald-600/[0.07] rounded-full blur-[120px] fixed -top-60 -left-40 pointer-events-none" />
      <div className="orb-2 w-[500px] h-[500px] bg-violet-600/[0.05] rounded-full blur-[120px] fixed -bottom-40 -right-40 pointer-events-none" />
      <div className="orb-3 w-[400px] h-[400px] bg-sky-600/[0.04] rounded-full blur-[100px] fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 pointer-events-none" />

      {/* Show Sidebar only if not on auth pages */}
      {!isAuthPage && <Sidebar />}

      <div className="flex-1 flex flex-col min-w-0 z-0 relative h-full">
        {children}
      </div>
    </div>
  )
}
