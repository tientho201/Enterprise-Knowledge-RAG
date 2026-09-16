---
name: task-report
description: Dùng SAU KHI hoàn thành 1 task/fix/feature (đặc biệt task lấy từ .claude/tasks/*.md như production-ops-gaps.md, production-readiness-audit.md) để sinh 1 báo cáo PDF + Markdown mô tả đã sửa gì và cách test/verify, lưu vào thư mục report/. Trigger khi user nói "tạo báo cáo", "xuất PDF", "lưu report", "báo cáo kết quả task", "hướng dẫn test cho task này", hoặc ngay sau khi tick xong 1 checkbox task trong file .claude/tasks/*.md. KHÔNG dùng cho báo cáo tổng hợp nhiều task cùng lúc — mỗi lần chạy skill này ra đúng 1 báo cáo cho đúng 1 task.
---

# Task Report — sinh PDF báo cáo kết quả + hướng dẫn test sau mỗi task

Mỗi khi hoàn thành 1 task (sửa code, thêm feature, fix bug — nhất là các task đánh
checkbox trong `.claude/tasks/*.md`), tạo 1 báo cáo PDF tóm tắt: đã sửa gì, ở file nào, và
người khác (hoặc chính bạn sau này) test/verify lại bằng cách nào. Báo cáo lưu vào thư mục
`report/` ở gốc repo, kèm 1 bản Markdown song song cùng nội dung (dễ diff/search — PDF là
binary, không diff được, xem giải thích trong `report/README.md`).

## Quy trình 3 bước

### Bước 1 — Gom thông tin task vừa làm

Trước khi gọi script, xác định:

1. **Task ID + tiêu đề** — nếu task lấy từ 1 file trong `.claude/tasks/`, dùng đúng số thứ
   tự/tiêu đề đã ghi ở đó (vd Task "1.1" trong `production-ops-gaps.md`) để dễ đối chiếu
   ngược lại. Nếu không có task file gốc, tự đặt tiêu đề ngắn mô tả đúng việc đã làm.
2. **Tóm tắt thay đổi** — 2-4 câu giải thích đã sửa gì và VÌ SAO (không chỉ liệt kê "đã
   sửa file X" — nói rõ vấn đề gì được giải quyết).
3. **Danh sách file đã sửa** — lấy từ `git status`/`git diff --stat` của thay đổi vừa làm,
   mỗi file kèm 1 câu ngắn mô tả thay đổi ở file đó.
4. **Hướng dẫn test/verify** — liệt kê từng bước cụ thể, MỖI BƯỚC có lệnh chạy được thật
   (`uv run pytest ...`, `curl ...`, `npm run ...`) và mô tả kết quả kỳ vọng. Đây là phần
   quan trọng nhất của báo cáo — người đọc phải tự verify lại được mà không cần hỏi thêm.
5. **Kết quả** — `pass`/`fail`/`partial` + ghi chú ngắn (đã chạy test nào, kết quả ra sao).
6. **Rollback** (optional) — nếu cần, ghi cách quay lại trạng thái trước đó (`git revert
   <sha>`, hoặc mô tả thủ công).

**KHÔNG đưa secret/API key/connection string thật vào bất kỳ trường nào** — báo cáo có
thể được lưu vào git, gửi cho người khác. Nếu lệnh test cần secret, dùng placeholder
(`<YOUR_API_KEY>`) trong `command`.

### Bước 2 — Dựng JSON theo schema và chạy script

Viết 1 file JSON tạm (schema đầy đủ + ví dụ thật ở
`.claude/skills/task-report/scripts/report_schema.example.json`):

```json
{
  "task_id": "1.1",
  "task_title": "Tên ngắn của task",
  "source_task_file": ".claude/tasks/production-ops-gaps.md",
  "date": "2026-09-14",
  "summary": "...",
  "changed_files": [
    { "path": "backend/app/agents/generator.py", "change": "..." }
  ],
  "test_steps": [
    { "step": "...", "command": "...", "expected": "..." }
  ],
  "result": { "status": "pass", "notes": "..." },
  "rollback": "..."
}
```

Lưu JSON ra 1 file tạm (vd `report/.tmp/<slug>.json` — không cần giữ lại sau khi chạy
xong, chỉ là input cho script), rồi chạy:

```bash
uv run --with fpdf2 python .claude/skills/task-report/scripts/generate_report.py \
  --input <path-to-json> --out-dir report
```

`uv run --with fpdf2` tạo môi trường tạm chỉ để chạy script này — **KHÔNG** thêm `fpdf2`
vào `backend/pyproject.toml` hay `frontend/package.json` (script này là tooling nội bộ
của skill, không phải dependency sản phẩm; giữ đúng nguyên tắc dependency hygiene đã có ở
skill `enterprise-knowledge-rag` — tránh phình Docker image vì thêm lib không cần thiết
cho runtime backend). Lệnh này chạy được ở bất kỳ đâu trong repo miễn có `uv` trên PATH,
không cần đứng trong `backend/`.

Script tự động:
- Sinh tên file theo slug từ `date` + `task_id` + `task_title` (không dấu, viết thường,
  nối bằng `-`) — đảm bảo tên file không trùng giữa các task khác nhau.
- Xuất **cả 2 file cùng lúc**: `report/<slug>.pdf` và `report/<slug>.md` (nội dung khớp
  nhau, sinh từ cùng 1 JSON input).

### Bước 3 — Xác nhận & báo lại đường dẫn cho user

Sau khi script chạy xong (in ra đường dẫn `PDF:` / `Markdown:`), báo lại cho user 2 đường
dẫn đó. Xoá file JSON tạm ở Bước 2 nếu không cần giữ lại.

## Lưu ý khi viết nội dung báo cáo

- **Phần "Hướng dẫn test" phải tự đứng được** — người đọc báo cáo (có thể không phải
  người đã làm task) chỉ cần copy lệnh trong báo cáo, chạy đúng thứ tự, là verify được
  toàn bộ, không cần đọc lại code hoặc hỏi thêm.
- **Không tự bịa kết quả test** — chỉ điền `result.status = "pass"` nếu đã thực sự chạy
  test/lệnh đó và thấy đúng kỳ vọng trong session hiện tại. Nếu chưa chạy được (thiếu env,
  thiếu service), điền `"partial"` và ghi rõ trong `notes` phần nào chưa verify được.
- **1 báo cáo = 1 task** — nếu 1 session làm nhiều task cùng lúc (vd 3 task trong
  `production-ops-gaps.md`), chạy script 3 lần, ra 3 báo cáo riêng — không gộp chung 1 báo
  cáo cho nhiều task khác nhau, vì mất khả năng tra cứu/đối chiếu ngược lại từng task.
- Nếu task này lấp 1 gap đã ghi trong 1 skill khác (`prompt-engineering`, `rag-review`,
  `ingestion`...), sau khi có báo cáo, quay lại cập nhật skill đó (đổi "gap" thành "đã
  fix", trỏ tới báo cáo) — theo đúng quy ước đã có ở cuối `production-ops-gaps.md`.

## Giới hạn kỹ thuật cần biết

- **PDF hiển thị tiếng Việt có dấu đầy đủ** (đã fix 2026-09-16) — `generate_report.py`
  tự dò 1 font TTF Unicode có sẵn trên máy (Arial/Tahoma trên Windows, DejaVu Sans/
  Liberation Sans/Noto Sans trên Linux, Arial trên macOS — xem
  `_UNICODE_FONT_CANDIDATES`) và `add_font()` font đó cho toàn bộ PDF. KHÔNG bundle
  font binary vào repo (tránh commit file `.ttf` nặng, không phải text) — chỉ dùng
  font đã có sẵn trên máy đang chạy script.
- **Fallback (hiếm gặp):** nếu máy chạy script không có font nào trong danh sách (vd
  Linux CI tối giản không cài font), script tự in cảnh báo ra stderr và fallback về
  core font Helvetica/Courier (Latin-1 only) — khi đó dấu tiếng Việt bị thay bằng `?`
  (hàm `_latin1()`), giống hành vi cũ. Cách khắc phục: cài 1 font trong danh sách (vd
  `apt install fonts-dejavu` trên Debian/Ubuntu) hoặc đọc bản Markdown song song (luôn
  có dấu đầy đủ, không phụ thuộc font).
- Bản Markdown song song (`.md`) không bị giới hạn font — luôn hiển thị tiếng Việt có
  dấu đầy đủ bất kể máy chạy script có font Unicode hay không.
