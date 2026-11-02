from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class RegisterIn(LoginIn):
    name: str = Field(min_length=2, max_length=60)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Tên cần ít nhất 2 ký tự.")
        return value


class ReviewIn(BaseModel):
    rating: int = Field(ge=1, le=10, strict=True)
    content: str = Field(min_length=10, max_length=3000)
    contains_spoiler: bool = False

    @field_validator("content")
    @classmethod
    def clean_content(cls, value):
        value = value.strip()
        if len(value) < 10:
            raise ValueError("Review cần ít nhất 10 ký tự.")
        return value


class WatchlistIn(BaseModel):
    status: Literal["want_to_watch", "watched"] = "want_to_watch"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    session_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    provider: Literal["auto", "gemini"] = "auto"
    selected_movie_id: int | None = Field(default=None, gt=0)

    @field_validator("message")
    @classmethod
    def clean_message(cls, value):
        if not value.strip():
            raise ValueError("Hãy nhập yêu cầu chọn phim.")
        return value.strip()


class ChatMovieCard(BaseModel):
    id: int
    title: str
    release_year: str
    rating: float
    poster_url: str | None
    trailer_url: str | None = None
    reason: str


class ChatResponse(BaseModel):
    reply: str
    movies: list[ChatMovieCard]
