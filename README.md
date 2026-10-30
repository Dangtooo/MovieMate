# Cinéphile — Review phim và chatbot recommendation

**FastAPI + SQLite + HTML/CSS/JavaScript thuần**, dành cho môn Web Design and Programming. Không cần PostgreSQL, Docker hay build frontend. `movies.tmdb_id` vẫn là khóa chính duy nhất của phim; review và watchlist tham chiếu trực tiếp mã này.

## Chạy website

Yêu cầu Python 3.12+. Tại thư mục dự án:

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

Mở **http://127.0.0.1:8000**, tài liệu API **http://127.0.0.1:8000/docs**. Dừng web bằng `Ctrl+C`.

Script tạo môi trường Python nếu thiếu, cài dependencies đã khóa phiên bản, tạo `.env` với khóa phiên ngẫu nhiên nếu chưa có, tạo bảng và thêm 24 phim mẫu mà không ghi đè dữ liệu. Database là **`data/cinephile.db`**; không cần chạy một dịch vụ database riêng. Đường dẫn tương đối trong `DATABASE_URL` được tính từ thư mục dự án.

Chạy thủ công:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe scripts/setup_env.py
.\.venv\Scripts\python.exe -m backend.demo_catalog
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload
```

## Chọn model trong khung chat

Mở **Ciné bot → Chọn model**:

| Lựa chọn | Cách hoạt động |
| --- | --- |
| Tự động | Theo `AI_PROVIDER` trong `.env`; nếu là `auto` thì ưu tiên Gemini khi có key, nếu không thì thử Ollama |
| Qwen · Local | Chỉ gọi Ollama theo cấu hình backend; không chuyển hội thoại sang Gemini khi lỗi |
| Gemini · API | Gọi Gemini với API key ở backend |
| Bộ lọc từ khóa | Không dùng AI, lọc các yêu cầu tiếng Việt cơ bản |

Model bị lỗi, chưa tải, hết thời gian hoặc trả JSON không hợp lệ thì dùng bộ lọc và **hiển thị rõ lý do**, không giả vờ đã chạy AI. Đổi model sẽ bắt đầu hội thoại mới. Nhấn **↺ cạnh bộ chọn model** để kiểm tra lại kết nối sau khi mở Ollama hoặc tải model.

## Qwen chạy local qua Ollama

1. Cài [Ollama cho Windows](https://ollama.com/download/windows) và mở ứng dụng Ollama.
2. Mở terminal mới, tải model:

```powershell
ollama pull qwen3:1.7b
```

3. Nếu Ollama chưa tự chạy nền, mở một terminal riêng:

```powershell
ollama serve
```

4. Chạy web bằng `run.ps1`, chọn **Qwen · Local** trong khung chat. Không cần API key cho Qwen.

Cấu hình `.env`:

```dotenv
DATABASE_URL=sqlite:///./data/cinephile.db
AI_PROVIDER=auto
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3:1.7b
OLLAMA_TIMEOUT=120
```

Muốn mặc định chọn Qwen khi mở trang: đặt `AI_PROVIDER=ollama`. Có thể thay bằng model Qwen khác đã tải, ví dụ `OLLAMA_MODEL=qwen3:4b`; tải đúng model bằng `ollama pull` trước. Máy chậm có thể tăng `OLLAMA_TIMEOUT` (giây). Tốc độ/RAM phụ thuộc model, ngữ cảnh và phần cứng; bản 1.7B là lựa chọn bắt đầu.

Backend dùng Ollama `/api/chat`, JSON schema, `stream=false`, `think=false`, giới hạn đầu ra/ngữ cảnh. Qwen chỉ phân tích tiêu chí; backend chọn phim thật từ SQLite và loại phim người dùng đã xem. Model không tự tạo tên phim trả về. [Ollama Chat API](https://docs.ollama.com/api/chat), [structured outputs](https://docs.ollama.com/capabilities/structured-outputs).

Lần tải model đầu tiên cần Internet và dung lượng đĩa. Sau khi tải, có thể gợi ý từ danh mục SQLite bằng Qwen mà không gọi AI cloud. Poster và kho phim TMDB vẫn cần Internet nếu sử dụng.

**Giới hạn kiểm tra trên máy hiện tại:** chưa cài/chạy Ollama nên chưa kiểm tra suy luận Qwen thật. Adapter/schema/phân tuyến Qwen được kiểm tra bằng phản hồi mô phỏng; trạng thái mất kết nối và fallback được kiểm tra qua trình duyệt thật.

## TMDB và Gemini

Điền trong `.env`, khởi động lại web sau khi sửa:

```dotenv
TMDB_ACCESS_TOKEN=your_tmdb_api_read_access_token
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-3.5-flash-lite
```

- TMDB: dùng **API Read Access Token**, không phải v3 API key. Lấy tại [cài đặt TMDB API](https://www.themoviedb.org/settings/api).
- Gemini: lấy key tại [Google AI Studio](https://aistudio.google.com/apikey). Có thể đổi model theo quyền truy cập tài khoản.
- Key chỉ ở backend. Không đưa `.env`, database hoặc cấu hình sao lưu lên Git.
- Chưa có TMDB key: dùng 24 phim mẫu; thông tin/điểm/ngày phát hành là dữ liệu demo. Có key: tìm kiếm kho TMDB và lưu metadata về SQLite. Không tải video phim.
- TMDB list cache trong RAM 5 phút; chi tiết cập nhật sau 24 giờ khi mở lại. List không gọi chi tiết cho từng thẻ; chatbot chỉ lấy một số ứng viên khi cần biết thời lượng.
- TMDB lỗi: trả danh mục đã lưu cùng thông báo. Ảnh có placeholder nếu tải lỗi.

## Dữ liệu cũ khi đổi từ PostgreSQL

Trong workspace này, **24 phim và 1 tài khoản đã chuyển sang SQLite**, giữ nguyên ID, email và password hash. Database cũ vẫn được giữ trong `.local/postgres`, cấu hình cũ ở `.local/.env.before-sqlite`, kết quả chuyển ở `.local/sqlite-migration.json`. Ứng dụng hiện không kết nối PostgreSQL.

`setup_env.py` tự đổi `DATABASE_URL` PostgreSQL cũ sang SQLite và sao lưu `.env`, không xóa dữ liệu cũ. Nếu áp dụng cập nhật cho một bản cài khác có dữ liệu PostgreSQL, cần chuyển trước khi sử dụng SQLite mới:

```powershell
# Chỉ dành cho chuyển dữ liệu cũ: database nguồn phải đang chạy.
.\.venv\Scripts\python.exe -m pip install "psycopg[binary]"
.\.venv\Scripts\python.exe scripts/migrate_to_sqlite.py
```

Script sao chép bằng một transaction, không thay đổi nguồn, từ chối gộp nếu SQLite đã có dữ liệu và không chạy lại khi có marker hoàn tất. Bản cài mới không cần bước này. `psycopg` không còn là dependency ứng dụng.

## Chức năng và schema

- Tìm/lọc/sắp xếp/phân trang phim; xem chi tiết, diễn viên, trailer nếu có.
- Đăng ký/đăng nhập; password Argon2, cookie JWT HttpOnly; giữ phiên sau reload.
- Mỗi người một review/phim: tạo/sửa/xóa, chấm 1–10, che spoiler, phân trang.
- Điểm cộng đồng tính từ review thật, hiển thị riêng với điểm TMDB.
- Tủ phim muốn xem/đã xem, bỏ lưu, lọc và phân trang.
- Chat giữ tối đa 6 lượt ngữ cảnh, chọn Gemini/Qwen/bộ lọc, tránh phim đã xem.

```text
movies: tmdb_id PK, title, original_title, overview, poster_path, backdrop_path,
        release_date, runtime, genre_ids JSON, original_language, tmdb_rating,
        popularity, cast_names JSON, trailer_key, updated_at, details_fetched_at
