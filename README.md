# MovieMate — Review phim và chatbot recommendation

**FastAPI + SQLite + HTML/CSS/JavaScript thuần**, dành cho môn Web Design and Programming. Không cần PostgreSQL, Docker hay build frontend. `movies.tmdb_id` vẫn là khóa chính duy nhất của phim; review và watchlist tham chiếu trực tiếp mã này.

## Chạy website

Yêu cầu Python 3.12+ và Internet để cài thư viện lần đầu. Mở terminal tại **thư mục chứa `README.md`, `backend/` và `requirements.lock.txt`** (trong workspace hiện tại là `D:\MovieMate\MovieMate`).

### Windows (PowerShell hoặc CMD)

Chạy lệnh sau, hoặc nhấp đúp vào `start.bat` trong File Explorer:

```powershell
.\start.bat
```

Nếu bản tải về chưa có `start.bat`, chạy trực tiếp script PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

Mở **http://127.0.0.1:8000**, tài liệu API **http://127.0.0.1:8000/docs**. Dừng web bằng `Ctrl+C`.

Script tạo môi trường Python nếu thiếu, cài dependencies đã khóa phiên bản và tự cập nhật môi trường khi `requirements.lock.txt` thay đổi (kể cả khi `.venv` đã tồn tại). Lần cập nhật thư viện cần Internet. Script cũng tạo `.env` với khóa phiên ngẫu nhiên nếu chưa có, tạo bảng và thêm 24 phim mẫu mà không ghi đè dữ liệu. Database là **`data/moviemate.db`**; không cần chạy một dịch vụ database riêng. Đường dẫn tương đối trong `DATABASE_URL` được tính từ thư mục dự án.

Chạy thủ công trên Windows nếu cần:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe scripts/setup_env.py
.\.venv\Scripts\python.exe -m backend.demo_catalog
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload
```

### macOS và Linux (Terminal: bash hoặc zsh)

Kiểm tra `python3 --version` là **3.12 trở lên**. Nếu máy dùng tên lệnh như `python3.12`, thay `python3` ở lệnh tạo môi trường bằng tên đó. Lần đầu chạy lần lượt:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.lock.txt
./.venv/bin/python scripts/setup_env.py
./.venv/bin/python -m backend.demo_catalog
./.venv/bin/python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000 --reload-dir backend --reload-dir frontend
```

Những lần sau chỉ cần mở terminal tại thư mục dự án và chạy:

```bash
./.venv/bin/python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000 --reload-dir backend --reload-dir frontend
```

Nếu Ubuntu/Debian báo thiếu `venv` hoặc `ensurepip`, cài gói `venv` tương ứng với phiên bản Python đang dùng rồi tạo lại môi trường. Ví dụ với Python mặc định của hệ điều hành:

```bash
sudo apt update
sudo apt install python3-venv
```

Các lệnh trên gọi Python trong `.venv` trực tiếp, không cần kích hoạt môi trường. Khi chuyển project giữa Windows và macOS/Linux, tạo `.venv` riêng trên mỗi máy; không sao chép môi trường từ hệ điều hành khác. Website và tài liệu API dùng cùng địa chỉ ở trên, dừng bằng `Ctrl+C`.

## Chatbot Google ADK + Gemini + TMDB

Chatbot có đúng ba file:

- `backend/chat_service.py`: phiên hội thoại theo người dùng/cookie, giới hạn bộ nhớ, gọi agent và kiểm tra thẻ phim trả về.
- `backend/chat_agent.py`: Google ADK `Agent` + `Runner`, prompt tiếng Việt, lịch sử và vòng gọi function tools. Không dùng sub-agent.
- `backend/chat_tools.py`: tìm tên phim, discover với bộ lọc, diễn viên/đạo diễn, phim tương tự, danh sách rạp/thịnh hành, chi tiết/trailer/nơi xem và xếp hạng.

Các câu hỏi thường gặp và tool được dùng:

