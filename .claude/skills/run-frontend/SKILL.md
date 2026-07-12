---
name: run-frontend
description: Chạy, build, lint hoặc format frontend Next.js (thư mục frontend/) của project Enterprise Knowledge RAG. Dùng khi user yêu cầu chạy dev server, build frontend, hoặc làm việc với code trong frontend/app, frontend/components.
---

# Frontend — Next.js app

`frontend/` — Next.js **16.2.6** + React **19.2.4**, package name `next-app`.

**Cảnh báo quan trọng** (`frontend/AGENTS.md`): đây là bản Next.js có breaking changes so với
training data cũ — API, convention, cấu trúc file có thể khác. Đọc
`node_modules/next/dist/docs/` cho phần liên quan trước khi viết code mới, đừng giả định pattern
Next.js quen thuộc còn đúng.

## Lệnh (từ `frontend/`)

```bash
cd frontend

npm install          # cài dependencies lần đầu
npm run dev          # dev server (next dev)
npm run build         # production build
npm run start         # chạy production build
npm run lint           # eslint
npm run typecheck      # tsc --noEmit
npm run format          # prettier --write "**/*.{ts,tsx}"
```

## Stack UI

- Tailwind v4 (`@tailwindcss/postcss`)
- shadcn/ui + radix-ui (`components.json` định nghĩa alias/style) — ưu tiên dùng component có
  sẵn trong `frontend/components/` trước khi tự viết mới.
- `next-themes` cho dark mode, `lucide-react` cho icon, `class-variance-authority` +
  `tailwind-merge` cho variant styling.

## Kết nối backend

`frontend/endpointAPIbe.json` mô tả contract API mà frontend gọi tới backend FastAPI — đối chiếu
file này khi thêm/sửa API call, và cập nhật nếu backend đổi endpoint (xem skill
`enterprise-knowledge-rag` cho danh sách route backend).

## Gotchas

- Thiếu `node_modules` hoặc version Node không tương thích là lỗi phổ biến nhất khi build fail —
  chạy `npm install` lại trước khi debug sâu hơn.
- Chưa có test runner nào được cấu hình (xem skill `testing`) — đừng giả định `npm test` tồn
  tại.
