from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, StringConstraints

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Password = Annotated[str, Field(min_length=1, max_length=256)]  # strength is checked in the service


class RegisterRequest(BaseModel):
    email: EmailStr
    name: Name
    password: Password


class LoginRequest(BaseModel):
    email: EmailStr
    password: Password


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=200)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    new_password: Password


class ChangePasswordRequest(BaseModel):
    current_password: Password
    new_password: Password


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    is_admin: bool
    notification_preferences: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class ProfileUpdate(BaseModel):
    name: Name | None = None
    notification_preferences: dict | None = None
