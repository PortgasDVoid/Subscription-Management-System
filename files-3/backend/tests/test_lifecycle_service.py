"""PostgreSQL integration tests for subscription_lifecycle_service and v_subscription_stage.

NOT YET RUN: written without a database available. Run with TEST_DATABASE_URL set (see conftest.py).
Seed anchors: sub 3 yearly (expiry 2027-01-31, billed through that day), sub 5 paused, sub 6 closed.
"""
from datetime import date

from app.services.subscription_lifecycle_service import SubscriptionLifecycleService, run_lifecycle
from tests.conftest import q

AFTER = date(2027, 2, 1)


def sub(conn, sid):
    return q(conn, "SELECT status::text, expiry_date, renewal_count, closure_reason::text, next_billing_date, "
                   "closed_at FROM subscriptions WHERE id = :i", i=sid).one()


def events(conn, sid):
    return q(conn, "SELECT event_type, from_status::text, to_status::text, actor_user_id FROM subscription_events "
                   "WHERE subscription_id = :i ORDER BY id DESC LIMIT 1", i=sid).one()


def test_fully_billed_yearly_subscription_auto_renews(conn):
    r = SubscriptionLifecycleService(conn).process_expired(3, AFTER)
    assert (r.outcome, r.new_expiry) == ("renewed", date(2028, 1, 31))
    s = sub(conn, 3)
    assert (s[0], s[1], s[2], s[4]) == ("active", date(2028, 1, 31), 1, date(2027, 2, 1))   # billing carries on
    assert tuple(events(conn, 3)) == ("renewed", "active", "active", None)


def test_plan_without_auto_renew_closes_as_expired(conn):
    q(conn, "UPDATE plans SET auto_renew = FALSE WHERE id = 3")
    r = SubscriptionLifecycleService(conn).process_expired(3, AFTER)
    assert r.outcome == "closed"
    s = sub(conn, 3)
    assert (s[0], s[3], s[4]) == ("closed", "expired", None) and s[5] is not None
    assert tuple(events(conn, 3)) == ("closed", "active", "closed", None)


def test_expired_while_paused_is_closed(conn):
    q(conn, "UPDATE subscriptions SET expiry_date = '2026-10-01' WHERE id = 5")
    assert SubscriptionLifecycleService(conn).process_expired(5, date(2026, 10, 31)).outcome == "closed"
    assert sub(conn, 5)[3] == "expired"


def test_unbilled_periods_are_left_for_the_billing_run(conn):
    q(conn, "UPDATE subscriptions SET expiry_date = '2026-12-31' WHERE id = 1")      # Nov, Dec not invoiced yet
    r = SubscriptionLifecycleService(conn).process_expired(1, date(2027, 1, 2))
    assert (r.outcome, r.reason) == ("skipped", "unbilled_periods") and sub(conn, 1)[0] == "active"


def test_running_twice_does_not_renew_twice(conn):
    svc = SubscriptionLifecycleService(conn)
    svc.process_expired(3, AFTER)
    again = svc.process_expired(3, AFTER)
    assert (again.outcome, again.reason) == ("skipped", "not_expired") and sub(conn, 3)[2] == 1


def test_run_lifecycle_summary(conn, scope):
    q(conn, "UPDATE plans SET auto_renew = FALSE WHERE id = 3")
    q(conn, "UPDATE subscriptions SET expiry_date = '2026-10-01' WHERE id = 5")
    s = run_lifecycle(scope, as_of=AFTER)
    assert (s.checked, s.closed, s.renewed, s.errors) == (2, 2, 0, [])


# ---- stage view (db/03_subscription_stage_view.sql) -------------------------------------------
def stages(conn):
    return {r[0]: r[1] for r in q(conn, "SELECT subscription_id, stage FROM v_subscription_stage")}


def test_seed_stages(conn):
    assert stages(conn) == {1: "Active", 2: "Active", 3: "Active", 4: "Active", 5: "Active", 6: "Closed"}
    assert q(conn, "SELECT is_paused FROM v_subscription_stage WHERE subscription_id = 5").scalar() is True


def test_draft_to_closed_journey(conn):
    q(conn, "UPDATE subscriptions SET status = 'draft' WHERE id = 1")
    for quote_status, expected in (("draft", "Draft"), ("sent", "Quotation"), ("approved", "Confirmed"),
                                   ("converted", "Confirmed")):
        q(conn, "UPDATE quotations SET status = CAST(:s AS quotation_status) WHERE id = 1", s=quote_status)
        assert stages(conn)[1] == expected, quote_status
    q(conn, "UPDATE subscriptions SET quotation_id = NULL WHERE id = 1")
    assert stages(conn)[1] == "Draft"
