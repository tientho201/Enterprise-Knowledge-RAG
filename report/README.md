# report/

Báo cáo kết quả từng task — sinh tự động bởi skill `task-report`
(`.claude/skills/task-report/SKILL.md`). Mỗi task hoàn thành có 1 cặp file cùng tên:

```
report/<YYYY-MM-DD>-<task-id>-<slug-tên-task>.pdf   ← báo cáo để đọc/gửi người khác
report/<YYYY-MM-DD>-<task-id>-<slug-tên-task>.md    ← bản Markdown song song, dễ diff/search
```

Không sửa tay file trong thư mục này — nếu cần cập nhật báo cáo của 1 task, chạy lại
script sinh báo cáo (xem skill `task-report`) để 2 file PDF/MD luôn khớp nhau.