| Ví dụ người dùng hỏi | Tool |
| --- | --- |
| “Tìm phim tên Incantation” | `search_movies` |
| “Phim giống Incantation?” | `find_similar_movies` (tìm phim gốc + phim liên quan trong một lần gọi tool) |
| “Nolan là ai / 5 phim ông ấy đạo diễn?” | `person_information` |
| “Phim có cả Tom Hanks và Meg Ryan?” | `discover_movies` với nhiều tên diễn viên |
| “Phim hài Nhật dưới 2 giờ từ 2020?” | `discover_movies` với bộ lọc |
| “Phim nào trên Netflix Việt Nam?” | `discover_movies` với `watch_provider`, `watch_country` |
| “Thể loại phim nào có thể lọc?” | `list_genres` |
| “Đang chiếu / sắp chiếu / thịnh hành?” | `movie_lists` |
| “Nội dung, diễn viên, thời lượng, trailer?” | `movie_details` |
| “Phim đó xem ở đâu / thuê hay mua?” | `watch_providers` |
| “John Wick có mấy phần, thứ tự xem?” | `movie_collection` (thứ tự phát hành, không tự đoán dòng thời gian cốt truyện) |
| “So sánh hai phim / phim nào ngắn hơn?” | `compare_movies`, `rank_candidates` |

Phim/người trùng tên sẽ yêu cầu làm rõ. Không có dữ liệu giải thưởng, lịch suất chiếu theo rạp hay cảnh báo nội dung chi tiết thì chatbot phải nói rõ giới hạn. Kết quả cuối qua `finish_answer`, kiểm tra ID trước khi trả thẻ phim.

Terminal chạy Uvicorn mặc định in log tool (không cần bật debug):

```text
INFO: [chat:a1b2c3d4] TOOL START person_information args={"name": "Christopher Nolan", "role": "director"}
INFO: [chat:a1b2c3d4] TOOL DONE person_information duration=0.83s movies=8
INFO: [chat:a1b2c3d4] TOOL START finish_answer args={"movie_ids": [155, 27205]}
INFO: [chat:a1b2c3d4] TOOL DONE finish_answer duration=0.00s movies=0
```

`chat:...` nối các dòng thuộc cùng câu hỏi. `TOOL ERROR` cho biết lỗi công cụ. Tham số phim được ghi tối đa 800 ký tự; không ghi key/token hoặc toàn bộ câu trả lời. `movies=0` của `finish_answer` là phản hồi trạng thái, ID hiển thị ở dòng START. Không dùng `--log-level warning` nếu muốn xem log tool.

Điền `.env`, khởi động lại server sau khi sửa:

```dotenv
TMDB_ACCESS_TOKEN=your_tmdb_api_read_access_token
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-3.5-flash-lite
AI_PROVIDER=gemini
```

Gemini model phải có sẵn trong tài khoản; có thể đổi `GEMINI_MODEL`. Key chỉ ở backend. Cài lại thư viện khi cập nhật: `python -m pip install -r requirements.lock.txt`.

Ví dụ: “Phim hài Nhật dưới 2 tiếng từ 2020”, “Phim của Christopher Nolan có Cillian Murphy”, “Tìm phim giống Interstellar”, “Phim nào ngắn nhất trong số đó?”, “Trailer và nơi xem phim đó tại Việt Nam”, “Phim đang chiếu”. Các câu hỏi chung về thuật ngữ/thể loại điện ảnh có thể được giải thích trực tiếp. Dữ liệu không có trên TMDB (lịch suất chiếu, tin tức, giải thưởng...) sẽ được thông báo giới hạn.

Công cụ lấy phim trực tiếp qua TMDB, lưu metadata về SQLite để mở chi tiết và thêm vào tủ phim. Gợi ý loại phim người dùng đã đánh dấu đã xem. ID/thẻ phim phải có trong dữ liệu tra cứu. Rating xếp theo điểm Bayesian đơn giản `(votes * rating + 100 * 6) / (votes + 100)` để giảm ảnh hưởng phim ít lượt chấm; thẻ vẫn hiển thị điểm TMDB gốc. Có thêm sắp xếp ngày phát hành, độ phổ biến và thời lượng. Kết quả là xếp hạng trong tập ứng viên API trả về, không phải toàn bộ kho TMDB.

