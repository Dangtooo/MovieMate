import logging
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from threading import Lock
from time import monotonic

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from .auth import (
    COOKIE_NAME,
    DUMMY_HASH,
    current_user,
    password_hash,
    require_user,
    set_session,
    user_out,
)
from .config import ROOT, get_settings
from .db import Base, engine, get_db
from .models import Movie, Review, User, Watchlist
from .recommendations import recommend
from .ai import provider_status
from .queries import has_any_genre
from .schemas import ChatIn, LoginIn, RegisterIn, ReviewIn, WatchlistIn
from .tmdb import GENRES, save_movies, tmdb_get

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):
    # Initial schema creation for this course project; see README for migration policy.
    Base.metadata.create_all(engine)
    yield
    engine.dispose()


app = FastAPI(title="Cinéphile API", version="1.0.0", lifespan=lifespan)
_attempts = defaultdict(deque)
_limit_lock = Lock()


def rate_limit(request: Request, bucket: str, limit: int, seconds=60):
    key = (bucket, request.client.host if request.client else "unknown")
    now = monotonic()
    with _limit_lock:
        for old_key in list(_attempts):
            if not _attempts[old_key] or _attempts[old_key][-1] <= now - seconds:
                del _attempts[old_key]
        attempts = _attempts[key]
        while attempts and attempts[0] <= now - seconds:
            attempts.popleft()
        if len(attempts) >= limit:
            raise HTTPException(
                429,
                "Bạn thao tác quá nhanh. Hãy thử lại sau một phút.",
                headers={"Retry-After": str(seconds)},
            )
        attempts.append(now)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        allowed = [o.strip() for o in get_settings().allowed_origins.split(",")]
        if (origin and origin not in allowed) or request.headers.get(
            "sec-fetch-site"
        ) == "cross-site":
            return JSONResponse(
                {"detail": "Nguồn yêu cầu không được phép."}, status_code=403
            )
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' https://image.tmdb.org data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    if request.url.path in {"/docs", "/redoc", "/docs/oauth2-redirect"}:
        # FastAPI's generated documentation loads its UI bundle and inline bootstrap.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; img-src 'self' https://fastapi.tiangolo.com data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        )
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return JSONResponse(
        {
            "detail": "Dữ liệu chưa hợp lệ. Hãy kiểm tra các trường nhập.",
            "fields": [".".join(map(str, e["loc"][1:])) for e in exc.errors()],
        },
        status_code=422,
    )


@app.exception_handler(SQLAlchemyError)
async def database_error(request, exc):
    logger.exception("Database request failed")
    return JSONResponse(
        {"detail": "Không thể xử lý dữ liệu lúc này. Vui lòng thử lại."},
        status_code=503,
    )


def movie_out(movie: Movie, average=None, count=0, status=None):
    return {
        "tmdb_id": movie.tmdb_id,
        "title": movie.title,
        "original_title": movie.original_title,
        "overview": movie.overview,
        "poster_path": movie.poster_path,
        "backdrop_path": movie.backdrop_path,
        "release_date": movie.release_date,
        "runtime": movie.runtime,
        "genre_ids": movie.genre_ids,
        "genres": [GENRES[g] for g in movie.genre_ids if g in GENRES],
        "original_language": movie.original_language,
        "tmdb_rating": round(movie.tmdb_rating, 1),
        "community_rating": round(float(average), 1) if average is not None else None,
        "review_count": count,
        "watchlist_status": status,
    }


def movies_out(db, movies, user=None):
    ids = [m.tmdb_id for m in movies]
    if not ids:
        return []
    stats = {
        row[0]: (row[1], row[2])
        for row in db.execute(
            select(Review.movie_tmdb_id, func.avg(Review.rating), func.count())
            .where(Review.movie_tmdb_id.in_(ids))
            .group_by(Review.movie_tmdb_id)
        )
    }
    statuses = (
        dict(
            db.execute(
                select(Watchlist.movie_tmdb_id, Watchlist.status).where(
                    Watchlist.user_id == user.id, Watchlist.movie_tmdb_id.in_(ids)
                )
            ).all()
        )
        if user
        else {}
    )
    return [
        movie_out(m, *stats.get(m.tmdb_id, (None, 0)), statuses.get(m.tmdb_id))
        for m in movies
    ]


def get_movie(db, tmdb_id):
    if tmdb_id <= 0:
        raise HTTPException(404, "Không tìm thấy phim.")
    movie = db.get(Movie, tmdb_id)
    if movie is None and get_settings().tmdb_access_token:
        data = tmdb_get(f"movie/{tmdb_id}", append_to_response="credits,videos")
        if data.get("adult"):
            raise HTTPException(404, "Không tìm thấy phim.")
        save_movies(db, [data], details=True)
        movie = db.get(Movie, tmdb_id)
    if movie is None:
        raise HTTPException(404, "Không tìm thấy phim trong danh mục.")
    return movie


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    settings = get_settings()
    return {
        "status": "ok",
        "database": "sqlite",
        "tmdb_configured": bool(settings.tmdb_access_token),
        "gemini_configured": bool(settings.gemini_api_key),
        "ai_provider": settings.ai_provider,
        "catalog_count": db.scalar(select(func.count()).select_from(Movie)),
    }


