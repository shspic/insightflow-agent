from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.auth import UserResponse


class InviteCodeCreate(BaseModel):
    max_uses: int | None = Field(default=None, gt=0)
    expires_at: datetime | None = None


class InviteCodeUpdate(BaseModel):
    status: str | None = None
    max_uses: int | None = Field(default=None, gt=0)
    expires_at: datetime | None = None


class InviteCodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code_hint: str
    status: str
    max_uses: int | None
    used_count: int
    expires_at: datetime | None
    created_by_user_id: int | None
    created_at: datetime
    updated_at: datetime


class InviteCodeSecretResponse(InviteCodeResponse):
    invite_code: str


class PasswordResetAdminResponse(BaseModel):
    id: int
    user_id: int
    username: str
    status: str
    request_note: str | None
    admin_note: str | None
    requested_at: datetime
    handled_at: datetime | None
    handled_by_user_id: int | None


class AdminNoteRequest(BaseModel):
    admin_note: str | None = Field(default=None, max_length=1000)


class TemporaryPasswordResponse(BaseModel):
    request: PasswordResetAdminResponse
    temporary_password: str


class UserStatusUpdate(BaseModel):
    status: str


class UserListItem(UserResponse):
    updated_at: datetime


class AuditLogResponse(BaseModel):
    id: int
    user_id: int | None
    action: str
    resource_type: str | None
    resource_id: str | None
    status: str
    details: dict[str, Any] | None
    created_at: datetime