users: id PK, name, email UNIQUE, password_hash, created_at
reviews: id PK, user_id FK, movie_tmdb_id FK → movies.tmdb_id,
         rating CHECK 1..10, content, contains_spoiler, created_at, updated_at,
         UNIQUE(user_id, movie_tmdb_id)
watchlists: user_id FK, movie_tmdb_id FK → movies.tmdb_id,
            status CHECK ('want_to_watch', 'watched'), created_at,
            PRIMARY KEY(user_id, movie_tmdb_id)
```

SQLite bật foreign keys, WAL và busy timeout. Thời gian lưu UTC, trả API kèm múi giờ UTC. Thể loại lọc bằng `json_each` để so khớp số chính xác. Xóa tài khoản cascade review/watchlist. Sao lưu database khi web đã dừng; khi đang chạy dùng công cụ SQLite backup để có bản sao nhất quán với WAL.

## Mã nguồn và kiểm tra

`backend/main.py`: API/phân quyền. `models.py`/`db.py`: schema/SQLite. `ai.py`: adapter Gemini/Ollama, trạng thái model. `recommendations.py`: lọc gợi ý. `tmdb.py`: TMDB và upsert SQLite. `frontend/`: HTML/CSS/JS. `scripts/setup_env.py`: cấu hình ban đầu. `/api/ai/providers`: trạng thái provider, không lộ key. Các API khác xem `/docs`.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --check frontend/app.js
```

Tests dùng SQLite tạm riêng, rollback sau mỗi bài; không xóa dữ liệu app. Kiểm tra khóa ngoại/cascade, JSON genres, UTC, quyền review, watchlist, schema Qwen, history, lỗi model và việc Qwen không chuyển sang cloud.

Kiểm tra trình duyệt tùy chọn (Node.js, web đang chạy với danh mục mẫu):

```powershell
npm install --prefix .local/browser-tests playwright
.\.local\browser-tests\node_modules\.bin\playwright.cmd install chromium
node scripts/browser_smoke.cjs
```

Kiểm tra auth/review/watchlist, spoiler/escape HTML, chọn model/request Ollama/fallback, desktop/mobile, Swagger. Tài khoản QA duy nhất được xóa ở cuối; ảnh ở `.local/screenshots`. Dùng `CINEPHILE_TEST_URL` để chọn port khác, đồng thời cấu hình `ALLOWED_ORIGINS` cho server kiểm tra.

## Phạm vi đồ án

Frontend phục vụ cùng FastAPI, không mở `index.html` bằng `file://`. Đổi host/port cần cập nhật `ALLOWED_ORIGINS`. `create_all` chỉ tạo bảng, không sửa schema đã có; đổi schema sau này cần migration. Chưa có xác minh email/quên mật khẩu/kiểm duyệt review. Triển khai Internet cần HTTPS, `COOKIE_SECURE=true`, `SECRET_KEY` riêng; rate limit/cache RAM cần bộ nhớ dùng chung nếu chạy nhiều worker. JWT đã đăng xuất chưa có thu hồi phía server.

Nguồn dữ liệu/ảnh: [TMDB](https://www.themoviedb.org/). Website có logo và ghi nguồn ở footer theo [yêu cầu sử dụng](https://developer.themoviedb.org/docs/faq). Gemini/TMDB thật cần key hợp lệ để kiểm tra kết nối thực tế.
