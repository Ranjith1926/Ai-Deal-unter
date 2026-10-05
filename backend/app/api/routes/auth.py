from fastapi import APIRouter, Request, Response, status

from app.api.deps import AuthLimit, LoginGuard, SessionDep, UserDep
from app.core.errors import UnauthorizedError
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserOut,
)
from app.schemas.common import Envelope, ok
from app.services import auth as auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"], dependencies=[AuthLimit])


@router.post("/register", response_model=Envelope[UserOut], status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, session: SessionDep, response: Response):
    user = await auth_service.register(session, body.email, body.name, body.password)
    response.headers["Cache-Control"] = "no-store"
    return ok(UserOut.model_validate(user), "Account created")


@router.post("/login", response_model=Envelope[TokenPair])
async def login(body: LoginRequest, request: Request, session: SessionDep, response: Response):
    response.headers["Cache-Control"] = "no-store"
    guard = LoginGuard(request, body.email)
    await guard.check()
    try:
        tokens = await auth_service.login(session, body.email, body.password)
    except UnauthorizedError:
        await guard.failed()
        raise
    await guard.succeeded()
    return ok(tokens)


@router.post("/refresh", response_model=Envelope[TokenPair])
async def refresh(body: RefreshRequest, session: SessionDep, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return ok(await auth_service.refresh(session, body.refresh_token))


@router.post("/logout", response_model=Envelope[None])
async def logout(body: RefreshRequest, session: SessionDep):
    await auth_service.logout(session, body.refresh_token)
    return ok(message="Logged out")


@router.post("/password-reset/request", response_model=Envelope[None])
async def password_reset_request(body: PasswordResetRequest, session: SessionDep):
    await auth_service.request_password_reset(session, body.email)
    # Same answer whether or not the account exists.
    return ok(message="If an account exists for that email, a reset link has been sent")


@router.post("/password-reset/confirm", response_model=Envelope[None])
async def password_reset_confirm(body: PasswordResetConfirm, session: SessionDep):
    await auth_service.confirm_password_reset(session, body.token, body.new_password)
    return ok(message="Password updated. Please sign in again.")


@router.post("/change-password", response_model=Envelope[None])
async def change_password(body: ChangePasswordRequest, session: SessionDep, user: UserDep):
    await auth_service.change_password(session, user, body.current_password, body.new_password)
    return ok(message="Password updated. Please sign in again.")
