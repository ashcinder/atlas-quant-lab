from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.auth import (
    COOKIE_NAME,
    User,
    create_session,
    hash_password,
    normalize_email,
    parse_session,
    valid_email,
    valid_password,
    verify_password,
)
from app.config import ALLOW_REGISTRATION, ALLOWED_ORIGINS, AUTH_ENABLED, SESSION_SECONDS
from app.journal.domain import clear_ledger, empty_ledger, materialize_automatic, validate_ledger
from app.journal.store import JournalStore

router = APIRouter()
store = JournalStore()
_attempts: dict[tuple[str, str], list[float]] = defaultdict(list)
_attempt_lock = Lock()


def error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


def _origin_ok(request: Request) -> bool:
    if request.headers.get("sec-fetch-site") == "cross-site":
        return False
    origin = request.headers.get("origin")
    if not origin and request.headers.get("referer"):
        ref = urlsplit(request.headers["referer"])
        origin = f"{ref.scheme}://{ref.netloc}"
    same_origin = f"{request.url.scheme}://{request.url.netloc}"
    return not origin or origin in (*ALLOWED_ORIGINS, same_origin)


def _rate_key(request: Request) -> tuple[str, str]:
    return request.url.path, request.client.host if request.client else "unknown"


def _rate_limited(request: Request, maximum: int, seconds: int) -> bool:
    cutoff = time.monotonic() - seconds
    with _attempt_lock:
        for key in list(_attempts):
            if not _attempts[key] or _attempts[key][-1] < time.monotonic() - 3600:
                del _attempts[key]
        values = [value for value in _attempts.get(_rate_key(request), []) if value > cutoff]
        if values:
            _attempts[_rate_key(request)] = values
        return len(values) >= maximum or len(_attempts) >= 10000


def _record_attempt(request: Request) -> None:
    with _attempt_lock:
        _attempts[_rate_key(request)].append(time.monotonic())


async def _body(request: Request) -> dict:
    body = await request.json()
    if not isinstance(body, dict):
        raise ValueError("请求内容必须为 JSON 对象")
    return body


def current_user(request: Request) -> User | None:
    return parse_session(request, store.find_session_user)


def authenticated(request: Request) -> User | JSONResponse:
    if not _origin_ok(request):
        return error(403, "来源不被允许")
    user = current_user(request)
    return user if user else error(401, "需要登录")


def ledger_response(user: User, payload: dict, auto_added: int) -> dict:
    return {
        **payload,
        "autoAdded": auto_added,
        "authMode": "password",
        "user": {"email": user.email},
        "userId": user.id,
    }


def synchronize(user: User) -> dict:
    old = store.read_ledger(user.id, empty_ledger())
    result = materialize_automatic(old["state"])
    if result["state"] == old["state"]:
        return ledger_response(user, old, 0)
    saved = store.save_ledger(user.id, result["state"], old["revision"])
    # Another request won the CAS race. Returning the newest materialized state is safe.
    return ledger_response(
        user, saved or store.read_ledger(user.id, empty_ledger()), result["added"] if saved else 0
    )


@router.get("/api/health")
def health():
    return {"status": "ok", "storage": "sqlite", "timezone": "Asia/Shanghai"}


@router.get("/api/session")
def session(request: Request):
    user = current_user(request)
    return {
        "authenticated": bool(user),
        "authEnabled": AUTH_ENABLED,
        "registrationEnabled": ALLOW_REGISTRATION,
        "email": user.email if user else None,
        "userId": user.id if user else None,
    }


@router.post("/api/login")
async def login(request: Request):
    if not _origin_ok(request):
        return error(403, "来源不被允许")
    if _rate_limited(request, 5, 15 * 60):
        return error(429, "登录尝试过于频繁，请稍后再试")
    body = await _body(request)
    email = normalize_email(body.get("email")) if isinstance(body, dict) else ""
    account = store.user_by_email(email) if valid_email(email) else None
    if (
        not account
        or not valid_password(body.get("password"))
        or not verify_password(body.get("password"), account["password_hash"])
    ):
        _record_attempt(request)
        return error(401, "邮箱或密码错误")
    with _attempt_lock:
        _attempts.pop(_rate_key(request), None)
    user = User(account["id"], account["email"], account["session_version"])
    response = JSONResponse({"authenticated": True, "email": user.email, "userId": user.id})
    response.set_cookie(
        COOKIE_NAME,
        create_session(user),
        max_age=SESSION_SECONDS,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
    )
    return response


