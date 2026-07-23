from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RegisterRequest(BaseModel):
    username: str
    password: str
    password_confirm: str
    invite_code: str


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    new_password_confirm: str


class PasswordResetRequestCreate(BaseModel):
    username: str
    request_note: str | None = Field(default=None, max_length=1000)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: str
    status: str
    must_change_password: bool
    created_at: datetime
    last_login_at: datetime | None


class AuthResponse(BaseModel):
    user: UserResponse
    must_change_password: bool
    csrf_token: str


class CsrfResponse(BaseModel):
    message: str
    csrf_token: str


class MessageResponse(BaseModel):
    message: str
