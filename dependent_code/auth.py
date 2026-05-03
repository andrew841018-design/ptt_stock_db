"""
JWT 認證模組
- create_token()：登入成功後產生 JWT token
- verify_token()：FastAPI Depends，驗證 Authorization header

安全設計：
- 密碼用 **bcrypt hash** 儲存（passlib），不存明文
- 密碼 hash 從環境變數 ADMIN_PW_HASH / VIEWER_PW_HASH 讀入
- 金鑰產生：`python cli.py gen-jwt-secret` / `python cli.py gen-pw-hash <username> <password>`
"""

import os
import datetime
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext

from config import JWT_SECRET_KEY, JWT_ALGORITHM, JWT_EXPIRE_MINUTES

# FastAPI 自動在 Swagger UI 加上 Authorization 輸入框
_bearer_scheme = HTTPBearer()

# passlib context — bcrypt 是業界標準，slow-hash 防 brute force
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# timing-safe dummy：username 不存在時仍跑一次 bcrypt.verify，防止 timing attack 推測帳號列表
_TIMING_DUMMY_HASH = "$2b$12$C.kB9zgc/KQHoPGPFRJJNOxXNOSRPl15HrOeUf5/ivW98bQDRHYQK"

# 簡易使用者清單（未來可改為 DB 查詢）
_USERS = {
    "admin":  {"pw_hash": os.environ.get("ADMIN_PW_HASH"),  "role": "admin"},
    "viewer": {"pw_hash": os.environ.get("VIEWER_PW_HASH"), "role": "viewer"},
}


def create_token(username: str, role: str) -> str:
    """產生 JWT token，包含 username、role、過期時間（timezone-aware UTC）"""
    # datetime.utcnow() 在 Python 3.12+ deprecated；改用 timezone-aware
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=JWT_EXPIRE_MINUTES)
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
    """
    驗證帳密（constant-time bcrypt verify），成功回傳 user dict，失敗 raise HTTPException。

    使用 passlib `verify()`：
      - 即使 user 不存在也跑一次 dummy verify（常數時間），防止 timing attack 推測 user 列表
      - bcrypt 本身 slow-hash，每次驗證 ~100ms，防 brute-force
    """
    user = _USERS.get(username)
    # timing-safe：即使 username 不存在、或 pw_hash env var 未設定也跑一次 verify
    stored_hash = (user["pw_hash"] if user else None) or _TIMING_DUMMY_HASH
    valid = _pwd_context.verify(password, stored_hash)

    if not user or not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    return {"username": username, "role": user["role"]}