Thiếu key hoặc Gemini lỗi trả thông báo rõ; không tự chuyển sang bộ lọc hay Ollama. Phiên lưu RAM tối đa một giờ, 500 phiên tổng và 8 phiên mỗi chủ sở hữu; restart server sẽ mất lịch sử. Mỗi câu hỏi tối đa 8 lượt gọi model và 30 lượt tra cứu TMDB, timeout vòng ADK 120 giây (lệnh HTTP đồng bộ đang chạy kết thúc theo timeout TMDB riêng). Dùng một server worker cho bản demo.

Nguồn: [Google ADK function tools](https://google.github.io/adk-docs/tools-custom/function-tools/), [TMDB discover](https://developer.themoviedb.org/reference/discover-movie), [TMDB API token](https://www.themoviedb.org/settings/api), [Gemini API key](https://aistudio.google.com/apikey).

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
- Chat giữ tối đa 8 cặp hỏi/đáp, dùng Gemini qua Google ADK, tránh gợi ý phim đã xem.

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

`backend/main.py`: API/phân quyền. `models.py`/`db.py`: schema/SQLite. `chat_service.py`/`chat_agent.py`/`chat_tools.py`: chatbot Google ADK. `tmdb.py`: TMDB và upsert SQLite. `frontend/`: HTML/CSS/JS. `scripts/setup_env.py`: cấu hình ban đầu. `/api/ai/providers`: trạng thái provider, không lộ key. Các API khác xem `/docs`.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --check frontend/app.js
```

Tests dùng SQLite tạm riêng, rollback sau mỗi bài; không xóa dữ liệu app. Kiểm tra khóa ngoại/cascade, JSON genres, UTC, quyền review, watchlist, vòng gọi công cụ ADK, lịch sử/phiên riêng, xếp hạng, lọc TMDB và lỗi model.

Bộ test bổ sung kiểm tra ADK Runner thật với `BaseLlm` giả lập, giới hạn lượt gọi model, sửa đối số tool, đóng client khi lỗi, cookie bị sửa, hết hạn/giới hạn phiên và luồng FastAPI → agent → tool → SQLite. Các HTTP transport thật bị chặn trong test để không gọi Gemini/TMDB ngoài mạng.

Để cài công cụ đo coverage và chạy:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest --cov=backend --cov-report=term-missing
```

Xem [hướng dẫn và phạm vi từng file test](tests/README.md). Coverage đo các dòng code đã chạy, không phải độ chính xác gợi ý của AI.

Kiểm tra trình duyệt tùy chọn (Node.js, web đang chạy với danh mục mẫu):

```powershell
npm install --prefix .local/browser-tests playwright
.\.local\browser-tests\node_modules\.bin\playwright.cmd install chromium
node scripts/browser_smoke.cjs
```

Kiểm tra auth/review/watchlist, spoiler/escape HTML, hiển thị thẻ chat bằng phản hồi mô phỏng, desktop/mobile, Swagger. Tài khoản QA duy nhất được xóa ở cuối; ảnh ở `.local/screenshots`. Dùng `MOVIEMATE_TEST_URL` để chọn port khác, đồng thời cấu hình `ALLOWED_ORIGINS` cho server kiểm tra.

## Phạm vi đồ án

Frontend phục vụ cùng FastAPI, không mở `index.html` bằng `file://`. Đổi host/port cần cập nhật `ALLOWED_ORIGINS`. `create_all` chỉ tạo bảng, không sửa schema đã có; đổi schema sau này cần migration. Chưa có xác minh email/quên mật khẩu/kiểm duyệt review. Triển khai Internet cần HTTPS, `COOKIE_SECURE=true`, `SECRET_KEY` riêng; rate limit/cache RAM cần bộ nhớ dùng chung nếu chạy nhiều worker. JWT đã đăng xuất chưa có thu hồi phía server.

Nguồn dữ liệu/ảnh: [TMDB](https://www.themoviedb.org/). Website có logo và ghi nguồn ở footer theo [yêu cầu sử dụng](https://developer.themoviedb.org/docs/faq). Gemini/TMDB thật cần key hợp lệ để kiểm tra kết nối thực tế.
