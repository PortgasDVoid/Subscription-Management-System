"""All SQL for renewing / closing expired subscriptions (no business rules)."""
from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import text


def _one(result):
    row = result.mappings().first()
    return dict(row) if row else None


def expired_subscription_ids(conn, as_of: date, limit: Optional[int] = None) -> list:
    """Active/paused subscriptions whose expiry_date is already behind us."""
    sql = ("SELECT id FROM subscriptions WHERE status IN ('active', 'paused') AND expiry_date < :as_of "
           "ORDER BY expiry_date, id" + (" LIMIT :limit" if limit else ""))
    params = {"as_of": as_of, **({"limit": limit} if limit else {})}
    return [r[0] for r in conn.execute(text(sql), params).all()]


def lock_subscription_with_plan(conn, subscription_id: int, skip_locked: bool = True):
    return _one(conn.execute(text(
        "SELECT s.id, s.status::text AS status, s.start_date, s.expiry_date, s.next_billing_date, "
        "s.last_billed_through, s.auto_renew, s.renewal_count, "
        "p.billing_period::text AS plan_period, p.billing_interval, p.term_periods, "
        "p.auto_renew AS plan_auto_renew "
        "FROM subscriptions s JOIN plans p ON p.id = s.plan_id WHERE s.id = :id "
        "FOR UPDATE OF s" + (" SKIP LOCKED" if skip_locked else "")), {"id": subscription_id}))


def renew_subscription(conn, subscription_id: int, new_expiry: date) -> None:
    conn.execute(text(
        "UPDATE subscriptions SET expiry_date = :e, renewal_count = renewal_count + 1 WHERE id = :id"),
        {"e": new_expiry, "id": subscription_id})


def close_subscription(conn, subscription_id: int, reason: str, note: str) -> None:
    """next_billing_date is cleared, the same way the seed represents a closed subscription."""
    conn.execute(text(
        "UPDATE subscriptions SET status = 'closed', closed_at = now(), "
        "closure_reason = CAST(:r AS closure_reason), closure_note = :n, next_billing_date = NULL "
        "WHERE id = :id"), {"r": reason, "n": note, "id": subscription_id})


def insert_event(conn, subscription_id: int, from_status: str, to_status: str, event_type: str,
                 reason: str) -> None:
    """actor_user_id stays NULL: these events are made by the scheduler."""
    conn.execute(text(
        "INSERT INTO subscription_events (subscription_id, from_status, to_status, event_type, reason) "
        "VALUES (:s, CAST(:f AS subscription_status), CAST(:t AS subscription_status), :e, :r)"),
        {"s": subscription_id, "f": from_status, "t": to_status, "e": event_type, "r": reason})
