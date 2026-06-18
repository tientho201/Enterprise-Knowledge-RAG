import { Geist_Mono, Inter } from "next/font/google"
import type { Metadata } from "next"

import "./globals.css"
import { ThemeProvider } from "@/components/theme-provider"
import { AppContextProvider } from "@/lib/context"
import AuthGuard from "@/components/AuthGuard"
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
            <AuthGuard>
              {children}
            </AuthGuard>
          </AppContextProvider>
        </ThemeProvider>
      </body>
    </html>
  )
}

