from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, Response
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import User

password_hash = PasswordHash.recommended()
DUMMY_HASH = password_hash.hash("unused-dummy-password")
COOKIE_NAME = "cine_session"


def current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        payload = jwt.decode(
            token,
            get_settings().secret_key,
            algorithms=["HS256"],
            options={"require": ["exp", "sub"]},
        )
        return db.get(User, int(payload["sub"]))
    except (jwt.PyJWTError, ValueError, TypeError):
        return None


def require_user(user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise HTTPException(401, "Bạn cần đăng nhập để thực hiện thao tác này.")
    return user


def set_session(response: Response, user: User):
    token = jwt.encode(
        {"sub": str(user.id), "exp": datetime.now(timezone.utc) + timedelta(days=7)},
        get_settings().secret_key,
        algorithm="HS256",
    )
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=604800,
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
        path="/",
    )


def user_out(user: User):
    return {"id": user.id, "name": user.name, "email": user.email}