@router.post("/api/register")
async def register(request: Request):
    if not _origin_ok(request):
        return error(403, "来源不被允许")
    if not ALLOW_REGISTRATION:
        return error(403, "当前服务器未开放注册")
    if _rate_limited(request, 5, 60 * 60):
        return error(429, "注册尝试过于频繁，请稍后再试")
    body = await _body(request)
    email = normalize_email(body.get("email")) if isinstance(body, dict) else ""
    password = body.get("password") if isinstance(body, dict) else None
    if not valid_email(email) or not valid_password(password):
        return error(400, "请输入有效邮箱和 8 至 128 位密码")
    user = store.create_user(email, password)
    if not user:
        return error(409, "该邮箱已注册")
    _record_attempt(request)
    response = JSONResponse(
        {"authenticated": True, "email": user.email, "userId": user.id}, status_code=201
    )
    response.set_cookie(
        COOKIE_NAME,
        create_session(user),
        max_age=SESSION_SECONDS,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
    )
    return response


@router.post("/api/logout")
def logout(request: Request):
    if not _origin_ok(request):
        return error(403, "来源不被允许")
    response = JSONResponse({"authenticated": False})
    response.delete_cookie(COOKIE_NAME, httponly=True, samesite="strict")
    return response


@router.post("/api/change-password")
async def change_password(request: Request):
    user = authenticated(request)
    if isinstance(user, JSONResponse):
        return user
    body = await _body(request)
    if _rate_limited(request, 5, 900):
        return error(429, "密码验证过于频繁，请稍后重试")
    account = store.user_by_email(user.email or "")
    if (
        not account
        or not valid_password(body.get("currentPassword"))
        or not verify_password(body.get("currentPassword"), account["password_hash"])
    ):
        _record_attempt(request)
        return error(403, "当前密码错误")
    if not valid_password(body.get("newPassword")):
        return error(400, "新密码需为 8 至 128 位")
    renewed = store.change_password(user, hash_password(body["newPassword"]))
    response = JSONResponse({"changed": True, "email": renewed.email})
    response.set_cookie(
        COOKIE_NAME,
        create_session(renewed),
        max_age=SESSION_SECONDS,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
    )
    return response


@router.get("/api/ledger")
def get_ledger(request: Request):
    user = authenticated(request)
    return user if isinstance(user, JSONResponse) else synchronize(user)


@router.put("/api/ledger")
async def put_ledger(request: Request):
    user = authenticated(request)
    if isinstance(user, JSONResponse):
        return user
    body = await _body(request)
    if type(body.get("revision")) is not int or body["revision"] < 0:
        return error(400, "账本版本无效")
    try:
        result = materialize_automatic(validate_ledger(body.get("state")))
    except (TypeError, ValueError) as exc:
        return error(400, str(exc))
    saved = store.save_ledger(user.id, result["state"], body["revision"])
    return (
        error(409, "账本已在其他设备更新，请刷新后重试")
        if not saved
        else ledger_response(user, saved, result["added"])
    )


@router.post("/api/reset")
async def reset(request: Request):
    user = authenticated(request)
    if isinstance(user, JSONResponse):
        return user
    body = await _body(request)
    if (
        not isinstance(body, dict)
        or body.get("confirmation") != "清空"
        or not isinstance(body.get("keepAccounts"), bool)
        or type(body.get("revision")) is not int
        or body.get("revision", -1) < 0
    ):
        return error(400, "重置确认信息无效")
    old = store.read_ledger(user.id, empty_ledger())
    if old["revision"] != body["revision"]:
        return error(409, "账本已在其他设备更新，请刷新后重试")
    saved = store.save_ledger(
        user.id, clear_ledger(old["state"], body["keepAccounts"]), old["revision"]
    )
    return (
        ledger_response(user, saved, 0)
        if saved
        else error(409, "账本已在其他设备更新，请刷新后重试")
    )


@router.get("/api/fx")
async def fx(request: Request):
    user = authenticated(request)
    if isinstance(user, JSONResponse):
        return user
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get("https://api.frankfurter.dev/v2/rate/USD/CNY")
            response.raise_for_status()
            data = response.json()
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("rate"), (int, float))
            or not 0.01 <= data["rate"] <= 1000
            or not isinstance(data.get("date"), str)
        ):
            raise ValueError
        return {**data, "source": "Frankfurter 汇率服务"}
    except Exception:
        return error(502, "暂时无法获取 USD/CNY 汇率")
