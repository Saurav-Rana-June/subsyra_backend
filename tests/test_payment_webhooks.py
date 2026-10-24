import unittest
import json
import hmac
import hashlib
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from main import app
from src.utils.db import LocalSession
from src.utils.settings import settings
from src.users.models import UserModel
from src.plans_pricing.models import PlanPricingModel
from src.subscription.models import SubscriptionModel, SubscriptionStatus
from src.payment.models import PaymentModel, PaymentStatus, WebhookEventModel
from src.invoices.models import InvoiceModel


class TestRazorpayWebhook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.secret = settings.RAZORPAY_WEBHOOK_SECRET.encode("utf-8")
        cls.db = LocalSession()

        # Ensure a test user exists
        cls.user = cls.db.query(UserModel).first()
        if not cls.user:
            cls.user = UserModel(
                full_name="Webhook Test User",
                email_address="webhook_test@example.com",
                hashed_password="dummy_hashed_password",
                mobile_number="9999999999",
                role="CUSTOMER"
            )
            cls.db.add(cls.user)
            cls.db.commit()
            cls.db.refresh(cls.user)

        # Ensure a test plan exists
        cls.plan = cls.db.query(PlanPricingModel).first()
        if not cls.plan:
            cls.plan = PlanPricingModel(
                name="Pro Webhook Plan",
                price=50000,
                currency="INR",
                billing_interval="month",
                interval_count=1,
                features=[]
            )
            cls.db.add(cls.plan)
            cls.db.commit()
            cls.db.refresh(cls.plan)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def generate_signature(self, body_bytes: bytes) -> str:
        return hmac.new(self.secret, body_bytes, hashlib.sha256).hexdigest()

    def test_01_missing_signature_header_returns_400(self):
        response = self.client.post("/api/payments/webhook/razorpay", content=b"{}")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json().get("detail"), "Missing signature header")

    def test_02_invalid_signature_returns_400(self):
        response = self.client.post(
            "/api/payments/webhook/razorpay",
            headers={"x-razorpay-signature": "invalid_dummy_signature"},
            content=b"{}"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json().get("detail"), "Invalid webhook signature")

    def test_03_malformed_json_returns_400(self):
        malformed_body = b"{\"event\": broken_json"
        sig = self.generate_signature(malformed_body)
        response = self.client.post(
            "/api/payments/webhook/razorpay",
            headers={"x-razorpay-signature": sig},
            content=malformed_body
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json().get("detail"), "Malformed JSON payload")

    def test_04_unsupported_event_returns_200_and_skipped(self):
        event_id = f"evt_unsupported_{int(datetime.now().timestamp())}"
        body = json.dumps({
            "id": event_id,
            "event": "refund.created",
            "payload": {"refund": {"entity": {"id": "rfd_123"}}}
        }).encode("utf-8")
        sig = self.generate_signature(body)

        response = self.client.post(
            "/api/payments/webhook/razorpay",
            headers={"x-razorpay-signature": sig, "x-razorpay-event-id": event_id},
            content=body
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("event_status"), "SKIPPED")

        # Verify DB audit status
        ev = self.db.query(WebhookEventModel).filter(WebhookEventModel.event_id == event_id).first()
        self.assertIsNotNone(ev)
        self.assertEqual(ev.status, "SKIPPED")

        # Clean up
        self.db.delete(ev)
        self.db.commit()

    def test_05_unmatched_order_id_returns_200_and_unmatched(self):
        event_id = f"evt_unmatched_{int(datetime.now().timestamp())}"
        body = json.dumps({
            "id": event_id,
            "event": "payment.captured",
            "payload": {"payment": {"entity": {"id": "pay_xyz", "order_id": "order_non_existent_999", "amount": 50000, "currency": "INR"}}}
        }).encode("utf-8")
        sig = self.generate_signature(body)

        response = self.client.post(
            "/api/payments/webhook/razorpay",
            headers={"x-razorpay-signature": sig, "x-razorpay-event-id": event_id},
            content=body
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("event_status"), "UNMATCHED")

        # Verify DB audit status
        ev = self.db.query(WebhookEventModel).filter(WebhookEventModel.event_id == event_id).first()
        self.assertIsNotNone(ev)
        self.assertEqual(ev.status, "UNMATCHED")

        # Clean up
        self.db.delete(ev)
        self.db.commit()

    def test_06_amount_mismatch_fails_payment_and_preserves_subscription(self):
        # Create fresh subscription & payment
        sub = SubscriptionModel(
            user_id=self.user.id,
            plan_id=self.plan.id,
            status=SubscriptionStatus.PENDING_PAYMENT.value,
            price_amount=50000,
            currency="INR",
            billing_interval="month",
            interval_count=1
        )
        self.db.add(sub)
        self.db.commit()

        order_id = f"order_mismatch_{sub.id}"
        payment = PaymentModel(
            subscription_id=sub.id,
            user_id=self.user.id,
            provider="RAZORPAY",
            provider_order_id=order_id,
            amount=50000,
            currency="INR",
            status=PaymentStatus.CREATED.value
        )
        self.db.add(payment)
        self.db.commit()

        event_id = f"evt_amt_mismatch_{sub.id}"
        # Webhook reports 100 paise instead of 50000 paise
        body = json.dumps({
            "id": event_id,
            "event": "payment.captured",
            "payload": {"payment": {"entity": {"id": "pay_bad_amt", "order_id": order_id, "amount": 100, "currency": "INR"}}}
        }).encode("utf-8")
        sig = self.generate_signature(body)

        response = self.client.post(
            "/api/payments/webhook/razorpay",
            headers={"x-razorpay-signature": sig, "x-razorpay-event-id": event_id},
            content=body
        )
        self.assertEqual(response.status_code, 200)

        self.db.refresh(payment)
        self.db.refresh(sub)
        self.assertEqual(payment.status, PaymentStatus.FAILED.value)
        self.assertIn("Amount/Currency mismatch", payment.failure_reason)
        self.assertEqual(sub.status, SubscriptionStatus.PENDING_PAYMENT.value)

        # Clean up
        ev = self.db.query(WebhookEventModel).filter(WebhookEventModel.event_id == event_id).first()
        if ev:
            self.db.delete(ev)
        self.db.delete(payment)
        self.db.delete(sub)
        self.db.commit()

    def test_07_currency_mismatch_fails_payment(self):
        sub = SubscriptionModel(
            user_id=self.user.id,
            plan_id=self.plan.id,
            status=SubscriptionStatus.PENDING_PAYMENT.value,
            price_amount=50000,
            currency="INR",
            billing_interval="month",
            interval_count=1
        )
        self.db.add(sub)
        self.db.commit()

        order_id = f"order_cur_mismatch_{sub.id}"
        payment = PaymentModel(
            subscription_id=sub.id,
            user_id=self.user.id,
            provider="RAZORPAY",
            provider_order_id=order_id,
            amount=50000,
            currency="INR",
            status=PaymentStatus.CREATED.value
        )
        self.db.add(payment)
        self.db.commit()

        event_id = f"evt_cur_mismatch_{sub.id}"
        # Webhook reports USD instead of INR
        body = json.dumps({
            "id": event_id,
            "event": "payment.captured",
            "payload": {"payment": {"entity": {"id": "pay_bad_cur", "order_id": order_id, "amount": 50000, "currency": "USD"}}}
        }).encode("utf-8")
        sig = self.generate_signature(body)

        response = self.client.post(
            "/api/payments/webhook/razorpay",
            headers={"x-razorpay-signature": sig, "x-razorpay-event-id": event_id},
            content=body
        )
        self.assertEqual(response.status_code, 200)

        self.db.refresh(payment)
        self.db.refresh(sub)
        self.assertEqual(payment.status, PaymentStatus.FAILED.value)
        self.assertIn("Amount/Currency mismatch", payment.failure_reason)

        # Clean up
        ev = self.db.query(WebhookEventModel).filter(WebhookEventModel.event_id == event_id).first()
        if ev:
            self.db.delete(ev)
        self.db.delete(payment)
        self.db.delete(sub)
        self.db.commit()

    def test_08_successful_payment_activates_subscription_and_sets_calendar_dates(self):
        sub = SubscriptionModel(
            user_id=self.user.id,
            plan_id=self.plan.id,
            status=SubscriptionStatus.PENDING_PAYMENT.value,
            price_amount=50000,
            currency="INR",
            billing_interval="month",
            interval_count=1
        )
        self.db.add(sub)
        self.db.commit()

        order_id = f"order_success_{sub.id}"
        payment = PaymentModel(
            subscription_id=sub.id,
            user_id=self.user.id,
            provider="RAZORPAY",
            provider_order_id=order_id,
            amount=50000,
            currency="INR",
            status=PaymentStatus.CREATED.value
        )
        self.db.add(payment)
        self.db.commit()

        event_id = f"evt_success_{sub.id}"
        body = json.dumps({
            "id": event_id,
            "event": "payment.captured",
            "payload": {"payment": {"entity": {"id": "pay_success_123", "order_id": order_id, "amount": 50000, "currency": "INR"}}}
        }).encode("utf-8")
        sig = self.generate_signature(body)

        response = self.client.post(
            "/api/payments/webhook/razorpay",
            headers={"x-razorpay-signature": sig, "x-razorpay-event-id": event_id},
            content=body
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("event_status"), "PROCESSED")

        self.db.refresh(payment)
        self.db.refresh(sub)
        self.assertEqual(payment.status, PaymentStatus.SUCCESS.value)
        self.assertEqual(payment.provider_payment_id, "pay_success_123")
        self.assertEqual(sub.status, SubscriptionStatus.ACTIVE.value)
        self.assertIsNotNone(sub.current_period_start)
        self.assertIsNotNone(sub.current_period_end)
        self.assertGreater(sub.current_period_end, sub.current_period_start)

        # Verify invoice was automatically generated
        inv = self.db.query(InvoiceModel).filter(InvoiceModel.payment_id == payment.id).first()
        self.assertIsNotNone(inv)
        self.assertEqual(inv.status, "PAID")
        self.assertEqual(inv.total_amount, 50000)
        self.assertTrue(inv.invoice_number.startswith("INV-"))

        # Clean up
        ev = self.db.query(WebhookEventModel).filter(WebhookEventModel.event_id == event_id).first()
        if ev:
            self.db.delete(ev)
        if inv:
            self.db.delete(inv)
        self.db.delete(payment)
        self.db.delete(sub)
        self.db.commit()

    def test_09_duplicate_delivery_idempotency_does_not_reset_dates(self):
        sub = SubscriptionModel(
            user_id=self.user.id,
            plan_id=self.plan.id,
            status=SubscriptionStatus.PENDING_PAYMENT.value,
            price_amount=50000,
            currency="INR",
            billing_interval="month",
            interval_count=1
        )
        self.db.add(sub)
        self.db.commit()

        order_id = f"order_idem_{sub.id}"
        payment = PaymentModel(
            subscription_id=sub.id,
            user_id=self.user.id,
            provider="RAZORPAY",
            provider_order_id=order_id,
            amount=50000,
            currency="INR",
            status=PaymentStatus.CREATED.value
        )
        self.db.add(payment)
        self.db.commit()

        event_id = f"evt_idem_{sub.id}"
        body = json.dumps({
            "id": event_id,
            "event": "payment.captured",
            "payload": {"payment": {"entity": {"id": "pay_idem_123", "order_id": order_id, "amount": 50000, "currency": "INR"}}}
        }).encode("utf-8")
        sig = self.generate_signature(body)

        # 1st Delivery
        res1 = self.client.post(
            "/api/payments/webhook/razorpay",
            headers={"x-razorpay-signature": sig, "x-razorpay-event-id": event_id},
            content=body
        )
        self.assertEqual(res1.status_code, 200)

        self.db.refresh(sub)
        first_period_start = sub.current_period_start
        first_period_end = sub.current_period_end

        # 2nd Delivery (exact duplicate)
        res2 = self.client.post(
            "/api/payments/webhook/razorpay",
            headers={"x-razorpay-signature": sig, "x-razorpay-event-id": event_id},
            content=body
        )
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.json().get("message"), "Event already processed")

        # Confirm dates were NOT altered
        self.db.refresh(sub)
        self.assertEqual(sub.current_period_start, first_period_start)
        self.assertEqual(sub.current_period_end, first_period_end)

        # Confirm only ONE invoice was created (no duplicates)
        invoice_count = self.db.query(InvoiceModel).filter(InvoiceModel.payment_id == payment.id).count()
        self.assertEqual(invoice_count, 1)

        # Clean up
        ev = self.db.query(WebhookEventModel).filter(WebhookEventModel.event_id == event_id).first()
        if ev:
            self.db.delete(ev)
        inv = self.db.query(InvoiceModel).filter(InvoiceModel.payment_id == payment.id).first()
        if inv:
            self.db.delete(inv)
        self.db.delete(payment)
        self.db.delete(sub)
        self.db.commit()

    def test_10_delayed_failure_event_does_not_overwrite_success(self):
        sub = SubscriptionModel(
            user_id=self.user.id,
            plan_id=self.plan.id,
            status=SubscriptionStatus.ACTIVE.value,
            price_amount=50000,
            currency="INR",
            billing_interval="month",
            interval_count=1
        )
        self.db.add(sub)
        self.db.commit()

        order_id = f"order_delayed_{sub.id}"
        payment = PaymentModel(
            subscription_id=sub.id,
            user_id=self.user.id,
            provider="RAZORPAY",
            provider_order_id=order_id,
            amount=50000,
            currency="INR",
            status=PaymentStatus.SUCCESS.value
        )
        self.db.add(payment)
        self.db.commit()

        event_id = f"evt_delayed_fail_{sub.id}"
        body = json.dumps({
            "id": event_id,
            "event": "payment.failed",
            "payload": {"payment": {"entity": {"id": "pay_delayed_fail", "order_id": order_id, "error_description": "Delayed failure"}}}
        }).encode("utf-8")
        sig = self.generate_signature(body)

        response = self.client.post(
            "/api/payments/webhook/razorpay",
            headers={"x-razorpay-signature": sig, "x-razorpay-event-id": event_id},
            content=body
        )
        self.assertEqual(response.status_code, 200)

        # Verify payment is STILL SUCCESS
        self.db.refresh(payment)
        self.db.refresh(sub)
        self.assertEqual(payment.status, PaymentStatus.SUCCESS.value)
        self.assertEqual(sub.status, SubscriptionStatus.ACTIVE.value)

        # Clean up
        ev = self.db.query(WebhookEventModel).filter(WebhookEventModel.event_id == event_id).first()
        if ev:
            self.db.delete(ev)
        inv = self.db.query(InvoiceModel).filter(InvoiceModel.payment_id == payment.id).first()
        if inv:
            self.db.delete(inv)
        self.db.delete(payment)
        self.db.delete(sub)
        self.db.commit()

    def test_11_cancelled_subscription_is_not_reactivated_by_delayed_webhook(self):
        sub = SubscriptionModel(
            user_id=self.user.id,
            plan_id=self.plan.id,
            status=SubscriptionStatus.CANCELLED.value,
            price_amount=50000,
            currency="INR",
            billing_interval="month",
            interval_count=1
        )
        self.db.add(sub)
        self.db.commit()

        order_id = f"order_cancelled_{sub.id}"
        payment = PaymentModel(
            subscription_id=sub.id,
            user_id=self.user.id,
            provider="RAZORPAY",
            provider_order_id=order_id,
            amount=50000,
            currency="INR",
            status=PaymentStatus.CREATED.value
        )
        self.db.add(payment)
        self.db.commit()

        event_id = f"evt_canc_{sub.id}"
        body = json.dumps({
            "id": event_id,
            "event": "payment.captured",
            "payload": {"payment": {"entity": {"id": "pay_canc", "order_id": order_id, "amount": 50000, "currency": "INR"}}}
        }).encode("utf-8")
        sig = self.generate_signature(body)

        response = self.client.post(
            "/api/payments/webhook/razorpay",
            headers={"x-razorpay-signature": sig, "x-razorpay-event-id": event_id},
            content=body
        )
        self.assertEqual(response.status_code, 200)

        self.db.refresh(payment)
        self.db.refresh(sub)
        # Payment succeeded, but subscription remained CANCELLED (cannot reactivate a cancelled sub)
        self.assertEqual(payment.status, PaymentStatus.SUCCESS.value)
        self.assertEqual(sub.status, SubscriptionStatus.CANCELLED.value)

        # Clean up
        ev = self.db.query(WebhookEventModel).filter(WebhookEventModel.event_id == event_id).first()
        if ev:
            self.db.delete(ev)
        inv = self.db.query(InvoiceModel).filter(InvoiceModel.payment_id == payment.id).first()
        if inv:
            self.db.delete(inv)
        self.db.delete(payment)
        self.db.delete(sub)
        self.db.commit()


if __name__ == "__main__":
    unittest.main()
