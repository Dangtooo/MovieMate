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


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=1500)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=6)
    provider: Literal["auto", "gemini", "ollama", "rules"] = "auto"

    @field_validator("message")
    @classmethod
    def clean_message(cls, value):
        if not value.strip():
            raise ValueError("Hãy nhập yêu cầu chọn phim.")
        return value.strip()


class Preferences(BaseModel):
    genre_ids: list[int] = Field(default_factory=list, max_length=5)
    excluded_genre_ids: list[int] = Field(default_factory=list, max_length=5)
    max_runtime: int | None = Field(default=None, ge=1, le=600)
    min_year: int | None = Field(default=None, ge=1900, le=2100)
    max_year: int | None = Field(default=None, ge=1900, le=2100)
    language: str | None = Field(default=None, pattern=r"^[a-z]{2}$")
    intro: str = Field(
        default="Đây là những phim phù hợp với yêu cầu của bạn.", max_length=500
    )
