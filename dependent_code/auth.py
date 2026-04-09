"""
JWT 認證模組
- create_token()：登入成功後產生 JWT token
- verify_token()：FastAPI Depends，驗證 Authorization header
"""

import datetime
import logging
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from config import JWT_SECRET_KEY, JWT_ALGORITHM, JWT_EXPIRE_MINUTES

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# FastAPI 自動在 Swagger UI 加上 Authorization 輸入框
_bearer_scheme = HTTPBearer()

# 簡易使用者清單（未來可改為 DB 查詢）
# 密碼用 hash 儲存更安全，這裡為了教學先用明文
_USERS = {
    "admin": {"password": "admin123",   "role": "admin"},
    "viewer": {"password": "viewer123", "role": "viewer"},
}


def create_token(username: str, role: str) -> str:
    """產生 JWT token，包含 username、role、過期時間"""
    expire = datetime.datetime.utcnow() + datetime.timedelta(minutes=JWT_EXPIRE_MINUTES)
    payload = {
        "sub":  username,
        "role": role,
        "exp":  expire,
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> dict:
    """
    FastAPI Depends：驗證 JWT token，回傳 payload dict。
    使用方式：
        @app.get("/protected")
        def protected(user: dict = Depends(verify_token)):
            return {"msg": f"hello {user['sub']}"}
    """
    # _bearer_scheme（HTTPBearer）已先從 Authorization header 拆出 token 字串
    # credentials.scheme      → "Bearer"
    # credentials.credentials → "eyJhbGci..."（token 本體）
    token = credentials.credentials

    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])

        return payload

    except JWTError:
        # JWTError 涵蓋所有失敗：簽名錯誤、token 過期、格式損壞
        # WWW-Authenticate header 是 OAuth 2.0 標準，告知 client 應用 Bearer scheme
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def authenticate_user(username: str, password: str) -> dict:
    """驗證帳密，成功回傳 user dict，失敗 raise HTTPException"""
    user = _USERS.get(username)
    if not user or user["password"] != password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    return {"username": username, "role": user["role"]}
