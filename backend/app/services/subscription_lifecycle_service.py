"""Close or auto-renew subscriptions whose expiry_date has passed (nightly job).

The billing engine only SKIPS an expired subscription ("expired"); this service is the missing half:

* paused + expired            -> closed (closure_reason 'expired'); nothing to bill while paused.
* active + expired, but billing has not yet caught up to expiry_date -> skipped ("unbilled_periods");
  the next billing run invoices the remaining periods first, then a later run closes/renews it.
* active + expired, fully billed:
    - subscription.auto_renew AND plan.auto_renew AND plan.term_periods known -> renewed: expiry_date
      moves forward by one term, renewal_count + 1, event 'renewed'. next_billing_date is already
      expiry_date + 1 day, so billing carries straight on.
    - auto-renew wanted but the plan has no term length -> skipped ("renewal_term_unknown"), because
      guessing a term could silently bill a customer for the wrong period. Someone must set it.
    - otherwise -> closed (closure_reason 'expired').

ASSUMPTION TO CONFIRM: ``plans.term_periods`` counts units of ``plans.billing_period`` (4 for the
weekly trial = 4 weeks, 1 for the yearly plan = 1 year), NOT multiples of ``billing_interval``.

Run order each night:  run_billing(...)  ->  run_lifecycle(...)  ->  SELECT mark_overdue_invoices();

``decide_expiry_action`` is pure (no database) so every rule is unit-tested without PostgreSQL.
"""
from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Optional

from sqlalchemy.exc import SQLAlchemyError

from app.repositories import lifecycle_repository as repo
from app.services.errors import BillingError
from app.utils import calculations as calc

RENEWED, CLOSED, SKIPPED, ERROR = "renewed", "closed", "skipped", "error"


@dataclass(frozen=True)
class ExpiryDecision:
    action: str                       # 'renew' | 'close' | 'skip'
    reason: str
    new_expiry: Optional[date] = None


@dataclass
class LifecycleResult:
    subscription_id: int
    outcome: str                      # renewed | closed | skipped | error
    reason: Optional[str] = None
    new_expiry: Optional[date] = None


@dataclass
class LifecycleSummary:
    as_of: date
    checked: int = 0
    renewed: int = 0
    closed: int = 0
    skipped: int = 0
    errors: list = field(default_factory=list)
    results: list = field(default_factory=list)


def decide_expiry_action(sub: dict, as_of: date) -> ExpiryDecision:
    """``sub`` is a row from lifecycle_repository.lock_subscription_with_plan."""
    expiry = sub["expiry_date"]
    status = sub["status"]
    if status not in ("active", "paused"):
        return ExpiryDecision("skip", f"subscription_{status}")
    if expiry is None or expiry >= as_of:
        return ExpiryDecision("skip", "not_expired")
    if status == "paused":
        return ExpiryDecision("close", "expired while paused")

    next_billing = sub["next_billing_date"]
    if next_billing is not None and next_billing <= expiry:
        return ExpiryDecision("skip", "unbilled_periods")        # let billing catch up first

    if sub["auto_renew"] and sub["plan_auto_renew"]:
        term = sub["term_periods"]
        if not term:
            return ExpiryDecision("skip", "renewal_term_unknown")
        first_day = expiry + timedelta(days=1)
        new_expiry = calc.billing_period_end(first_day, sub["plan_period"], term, anchor=first_day)
        return ExpiryDecision("renew", "auto-renewed", new_expiry)
    return ExpiryDecision("close", "expired")


class SubscriptionLifecycleService:
    def __init__(self, conn):
        self.conn = conn

    def process_expired(self, subscription_id: int, as_of: date) -> LifecycleResult:
        try:
            with self.conn.begin_nested():                       # SAVEPOINT: all-or-nothing
                sub = repo.lock_subscription_with_plan(self.conn, subscription_id)
                if sub is None:
                    return LifecycleResult(subscription_id, SKIPPED, "locked_or_missing")
                d = decide_expiry_action(sub, as_of)
                if d.action == "skip":
                    return LifecycleResult(subscription_id, SKIPPED, d.reason)
                if d.action == "renew":
                    repo.renew_subscription(self.conn, subscription_id, d.new_expiry)
                    repo.insert_event(self.conn, subscription_id, "active", "active", "renewed",
                                      f"Auto-renewed until {d.new_expiry.isoformat()}")
                    return LifecycleResult(subscription_id, RENEWED, d.reason, d.new_expiry)
                note = f"Expired on {sub['expiry_date'].isoformat()}"
                repo.close_subscription(self.conn, subscription_id, "expired", note)
                repo.insert_event(self.conn, subscription_id, sub["status"], "closed", "closed", note)
                return LifecycleResult(subscription_id, CLOSED, d.reason)
        except (BillingError, calc.CalculationError, SQLAlchemyError) as exc:
            return LifecycleResult(subscription_id, ERROR, type(exc).__name__, None)


def run_lifecycle(scope: Callable[[], AbstractContextManager], as_of: Optional[date] = None,
                  limit: Optional[int] = None) -> LifecycleSummary:
    """Process every expired subscription, each in its own transaction (one failure never blocks the rest)."""
    as_of = as_of or date.today()
    with scope() as conn:
        ids = repo.expired_subscription_ids(conn, as_of, limit)
    summary = LifecycleSummary(as_of=as_of, checked=len(ids))
    for sid in ids:
        with scope() as conn:
            res = SubscriptionLifecycleService(conn).process_expired(sid, as_of)
        summary.results.append(res)
        if res.outcome == RENEWED:
            summary.renewed += 1
        elif res.outcome == CLOSED:
            summary.closed += 1
        elif res.outcome == SKIPPED:
            summary.skipped += 1
        else:
            summary.errors.append({"subscription_id": sid, "code": res.reason})
    return summary
