"""Auth routes: /auth/signup, /auth/login, /auth/refresh, /auth/me"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator

from anima.auth import AuthError, login, rotate_refresh_token, signup
from anima.api.deps import current_user
from anima.models import User, UserPublic

router = APIRouter()


class SignupRequest(BaseModel):
    email:    str
    password: str

    @field_validator("email")
    @classmethod
    def email_strip(cls, v: str) -> str:
        return v.strip()


class LoginRequest(BaseModel):
    email:    str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token:  str
    refresh_token: str
    token_type:    str = "bearer"


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def signup_route(body: SignupRequest):
    try:
        _, access, refresh = signup(body.email, body.password)
    except AuthError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/login", response_model=TokenResponse)
async def login_route(body: LoginRequest):
    try:
        _, access, refresh = login(body.email, body.password)
    except AuthError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_route(body: RefreshRequest):
    result = rotate_refresh_token(body.refresh_token)
    if not result:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or expired refresh token")
    access, refresh = result
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.get("/me", response_model=UserPublic)
async def me(user: User = Depends(current_user)):
    return UserPublic(**user.model_dump(exclude={"password_hash"}))
