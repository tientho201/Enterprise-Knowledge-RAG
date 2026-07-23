import type { NextConfig } from "next"

// Rewrite này chỉ có tác dụng nếu code gọi đường dẫn tương đối "/api/v1/...".
// lib/api.ts hiện gọi thẳng absolute URL (BASE_URL + path) nên bỏ qua rewrite
// này — giữ lại để phòng chỗ nào khác lỡ fetch tương đối, và để đồng bộ nguồn
// URL với lib/api.ts (cùng đọc NEXT_PUBLIC_API_URL, tránh 2 nơi lệch nhau).
const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${BACKEND_URL}/api/v1/:path*`,
      },
    ]
  },
}

export default nextConfig
