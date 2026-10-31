"""Signup, login, password reset."""
import os
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from .auth import (normalise_email, password_problems, hash_password, verify_password, make_token,
                   new_reset_token, hash_token)
from .deps import db, current_user, audit
from .emailer import send_email

router = APIRouter(prefix="/api/auth", tags=["auth"])
APP_URL = os.getenv("APP_URL", "http://localhost:5173")
MAX_FAILS, LOCK_MINUTES, RESET_MINUTES = 5, 15, 60


class Signup(BaseModel):
    email: str; password: str; full_name: str; company_name: str | None = None; phone: str | None = None
class Login(BaseModel):
    email: str; password: str
class Forgot(BaseModel):
    email: str
class Reset(BaseModel):
    token: str; new_password: str


def _check_password(pw):
    p = password_problems(pw)
    if p: raise HTTPException(422, "Password " + ", ".join(p))


def _user_payload(u):
    return {"id": u["id"], "email": u["email"], "role": u["role"], "full_name": u["full_name"]}


@router.post("/signup", status_code=201)
def signup(x: Signup):
    try: email = normalise_email(x.email)
    except ValueError as e: raise HTTPException(422, str(e))
    _check_password(x.password)
    if not x.full_name.strip(): raise HTTPException(422, "Full name is required")
    try:
        with db().begin() as c:
            if c.execute(text("SELECT 1 FROM users WHERE email=:e"), {"e": email}).scalar():
                raise HTTPException(409, "An account with this email already exists")
            uid = c.execute(text("""INSERT INTO users(email,password_hash,role,full_name,phone)
                VALUES (:e,:h,'customer',:n,:p) RETURNING id"""),
                {"e": email, "h": hash_password(x.password), "n": x.full_name.strip(), "p": x.phone}).scalar_one()
            c.execute(text("INSERT INTO customers(user_id,name,company_name,email,phone) VALUES (:u,:n,:co,:e,:p)"),
                      {"u": uid, "n": x.full_name.strip(), "co": x.company_name, "e": email, "p": x.phone})
            audit(c, uid, "user.signup", "users", uid, None, {"email": email, "role": "customer"})
    except IntegrityError:
        raise HTTPException(409, "An account with this email already exists")
    return {"token": make_token(uid, "customer"), "user": {"id": uid, "email": email, "role": "customer", "full_name": x.full_name.strip()}}


@router.post("/login")
def login(x: Login):
    email = (x.email or "").strip().lower()
    failure = None   # raise AFTER the transaction commits, otherwise the failed-login counter would be rolled back
    with db().begin() as c:
        u = c.execute(text("SELECT * FROM users WHERE email=:e FOR UPDATE"), {"e": email}).mappings().first()
        now = datetime.now(timezone.utc)
        if not u or not u["is_active"]:
            failure = (401, "Invalid email or password")
        elif u["locked_until"] and u["locked_until"] > now:
            failure = (423, "Too many failed attempts. Try again later.")
        elif not verify_password(x.password, u["password_hash"]):
            fails = u["failed_logins"] + 1
            lock = now + timedelta(minutes=LOCK_MINUTES) if fails >= MAX_FAILS else None
            c.execute(text("UPDATE users SET failed_logins=:f,locked_until=:l WHERE id=:i"),
                      {"f": 0 if lock else fails, "l": lock, "i": u["id"]})
            failure = (401, "Invalid email or password")
        else:
            c.execute(text("UPDATE users SET failed_logins=0,locked_until=NULL,last_login_at=now() WHERE id=:i"), {"i": u["id"]})
    if failure:
        raise HTTPException(*failure)
    return {"token": make_token(u["id"], u["role"]), "user": _user_payload(u)}


@router.get("/me")
def me(user=Depends(current_user)):
    return _user_payload(user)


@router.post("/forgot-password")
def forgot(x: Forgot):
    """Always answers the same way so the endpoint cannot be used to discover which emails are registered."""
    out = {"message": "If that email is registered, a reset link has been sent."}
    email = (x.email or "").strip().lower()
    with db().begin() as c:
        u = c.execute(text("SELECT id,email,is_active FROM users WHERE email=:e"), {"e": email}).mappings().first()
        if not u or not u["is_active"]:
            return out
        raw, hashed = new_reset_token()
        c.execute(text("UPDATE auth_tokens SET used_at=now() WHERE user_id=:u AND purpose='password_reset' AND used_at IS NULL"), {"u": u["id"]})
        c.execute(text("""INSERT INTO auth_tokens(user_id,token_hash,purpose,expires_at)
            VALUES (:u,:h,'password_reset',:x)"""), {"u": u["id"], "h": hashed, "x": datetime.now(timezone.utc) + timedelta(minutes=RESET_MINUTES)})
        link = f"{APP_URL}/#reset={raw}"
        send_email(c, u["email"], "password_reset", "Reset your Brightloop password",
                   f"Use this link within {RESET_MINUTES} minutes to choose a new password:\n{link}\n\nIgnore this email if you did not ask for it.",
                   user_id=u["id"])
        if os.getenv("DEV_RETURN_RESET_TOKEN") == "1":   # demo convenience only - never enable in production
            out["dev_reset_token"] = raw
    return out


@router.post("/reset-password")
def reset(x: Reset):
    _check_password(x.new_password)
    with db().begin() as c:
        t = c.execute(text("""SELECT id,user_id FROM auth_tokens WHERE token_hash=:h AND purpose='password_reset'
            AND used_at IS NULL AND expires_at > now() FOR UPDATE"""), {"h": hash_token(x.token)}).mappings().first()
        if not t: raise HTTPException(400, "This reset link is invalid or has expired")
        c.execute(text("UPDATE users SET password_hash=:h,failed_logins=0,locked_until=NULL WHERE id=:u"),
                  {"h": hash_password(x.new_password), "u": t["user_id"]})
        c.execute(text("UPDATE auth_tokens SET used_at=now() WHERE id=:i"), {"i": t["id"]})
        audit(c, t["user_id"], "user.password_reset", "users", t["user_id"])
    return {"message": "Password updated. You can sign in now."}
