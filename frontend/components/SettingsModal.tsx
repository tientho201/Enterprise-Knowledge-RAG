"use client"

import React, { useEffect, useState } from "react"
import { Settings, Shield, Sparkles, Users, Loader2 } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog"
import { useApp } from "@/lib/context"
import { adminAPI, ApiError, type AuthUser } from "@/lib/api"

const ROLE_LABEL: Record<string, string> = {
  admin: "Quản trị viên",
  editor: "Biên tập viên",
  viewer: "Người xem",
}

const ROLE_OPTIONS: Array<"admin" | "editor" | "viewer"> = ["admin", "editor", "viewer"]

export default function SettingsModal({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { user } = useApp()
  const isAdmin = user?.role === "admin"

  const [users, setUsers] = useState<AuthUser[]>([])
  const [usersLoading, setUsersLoading] = useState(false)
  const [usersError, setUsersError] = useState<string | null>(null)
  const [updatingUserId, setUpdatingUserId] = useState<string | null>(null)

  useEffect(() => {
    if (!open || !isAdmin) return
    setUsersLoading(true)
    setUsersError(null)
    adminAPI
      .listUsers()
      .then(setUsers)
      .catch((err) => {
        setUsersError(err instanceof ApiError ? err.detail : "Không tải được danh sách người dùng")
      })
      .finally(() => setUsersLoading(false))
  }, [open, isAdmin])

  const handleRoleChange = async (targetId: string, role: "admin" | "editor" | "viewer") => {
    setUpdatingUserId(targetId)
    try {
      const updated = await adminAPI.updateUserRole(targetId, role)
      setUsers((prev) => prev.map((u) => (u.id === targetId ? updated : u)))
    } catch (err) {
      setUsersError(err instanceof ApiError ? err.detail : "Không đổi được quyền")
    } finally {
      setUpdatingUserId(null)
    }
  }

  if (!user) return null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto scrollbar-thin">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Settings className="w-4 h-4 text-emerald-400/70" />
            Cài đặt tài khoản
          </DialogTitle>
          <DialogDescription>Thông tin tài khoản và phân quyền của bạn.</DialogDescription>
        </DialogHeader>

        {/* Profile */}
        <div className="flex items-center gap-3 p-3 rounded-xl bg-white/[0.02] border border-white/[0.04]">
          {user.avatarUrl ? (
            <img
              src={user.avatarUrl}
              alt={user.name}
              className="w-11 h-11 rounded-full border border-emerald-500/20 shrink-0"
            />
          ) : (
            <div className="w-11 h-11 rounded-full bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center shrink-0 text-white font-bold text-sm">
              {user.name.charAt(0).toUpperCase()}
            </div>
          )}
          <div className="min-w-0 flex-1">
            <div className="text-[13px] font-semibold text-neutral-100 truncate">{user.name}</div>
            <div className="text-[11px] text-neutral-500 truncate">{user.email}</div>
          </div>
        </div>

        {/* Role + Plan */}
        <div className="grid grid-cols-2 gap-2 mt-3">
          <div className="p-3 rounded-xl bg-white/[0.02] border border-white/[0.04] space-y-1">
            <div className="flex items-center gap-1.5 text-[10px] font-medium text-neutral-500 uppercase tracking-wider">
              <Shield className="w-3 h-3" />
              Quyền
            </div>
            <div className="text-[13px] font-semibold text-neutral-200">
              {ROLE_LABEL[user.role] || user.role}
            </div>
          </div>
          <div className="p-3 rounded-xl bg-white/[0.02] border border-white/[0.04] space-y-1">
            <div className="flex items-center gap-1.5 text-[10px] font-medium text-neutral-500 uppercase tracking-wider">
              <Sparkles className="w-3 h-3" />
              Gói
            </div>
            <div
              className={`text-[13px] font-semibold ${
                user.plan === "pro" ? "text-emerald-400" : "text-neutral-200"
              }`}
            >
              {user.plan === "pro" ? "Pro" : "Free"}
            </div>
          </div>
        </div>

        {/* Admin: user management */}
        {isAdmin && (
          <div className="mt-5 pt-4 border-t border-white/[0.06]">
            <div className="flex items-center gap-1.5 text-[11px] font-semibold text-neutral-400 uppercase tracking-wider mb-2">
              <Users className="w-3.5 h-3.5" />
              Quản lý người dùng
            </div>

            {usersError && (
              <div className="text-[11px] text-red-400/80 mb-2">{usersError}</div>
            )}

            {usersLoading ? (
              <div className="flex items-center gap-2 text-[12px] text-neutral-500 py-3">
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                Đang tải...
              </div>
            ) : (
              <div className="space-y-1.5 max-h-52 overflow-y-auto scrollbar-thin">
                {users.map((u) => (
                  <div
                    key={u.id}
                    className="flex items-center justify-between gap-2 p-2 rounded-lg bg-white/[0.02] border border-white/[0.04]"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="text-[12px] text-neutral-300 truncate">
                        {u.full_name || u.email}
                      </div>
                      <div className="text-[10px] text-neutral-600 truncate">{u.email}</div>
                    </div>
                    <select
                      value={u.role}
                      disabled={updatingUserId === u.id}
                      onChange={(e) =>
                        handleRoleChange(u.id, e.target.value as "admin" | "editor" | "viewer")
                      }
                      className="bg-white/[0.03] border border-white/[0.08] rounded-lg px-2 py-1 text-[11px] text-neutral-300 focus:outline-none focus:border-emerald-500/30 shrink-0 disabled:opacity-50"
                    >
                      {ROLE_OPTIONS.map((r) => (
                        <option key={r} value={r} className="bg-[#161616]">
                          {ROLE_LABEL[r]}
                        </option>
                      ))}
                    </select>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
