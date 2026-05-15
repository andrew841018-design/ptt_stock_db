
import os
import datetime
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext

from config import JWT_SECRET_KEY, JWT_ALGORITHM, JWT_EXPIRE_MINUTES

_bearer_scheme = HTTPBearer()

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_TIMING_DUMMY_HASH = "$2b$12$C.kB9zgc/KQHoPGPFRJJNOxXNOSRPl15HrOeUf5/ivW98bQDRHYQK"

_USERS = {
    "admin":  {"pw_hash": os.environ.get("ADMIN_PW_HASH"),  "role": "admin"},
    "viewer": {"pw_hash": os.environ.get("VIEWER_PW_HASH"), "role": "viewer"},
}


def create_token(username: str, role: str) -> str:
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
    token = credentials.credentials

    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])

        return payload

    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def authenticate_user(username: str, password: str) -> dict:
    user = _USERS.get(username)
    stored_hash = (user["pw_hash"] if user else None) or _TIMING_DUMMY_HASH
    valid = _pwd_context.verify(password, stored_hash)

    if not user or not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    return {"username": username, "role": user["role"]}
