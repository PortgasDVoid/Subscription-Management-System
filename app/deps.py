"""Shared engine, authentication and role guards."""
import json, os
from fastapi import Depends, Header, HTTPException
from sqlalchemy import create_engine, text
from .auth import decode_token

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://sms_user:sms_password@localhost:5432/subscription_db")
engine = create_engine(DATABASE_URL, pool_pre_ping=True,
                       **({"pool_size": 10, "max_overflow": 20} if DATABASE_URL.startswith("postgresql") else {}))
STAFF = ("admin", "staff")
ADMIN = ("admin",)


def db():
    return engine


def current_user(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Authentication required")
    claims = decode_token(authorization[7:].strip())
    if not claims:
        raise HTTPException(401, "Session expired or invalid - please sign in again")
    with engine.connect() as c:
        u = c.execute(text("SELECT id,email,role,full_name,is_active FROM users WHERE id=:i"), {"i": claims["sub"]}).mappings().first()
    if not u or not u["is_active"]:
        raise HTTPException(401, "Account not found or disabled")
    return dict(u)


def require(*roles):
    def dep(user=Depends(current_user)):
        if user["role"] not in roles:
            raise HTTPException(403, "Your role is not allowed to do this")
        return user
    return dep


def audit(conn, actor_id, action, entity_type, entity_id=None, old=None, new=None):
    conn.execute(text("""INSERT INTO audit_logs(actor_user_id,action,entity_type,entity_id,old_values,new_values)
        VALUES (:a,:act,:et,:eid,CAST(:o AS jsonb),CAST(:n AS jsonb))"""),
        {"a": actor_id, "act": action, "et": entity_type, "eid": entity_id,
         "o": json.dumps(old, default=str) if old is not None else None,
         "n": json.dumps(new, default=str) if new is not None else None})


def customer_id_for(conn, user):
    return conn.execute(text("SELECT id FROM customers WHERE user_id=:u"), {"u": user["id"]}).scalar()
