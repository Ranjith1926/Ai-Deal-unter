"""Registration, login, token refresh/rotation, logout and password reset."""
import logging
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ConflictError, UnauthorizedError, ValidationFailed
from app.core.security import (
    create_access_token,
    hash_password,
    hash_token,
    needs_rehash,
    new_opaque_token,
    password_problems,
    verify_password,
)
from app.models import Notification, PasswordResetToken, RefreshToken, User
from app.schemas.auth import TokenPair
from app.services.common import utcnow

logger = logging.getLogger(__name__)

REUSE_GRACE_SECONDS = 10


def _normalise_email(email: str) -> str:
    return email.strip().lower()


def _check_password(password: str, email: str | None = None) -> None:
    problems = password_problems(password, email)
    if problems:
        raise ValidationFailed("Password does not meet the requirements", problems)


async def _issue_tokens(session: AsyncSession, user: User, now: datetime) -> TokenPair:
    settings = get_settings()
    access, expires_in = create_access_token(user.id, now)
    refresh = new_opaque_token()
    session.add(RefreshToken(
        user_id=user.id, token_hash=hash_token(refresh),
        expires_at=now + timedelta(days=settings.refresh_token_days),
    ))
    return TokenPair(access_token=access, refresh_token=refresh, expires_in=expires_in)


async def register(session: AsyncSession, email: str, name: str, password: str) -> User:
    email = _normalise_email(email)
    _check_password(password, email)
    user = User(email=email, name=name.strip(), password_hash=hash_password(password))
    session.add(user)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise ConflictError("An account with this email already exists") from None
    await session.commit()
    return user


async def login(session: AsyncSession, email: str, password: str, now: datetime | None = None) -> TokenPair:
    now = now or utcnow()
    user = await session.scalar(select(User).where(User.email == _normalise_email(email)))
    # Always run a verify (against a dummy hash if needed) so timing doesn't reveal accounts.
    valid = verify_password(user.password_hash if user else None, password)
    if not (user and valid and user.is_active):
        raise UnauthorizedError("Invalid email or password")
    if user.password_hash and needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    tokens = await _issue_tokens(session, user, now)
    await session.commit()
    return tokens


async def _revoke_all(session: AsyncSession, user_id: int, now: datetime) -> None:
    await session.execute(
        update(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )


async def refresh(session: AsyncSession, refresh_token: str, now: datetime | None = None) -> TokenPair:
    """Rotate: the presented token is revoked and a new pair issued.

    Presenting an already-revoked token means it may have been stolen, so every session of
    that user is revoked.
    """
    now = now or utcnow()
    row = await session.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(refresh_token)))
    if row is None or row.expires_at <= now:
        raise UnauthorizedError("Invalid or expired refresh token")
    if row.revoked_at is not None:  # explicitly ended (logout, password change, theft response): final
        raise UnauthorizedError("Invalid or expired refresh token")
    reused_within_leeway = False
    if row.rotated_at is not None:
        # Parallel requests (a page and its prefetches) routinely present the same token within
        # moments of each other. Inside a short leeway that is benign: issue the caller its own
        # fresh pair instead of logging a valid session out. Only a *later* replay is theft.
        if now - row.rotated_at > timedelta(seconds=REUSE_GRACE_SECONDS):
            await _revoke_all(session, row.user_id, now)
            await session.commit()
            logger.warning("Refresh token reuse detected; all sessions revoked", extra={"user_id": row.user_id})
            raise UnauthorizedError("Invalid or expired refresh token")
        reused_within_leeway = True
    user = await session.get(User, row.user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("Invalid or expired refresh token")
    if not reused_within_leeway:
        row.rotated_at = now
    tokens = await _issue_tokens(session, user, now)
    await session.commit()
    return tokens


async def logout(session: AsyncSession, refresh_token: str, now: datetime | None = None) -> None:
    """Revoke one session. Unknown tokens are ignored so logout is always safe to call."""
    now = now or utcnow()
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == hash_token(refresh_token), RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await session.commit()


async def request_password_reset(session: AsyncSession, email: str, now: datetime | None = None) -> None:
    """Queue a reset email. Silent for unknown addresses, so accounts cannot be enumerated."""
    now = now or utcnow()
    settings = get_settings()
    user = await session.scalar(select(User).where(User.email == _normalise_email(email), User.is_active))
    if user is None:
        return
    token = new_opaque_token()
    session.add(PasswordResetToken(
        user_id=user.id, token_hash=hash_token(token),
        expires_at=now + timedelta(minutes=settings.password_reset_minutes),
    ))
    # The message holds the live token, so it is flagged sensitive: the dispatcher scrubs it once delivery
    # finishes, and expires it unsent if email is not configured.
    link = f"{settings.frontend_url.rstrip('/')}/reset-password?token={token}"
    session.add(Notification(
        user_id=user.id, type="email", title="Reset your AI Deal Hunter password",
        message=(
            f"Use this link within {settings.password_reset_minutes} minutes to choose a new password:\n\n{link}\n\n"
            "If you did not ask to reset your password, you can ignore this email."
        ),
        is_sensitive=True,
    ))
    await session.commit()


async def confirm_password_reset(
    session: AsyncSession, token: str, new_password: str, now: datetime | None = None
) -> None:
    now = now or utcnow()
    row = await session.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(token)))
    if row is None or row.used_at is not None or row.expires_at <= now:
        raise ValidationFailed("This reset link is invalid or has expired")
    user = await session.get(User, row.user_id)
    if user is None or not user.is_active:
        raise ValidationFailed("This reset link is invalid or has expired")
    _check_password(new_password, user.email)
    user.password_hash = hash_password(new_password)
    row.used_at = now
    await _revoke_all(session, user.id, now)  # a reset signs out every device
    await session.commit()


async def change_password(
    session: AsyncSession, user: User, current_password: str, new_password: str, now: datetime | None = None
) -> None:
    now = now or utcnow()
    if not verify_password(user.password_hash, current_password):
        raise UnauthorizedError("Current password is incorrect")
    _check_password(new_password, user.email)
    user.password_hash = hash_password(new_password)
    await _revoke_all(session, user.id, now)
    await session.commit()
