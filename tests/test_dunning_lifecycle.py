import unittest
import json
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from src.utils.db import LocalSession
from src.users.models import UserModel
from src.plans_pricing.models import PlanPricingModel
from src.subscription.models import SubscriptionModel, SubscriptionStatus
from src.payment.models import PaymentModel, PaymentStatus
from src.invoices.models import InvoiceModel
from src.payment.dtos import PaymentCheckoutRequestSchema, PaymentVerifySchema
from src.payment.controllers import initiate_checkout, verify_payment, handle_razorpay_webhook
from src.utils.subscription_services import handle_failed_renewal, process_subscription_renewals


class TestDunningLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = LocalSession()

        # 1. Test User
        cls.user = cls.db.query(UserModel).filter(UserModel.email_address == "dunning_user@example.com").first()
        if not cls.user:
            cls.user = UserModel(
                full_name="Dunning Test User",
                email_address="dunning_user@example.com",
                hashed_password="hashed_pw_test",
                mobile_number="9888877777",
                role="CUSTOMER",
            )
            cls.db.add(cls.user)
            cls.db.commit()
            cls.db.refresh(cls.user)

        # 2. Plan
        cls.plan = cls.db.query(PlanPricingModel).filter(PlanPricingModel.name == "Dunning Test Plan").first()
        if not cls.plan:
            cls.plan = PlanPricingModel(
                name="Dunning Test Plan",
                price_amount=69900,
                currency="INR",
                billing_interval="month",
                interval_count=1,
                features=["Feature A", "Feature B"],
                is_active=True,
            )
            cls.db.add(cls.plan)
            cls.db.commit()
            cls.db.refresh(cls.plan)

    @classmethod
    def tearDownClass(cls):
        cls.db.query(InvoiceModel).filter(InvoiceModel.user_id == cls.user.id).delete()
        cls.db.query(PaymentModel).filter(PaymentModel.user_id == cls.user.id).delete()
        cls.db.query(SubscriptionModel).filter(SubscriptionModel.user_id == cls.user.id).delete()
        if cls.plan:
            cls.db.delete(cls.plan)
        if cls.user:
            cls.db.delete(cls.user)
        cls.db.commit()
        cls.db.close()

    def tearDown(self):
        self.db.query(InvoiceModel).filter(InvoiceModel.user_id == self.user.id).delete()
        self.db.query(PaymentModel).filter(PaymentModel.user_id == self.user.id).delete()
        self.db.query(SubscriptionModel).filter(SubscriptionModel.user_id == self.user.id).delete()
        self.db.commit()

    def test_01_failed_renewal_enters_grace_period_past_due(self):
        now = datetime.now(timezone.utc)
        sub = SubscriptionModel(
            user_id=self.user.id,
            plan_id=self.plan.id,
            status=SubscriptionStatus.ACTIVE.value,
            price_amount=self.plan.price_amount,
            currency="INR",
            billing_interval="month",
            interval_count=1,
            current_period_start=now - timedelta(days=30),
            current_period_end=now,
            renewal_retry_count=0,
            grace_period_end=None,
        )
        self.db.add(sub)
        self.db.commit()
        self.db.refresh(sub)

        # 1. Trigger failed renewal
        result = handle_failed_renewal(sub=sub, db=self.db, max_retries=3, grace_period_days=7)
        self.assertEqual(result, "PAST_DUE")
        self.assertEqual(sub.status, SubscriptionStatus.PAST_DUE.value)
        self.assertEqual(sub.renewal_retry_count, 1)
        self.assertIsNotNone(sub.grace_period_end)

    def test_02_retry_exhaustion_transitions_to_expired(self):
        now = datetime.now(timezone.utc)
        sub = SubscriptionModel(
            user_id=self.user.id,
            plan_id=self.plan.id,
            status=SubscriptionStatus.PAST_DUE.value,
            price_amount=self.plan.price_amount,
            currency="INR",
            billing_interval="month",
            interval_count=1,
            current_period_start=now - timedelta(days=30),
            current_period_end=now,
            renewal_retry_count=2,
            grace_period_end=now + timedelta(days=4),
        )
        self.db.add(sub)
        self.db.commit()
        self.db.refresh(sub)

        # 3rd retry (reaches max_retries=3) -> still PAST_DUE
        res3 = handle_failed_renewal(sub=sub, db=self.db, max_retries=3)
        self.assertEqual(res3, "PAST_DUE")
        self.assertEqual(sub.renewal_retry_count, 3)

        # 4th retry (exceeds max_retries) -> transitions to EXPIRED
        res4 = handle_failed_renewal(sub=sub, db=self.db, max_retries=3)
        self.assertEqual(res4, "EXPIRED")
        self.assertEqual(sub.status, SubscriptionStatus.EXPIRED.value)

    def test_03_expired_grace_period_processed_by_worker(self):
        now = datetime.now(timezone.utc)
        sub = SubscriptionModel(
            user_id=self.user.id,
            plan_id=self.plan.id,
            status=SubscriptionStatus.PAST_DUE.value,
            price_amount=self.plan.price_amount,
            currency="INR",
            billing_interval="month",
            interval_count=1,
            current_period_start=now - timedelta(days=37),
            current_period_end=now - timedelta(days=7),
            renewal_retry_count=2,
            grace_period_end=now - timedelta(seconds=10),  # Grace period expired
        )
        self.db.add(sub)
        self.db.commit()
        self.db.refresh(sub)

        # Run renewal worker
        res = process_subscription_renewals(self.db)
        self.assertGreaterEqual(res["grace_expired"], 1)

        self.db.refresh(sub)
        self.assertEqual(sub.status, SubscriptionStatus.EXPIRED.value)

    @patch("src.payment.controllers.create_razorpay_order")
    @patch("src.payment.controllers.verify_razorpay_signature")
    def test_04_recovery_from_past_due_via_verify_payment(self, mock_verify_sig, mock_create_rzp_order):
        mock_create_rzp_order.return_value = {"id": "order_recover_dunning_1"}
        mock_verify_sig.return_value = True

        now = datetime.now(timezone.utc)
        sub = SubscriptionModel(
            user_id=self.user.id,
            plan_id=self.plan.id,
            status=SubscriptionStatus.PAST_DUE.value,
            price_amount=self.plan.price_amount,
            currency="INR",
            billing_interval="month",
            interval_count=1,
            current_period_start=now - timedelta(days=32),
            current_period_end=now - timedelta(days=2),
            renewal_retry_count=2,
            grace_period_end=now + timedelta(days=5),
        )
        self.db.add(sub)
        self.db.commit()
        self.db.refresh(sub)

        # 1. Initiate checkout for recovery
        checkout_req = PaymentCheckoutRequestSchema(subscription_id=sub.id)
        checkout_res = initiate_checkout(body=checkout_req, db=self.db, user=self.user)
        self.assertEqual(checkout_res.status, 201)
        order_id = checkout_res.data["razorpay_order_id"]
        payment_id = checkout_res.data["payment_id"]

        # 2. Complete payment
        verify_req = PaymentVerifySchema(
            razorpay_order_id=order_id,
            razorpay_payment_id="pay_recover_999",
            razorpay_signature="dummy_valid_sig",
        )
        verify_res = verify_payment(body=verify_req, db=self.db, user=self.user)
        self.assertEqual(verify_res.status, 200)

        # 3. Verify subscription is restored to ACTIVE and dunning reset
        self.db.refresh(sub)
        self.assertEqual(sub.status, SubscriptionStatus.ACTIVE.value)
        self.assertIsNone(sub.grace_period_end)
        self.assertEqual(sub.renewal_retry_count, 0)

        # 4. Verify invoice has billing_reason="SUBSCRIPTION_CYCLE"
        invoice = self.db.query(InvoiceModel).filter(InvoiceModel.payment_id == payment_id).first()
        self.assertIsNotNone(invoice)
        self.assertEqual(invoice.billing_reason, "SUBSCRIPTION_CYCLE")

    @patch("src.payment.controllers.verify_razorpay_webhook_signature")
    def test_05_webhook_payment_failed_triggers_dunning(self, mock_webhook_sig):
        mock_webhook_sig.return_value = True

        now = datetime.now(timezone.utc)
        sub = SubscriptionModel(
            user_id=self.user.id,
            plan_id=self.plan.id,
            status=SubscriptionStatus.ACTIVE.value,
            price_amount=self.plan.price_amount,
            currency="INR",
            billing_interval="month",
            interval_count=1,
            current_period_start=now - timedelta(days=30),
            current_period_end=now,
            renewal_retry_count=0,
            grace_period_end=None,
        )
        self.db.add(sub)
        self.db.commit()
        self.db.refresh(sub)

        order_id = f"order_dunning_fail_{sub.id}"
        payment = PaymentModel(
            subscription_id=sub.id,
            user_id=self.user.id,
            provider="RAZORPAY",
            provider_order_id=order_id,
            amount=self.plan.price_amount,
            currency="INR",
            status=PaymentStatus.CREATED.value,
        )
        self.db.add(payment)
        self.db.commit()

        # Send payment.failed webhook
        event_id = f"evt_fail_{int(datetime.now().timestamp())}"
        payload = {
            "id": event_id,
            "event": "payment.failed",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_fail_123",
                        "order_id": order_id,
                        "error_description": "Card expired / Insufficient funds",
                    }
                }
            },
        }
        body_bytes = json.dumps(payload).encode("utf-8")

        res = asyncio.run(
            handle_razorpay_webhook(
                request_body=body_bytes,
                signature="dummy_sig",
                db=self.db,
                event_id_header=event_id,
            )
        )
        self.assertEqual(res.get("status"), "ok")

        # Verify payment is marked FAILED and subscription enters PAST_DUE
        self.db.refresh(payment)
        self.db.refresh(sub)
        self.assertEqual(payment.status, PaymentStatus.FAILED.value)
        self.assertEqual(sub.status, SubscriptionStatus.PAST_DUE.value)
        self.assertEqual(sub.renewal_retry_count, 1)
        self.assertIsNotNone(sub.grace_period_end)