@app.get("/api/ai/providers")
def ai_providers():
    return provider_status()


@app.post("/api/auth/register", status_code=201)
def register(
    payload: RegisterIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    rate_limit(request, "auth", 12)
    user = User(
        name=payload.name,
        email=str(payload.email).lower(),
        password_hash=password_hash.hash(payload.password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Email này đã được sử dụng.") from None
    set_session(response, user)
    return user_out(user)


@app.post("/api/auth/login")
def login(
    payload: LoginIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    rate_limit(request, "auth", 12)
    user = db.scalar(select(User).where(User.email == str(payload.email).lower()))
    valid = password_hash.verify(
        payload.password, user.password_hash if user else DUMMY_HASH
    )
    if not user or not valid:
        raise HTTPException(401, "Email hoặc mật khẩu không đúng.")
    set_session(response, user)
    return user_out(user)


@app.post("/api/auth/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")


@app.get("/api/auth/me")
def me(user: User | None = Depends(current_user)):
    return user_out(user) if user else None


@app.get("/api/genres")
def genres():
    return [{"id": k, "name": v} for k, v in GENRES.items()]


@app.get("/api/movies")
def list_movies(
    q: str = Query("", max_length=120),
    genre: int | None = None,
    year: int | None = Query(None, ge=1900, le=2100),
    sort: str = Query("popular", pattern="^(popular|rating|newest)$"),
    page: int = Query(1, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user),
):
    q = q.strip()
    if genre is not None and genre not in GENRES:
        raise HTTPException(422, "Thể loại không hợp lệ.")
    if q and genre:
        raise HTTPException(422, "Hãy bỏ bộ lọc thể loại khi tìm theo tên phim.")
    source, warning = "local", None
    if get_settings().tmdb_access_token:
        try:
            params = {"page": page, "include_adult": "false"}
            if q:
                params["query"] = q
                if year:
                    params["primary_release_year"] = year
                data = tmdb_get("search/movie", **params)
            else:
                params["sort_by"] = {
                    "popular": "popularity.desc",
                    "rating": "vote_average.desc",
                    "newest": "primary_release_date.desc",
                }[sort]
                params["vote_count.gte"] = 100 if sort == "rating" else 20
                params["primary_release_date.lte"] = (
                    datetime.now(timezone.utc).date().isoformat()
                )
                if genre:
                    params["with_genres"] = genre
                if year:
                    params["primary_release_year"] = year
                data = tmdb_get("discover/movie", **params)
            rows = [r for r in data.get("results", []) if not r.get("adult")]
            save_movies(db, rows)
            movies = [db.get(Movie, r["id"]) for r in rows]
            return {
                "items": movies_out(db, movies, user),
                "page": page,
                "total_pages": min(data.get("total_pages", 0), 500),
                "total": data.get("total_results", 0),
                "source": "tmdb",
                "warning": None,
            }
        except HTTPException:
            source, warning = (
                "cached",
                "TMDB đang không phản hồi. Đang hiển thị phim đã lưu.",
            )
    stmt = select(Movie)
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(
            Movie.title.ilike(f"%{escaped}%", escape="\\")
            | Movie.original_title.ilike(f"%{escaped}%", escape="\\")
        )
    if genre:
        stmt = stmt.where(has_any_genre([genre]))
    if year:
        stmt = stmt.where(func.extract("year", Movie.release_date) == year)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    order = {
        "popular": Movie.popularity.desc(),
        "rating": Movie.tmdb_rating.desc(),
        "newest": Movie.release_date.desc().nulls_last(),
    }[sort]
    movies = db.scalars(
        stmt.order_by(order, Movie.tmdb_id).offset((page - 1) * 20).limit(20)
    ).all()
    return {
        "items": movies_out(db, movies, user),
        "page": page,
        "total_pages": (total + 19) // 20,
        "total": total,
        "source": source,
        "warning": warning,
    }


@app.get("/api/movies/{tmdb_id}")
def movie_detail(
    tmdb_id: int,
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user),
):
    movie = get_movie(db, tmdb_id)
    warning = None
    stale = movie.details_fetched_at is None or movie.details_fetched_at < datetime.now(
        timezone.utc
    ) - timedelta(hours=24)
    if stale and get_settings().tmdb_access_token:
        try:
            data = tmdb_get(f"movie/{tmdb_id}", append_to_response="credits,videos")
            save_movies(db, [data], details=True)
            movie = db.get(Movie, tmdb_id)
        except HTTPException:
            warning = "Đang hiển thị thông tin đã lưu vì TMDB tạm thời không phản hồi."
    result = movies_out(db, [movie], user)[0]
    result.update(
        cast_names=movie.cast_names, trailer_key=movie.trailer_key, warning=warning
    )
    return result


def review_out(review, name):
    return {
        "id": review.id,
        "user_id": review.user_id,
        "author": name,
        "movie_tmdb_id": review.movie_tmdb_id,
        "rating": review.rating,
        "content": review.content,
        "contains_spoiler": review.contains_spoiler,
        "created_at": review.created_at,
        "updated_at": review.updated_at,
    }


@app.get("/api/movies/{tmdb_id}/reviews")
def list_reviews(
    tmdb_id: int, page: int = Query(1, ge=1), db: Session = Depends(get_db)
):
    get_movie(db, tmdb_id)
    condition = Review.movie_tmdb_id == tmdb_id
    total = db.scalar(select(func.count()).select_from(Review).where(condition))
    rows = db.execute(
        select(Review, User.name)
        .join(User)
        .where(condition)
        .order_by(Review.created_at.desc())
        .offset((page - 1) * 10)
        .limit(10)
    ).all()
    return {
        "items": [review_out(r, name) for r, name in rows],
        "page": page,
        "total": total,
        "total_pages": (total + 9) // 10,
    }


@app.put("/api/movies/{tmdb_id}/reviews/me")
def write_review(
    tmdb_id: int,
    payload: ReviewIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    from sqlalchemy.dialects.sqlite import insert

    get_movie(db, tmdb_id)
    values = payload.model_dump()
    stmt = insert(Review).values(user_id=user.id, movie_tmdb_id=tmdb_id, **values)
    db.execute(
        stmt.on_conflict_do_update(
            index_elements=[Review.user_id, Review.movie_tmdb_id],
            set_={**values, "updated_at": datetime.now(timezone.utc)},
        )
    )
    db.commit()
    review = db.scalar(
        select(Review).where(Review.user_id == user.id, Review.movie_tmdb_id == tmdb_id)
    )
    return review_out(review, user.name)


@app.get("/api/movies/{tmdb_id}/reviews/me")
def my_review(
    tmdb_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    review = db.scalar(
        select(Review).where(Review.user_id == user.id, Review.movie_tmdb_id == tmdb_id)
    )
    return review_out(review, user.name) if review else None


@app.delete("/api/movies/{tmdb_id}/reviews/me", status_code=204)
def delete_review(
    tmdb_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    db.execute(
        delete(Review).where(Review.user_id == user.id, Review.movie_tmdb_id == tmdb_id)
    )
    db.commit()


@app.get("/api/watchlist")
def watchlist(
    page: int = Query(1, ge=1),
    status: str = Query("all", pattern="^(all|want_to_watch|watched)$"),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    stmt = (
        select(Movie)
        .join(Watchlist, Movie.tmdb_id == Watchlist.movie_tmdb_id)
        .where(Watchlist.user_id == user.id)
    )
    if status != "all":
        stmt = stmt.where(Watchlist.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    movies = db.scalars(
        stmt.order_by(Watchlist.created_at.desc()).offset((page - 1) * 20).limit(20)
    ).all()
    return {
        "items": movies_out(db, movies, user),
        "page": page,
        "total": total,
        "total_pages": (total + 19) // 20,
        "source": "watchlist",
    }


@app.put("/api/watchlist/{tmdb_id}")
def save_watchlist(
    tmdb_id: int,
    payload: WatchlistIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    from sqlalchemy.dialects.sqlite import insert

    get_movie(db, tmdb_id)
    stmt = insert(Watchlist).values(
        user_id=user.id, movie_tmdb_id=tmdb_id, status=payload.status
    )
    db.execute(
        stmt.on_conflict_do_update(
            index_elements=[Watchlist.user_id, Watchlist.movie_tmdb_id],
            set_={"status": payload.status},
        )
    )
    db.commit()
    return {"tmdb_id": tmdb_id, "status": payload.status}


@app.delete("/api/watchlist/{tmdb_id}", status_code=204)
def remove_watchlist(
    tmdb_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    db.execute(
        delete(Watchlist).where(
            Watchlist.user_id == user.id, Watchlist.movie_tmdb_id == tmdb_id
        )
    )
    db.commit()


@app.post("/api/chat")
def chat(
    payload: ChatIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user),
):
    rate_limit(request, "chat", 10)
    movies, result = recommend(db, payload, user.id if user else None)
    result["movies"] = movies_out(db, movies, user)
    for movie in result["movies"]:
        bits = [
            g
            for g in movie["genres"]
            if g in [GENRES.get(i) for i in result["preferences"]["genre_ids"]]
        ]
        if movie["runtime"]:
            bits.append(f"{movie['runtime']} phút")
        bits.append(f"TMDB {movie['tmdb_rating']}/10")
        movie["reason"] = " · ".join(bits)
    return result


app.mount("/static", StaticFiles(directory=ROOT / "frontend"), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(ROOT / "frontend" / "index.html")
