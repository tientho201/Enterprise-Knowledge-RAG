"use client"

import React, { useState } from "react"
import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"
import {
  Plus,
  Trash2,
  MessageSquare,
  PanelLeftClose,
  Zap,
  FileText,
  BookOpen,
  History,
  LogOut,
  MoreHorizontal,
  Settings,
  Sparkles
} from "lucide-react"
import { useApp } from "@/lib/context"
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu"
import SettingsModal from "@/components/SettingsModal"
import UpgradeModal from "@/components/UpgradeModal"

export default function Sidebar() {
  const pathname = usePathname()
  const router = useRouter()
  const { 
    chatSessions, 
    activeSessionId, 
    setActiveSessionId,
    loadConversation,
    showLeftSidebar, 
    setShowLeftSidebar,
    handleNewChat,
    handleDeleteSession,
    user,
    logout
  } = useApp()

  const [showSettings, setShowSettings] = useState(false)
  const [showUpgrade, setShowUpgrade] = useState(false)

  if (!showLeftSidebar) return null

  const navItems = [
    { name: "Trợ lý AI", href: "/", icon: MessageSquare },
    { name: "Thư viện tài liệu", href: "/document-library", icon: FileText },
    { name: "Vault Nghiên cứu", href: "/research-vault", icon: BookOpen },
    { name: "Lịch sử làm việc", href: "/work-history", icon: History },
    { name: "Giao diện nâng cao", href: "/advanced-interface", icon: Settings }
  ]

  const handleSessionClick = async (sessionId: string) => {
    setActiveSessionId(sessionId)
    // Load conversation messages if not already loaded
    await loadConversation(sessionId)
    if (pathname !== "/") {
      router.push("/")
    }
  }

  const handleCreateNewChat = () => {
    handleNewChat()
    if (pathname !== "/") {
      router.push("/")
    }
  }

  return (
    <aside className="w-[260px] border-r border-white/[0.04] bg-[#0f0f0f]/80 backdrop-blur-xl shrink-0 flex flex-col z-10 sidebar-transition h-full">
      {/* Brand */}
      <div className="p-4 pb-3 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-emerald-500/80 to-teal-600/80 flex items-center justify-center">
            <Zap className="w-4 h-4 text-white" />
          </div>
          <div>
            <h1 className="text-sm font-bold text-neutral-100 tracking-tight">
              Knowledge RAG
            </h1>
            <div className="text-[10px] text-neutral-500 font-medium tracking-wide">Enterprise Legal</div>
          </div>
        </div>
        <button 
          onClick={() => setShowLeftSidebar(false)}
          className="p-1.5 rounded-lg hover:bg-white/[0.04] text-neutral-500 hover:text-neutral-300 transition-colors md:hidden"
        >
          <PanelLeftClose className="w-4 h-4" />
        </button>
      </div>

      {/* Main Pages Navigation */}
      <div className="px-2 py-3 space-y-0.5 border-b border-white/[0.04]">
        {navItems.map((item) => {
          const isActive = pathname === item.href;
          const Icon = item.icon;
          return (
            <Link
              key={item.name}
              href={item.href}
              className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-[13px] font-medium transition-all ${
                isActive 
                  ? "bg-emerald-500/10 text-emerald-300 border-l-2 border-emerald-500" 
                  : "text-neutral-400 hover:bg-white/[0.03] hover:text-neutral-200"
              }`}
            >
              <Icon className={`w-4 h-4 ${isActive ? "text-emerald-400" : "text-neutral-500"}`} />
              <span>{item.name}</span>
            </Link>
          )
        })}
      </div>

      {/* New Chat */}
      <div className="px-3 pt-4 pb-2">
        <button 
          onClick={handleCreateNewChat}
          className="w-full flex items-center justify-center gap-2 py-2 px-4 rounded-xl border border-white/[0.06] bg-white/[0.02] hover:bg-white/[0.05] text-neutral-300 text-xs font-medium transition-all hover:border-white/[0.1]"
        >
          <Plus className="w-3.5 h-3.5" />
          Hội thoại mới
        </button>
      </div>

      {/* Session List */}
      <div className="flex-1 overflow-y-auto px-2 space-y-0.5 scrollbar-thin">
        <div className="px-3 py-1.5 text-[10px] font-semibold text-neutral-500 uppercase tracking-wider">
          Lịch sử chat
        </div>
        
        {chatSessions.map((session) => {
          const isActive = session.id === activeSessionId && pathname === "/";
          return (
            <div
              key={session.id}
              onClick={() => handleSessionClick(session.id)}
              className={`group flex items-center justify-between px-3 py-2 rounded-lg text-[13px] cursor-pointer transition-all ${
                isActive 
                  ? "bg-white/[0.06] text-neutral-100" 
                  : "text-neutral-400 hover:bg-white/[0.03] hover:text-neutral-200"
              }`}
            >
              <div className="flex items-center gap-2.5 min-w-0 flex-1">
                <MessageSquare className={`w-3.5 h-3.5 shrink-0 ${isActive ? "text-emerald-400/70" : "text-neutral-600"}`} />
                <span className="truncate">{session.title}</span>
              </div>
              
              <button 
                onClick={(e) => {
                  e.stopPropagation()
                  handleDeleteSession(session.id, e)
                }}
                className="opacity-0 group-hover:opacity-100 p-1 rounded-md hover:bg-white/[0.06] text-neutral-500 hover:text-red-400 transition-all"
              >
                <Trash2 className="w-3 h-3" />
              </button>
            </div>
          )
        })}
      </div>

      {/* User Profile Widget */}
      {user && (
        <div className="p-3 border-t border-white/[0.04] flex items-center justify-between gap-2.5 bg-white/[0.01]">
          <div className="flex items-center gap-2 min-w-0">
            {/* User Avatar */}
            {user.avatarUrl ? (
              <img
                src={user.avatarUrl}
                alt={user.name}
                className="w-8 h-8 rounded-full border border-emerald-500/20 shrink-0 bg-gradient-to-br from-emerald-500/10 to-teal-500/10"
              />
            ) : (
              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center shrink-0 text-white font-bold text-[10px]">
                {user.name.charAt(0).toUpperCase()}
              </div>
            )}

            {/* User Details */}
            <div className="min-w-0 flex-1">
              <div className="text-[12px] font-semibold text-neutral-200 truncate leading-tight">
                {user.name}
              </div>
              <div className="text-[10px] text-neutral-500 truncate leading-tight mt-0.5">
                {user.email}
              </div>
            </div>
          </div>

          {/* Menu tài khoản */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                className="p-1.5 rounded-lg hover:bg-white/[0.06] text-neutral-500 hover:text-neutral-200 transition-colors shrink-0 cursor-pointer outline-none"
                title="Tài khoản"
              >
                <MoreHorizontal className="w-3.5 h-3.5" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" side="top">
              <DropdownMenuItem onClick={() => setShowSettings(true)}>
                <Settings className="w-3.5 h-3.5" />
                Cài đặt
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => setShowUpgrade(true)}>
                <Sparkles className="w-3.5 h-3.5" />
                Nâng cấp
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="destructive" onClick={() => logout()}>
                <LogOut className="w-3.5 h-3.5" />
                Đăng xuất
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      )}

      <SettingsModal open={showSettings} onOpenChange={setShowSettings} />
      <UpgradeModal open={showUpgrade} onOpenChange={setShowUpgrade} />
    </aside>
  )
}
