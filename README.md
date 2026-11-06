# MovieMate

Website review phim và chatbot gợi ý phim, dùng FastAPI, SQLite, Google ADK và HTML/CSS/JavaScript.

**Dùng trực tiếp:** https://moviemate-i3nr.onrender.com/

## Chạy bằng Docker

1. Cài và mở Docker Desktop (Linux containers).
2. Tạo `.env` từ `.env.example` nếu chưa có. Điền `SECRET_KEY` riêng (ít nhất 32 ký tự, thay giá trị mẫu), `TMDB_ACCESS_TOKEN`, `GEMINI_API_KEY` và `GEMINI_MODEL` phù hợp.
3. Chạy tại thư mục dự án:

```bash
docker compose up --build -d
```

Mở http://localhost:8000. Dừng ứng dụng:

```bash
docker compose down
```

Database được lưu trong Docker volume; không dùng `down -v` nếu muốn giữ dữ liệu.
