import { Geist_Mono, Inter } from "next/font/google"
import type { Metadata } from "next"

import "./globals.css"
import { ThemeProvider } from "@/components/theme-provider"
import { AppContextProvider } from "@/lib/context"
import Sidebar from "@/components/Sidebar"
import { cn } from "@/lib/utils"

const inter = Inter({subsets:['latin', 'vietnamese'],variable:'--font-sans'})

const fontMono = Geist_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
})

export const metadata: Metadata = {
  title: "Enterprise Knowledge RAG — Hệ thống Tra cứu Pháp lý AI",
  description: "Trợ lý AI chuyên sâu tra cứu, phân tích tài liệu pháp lý và quy chế nội bộ doanh nghiệp. Sử dụng công nghệ RAG (Retrieval-Augmented Generation) với Vector Database.",
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html
      lang="vi"
      suppressHydrationWarning
      className={cn("antialiased", fontMono.variable, "font-sans", inter.variable)}
    >
      <body>
        <ThemeProvider>
          <AppContextProvider>
            <div className="bg-[#0a0a0a] h-screen text-neutral-100 relative overflow-hidden flex font-sans dot-bg">
              {/* ===== BACKGROUND AMBIENT ORBS ===== */}
              <div className="orb-1 w-[600px] h-[600px] bg-emerald-600/[0.07] rounded-full blur-[120px] fixed -top-60 -left-40 pointer-events-none" />
              <div className="orb-2 w-[500px] h-[500px] bg-violet-600/[0.05] rounded-full blur-[120px] fixed -bottom-40 -right-40 pointer-events-none" />
              <div className="orb-3 w-[400px] h-[400px] bg-sky-600/[0.04] rounded-full blur-[100px] fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 pointer-events-none" />

              <Sidebar />

              <div className="flex-1 flex flex-col min-w-0 z-0 relative h-full">
                {children}
              </div>
            </div>
          </AppContextProvider>
        </ThemeProvider>
      </body>
    </html>
  )
}

