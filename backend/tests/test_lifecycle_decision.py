"""Pure unit tests for the expiry decision rules (no database)."""
import unittest
from datetime import date

from app.services.subscription_lifecycle_service import decide_expiry_action as decide


def sub(**kw):
    base = dict(status="active", start_date=date(2026, 2, 1), expiry_date=date(2027, 1, 31),
                next_billing_date=date(2027, 2, 1), last_billed_through=date(2027, 1, 31),
                auto_renew=True, plan_auto_renew=True, plan_period="yearly", billing_interval=1, term_periods=1)
    base.update(kw)
    return base


AFTER = date(2027, 2, 1)


class Decisions(unittest.TestCase):
    def test_not_expired_yet(self):
        self.assertEqual(decide(sub(), date(2027, 1, 31)).reason, "not_expired")     # expiry day itself is still valid
        self.assertEqual(decide(sub(expiry_date=None), AFTER).reason, "not_expired")

    def test_yearly_auto_renews_one_term(self):
        d = decide(sub(), AFTER)
        self.assertEqual((d.action, d.new_expiry), ("renew", date(2028, 1, 31)))

    def test_weekly_trial_term_counts_weeks(self):
        s = sub(plan_period="weekly", term_periods=4, expiry_date=date(2026, 12, 6), next_billing_date=date(2026, 12, 7))
        self.assertEqual(decide(s, date(2026, 12, 7)).new_expiry, date(2027, 1, 3))

    def test_plan_without_auto_renew_closes(self):
        self.assertEqual(decide(sub(plan_auto_renew=False), AFTER).action, "close")
        self.assertEqual(decide(sub(auto_renew=False), AFTER).action, "close")

    def test_auto_renew_without_a_term_is_flagged_not_guessed(self):
        d = decide(sub(term_periods=None), AFTER)
        self.assertEqual((d.action, d.reason), ("skip", "renewal_term_unknown"))

    def test_unbilled_periods_wait_for_billing(self):
        s = sub(next_billing_date=date(2027, 1, 1))              # January period not invoiced yet
        self.assertEqual(decide(s, AFTER).reason, "unbilled_periods")

    def test_paused_and_expired_closes(self):
        s = sub(status="paused", next_billing_date=date(2026, 9, 1))
        self.assertEqual(decide(s, AFTER).action, "close")

    def test_closed_and_draft_are_left_alone(self):
        for status in ("closed", "draft"):
            self.assertEqual(decide(sub(status=status), AFTER).action, "skip")


if __name__ == "__main__":
    unittest.main()
