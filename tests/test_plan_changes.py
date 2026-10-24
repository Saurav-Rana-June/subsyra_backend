import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from src.utils.db import LocalSession
from src.users.models import UserModel
from src.plans_pricing.models import PlanPricingModel
from src.subscription.models import SubscriptionModel, SubscriptionStatus
from src.payment.models import PaymentModel, PaymentStatus
from src.invoices.models import InvoiceModel
from src.audit_logs.models import AuditLogModel
from src.subscription.dtos import PlanChangeRequestSchema
from src.subscription.controllers import preview_plan_change, execute_plan_change
from src.payment.dtos import PaymentVerifySchema
from src.payment.controllers import verify_payment
from src.utils.subscription_services import process_subscription_renewals


class TestPlanChangeAndSettlement(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = LocalSession()

        # 1. Test User
        cls.user = cls.db.query(UserModel).filter(UserModel.email_address == "plan_change_test@example.com").first()
        if not cls.user:
            cls.user = UserModel(
                full_name="Plan Change Test User",
                email_address="plan_change_test@example.com",
                hashed_password="hashed_pw_test",
                mobile_number="9876543210",
                role="CUSTOMER",
            )
            cls.db.add(cls.user)
            cls.db.commit()
            cls.db.refresh(cls.user)

        # 2. Basic Plan: ₹500 / month (50000 paise)
        cls.basic_plan = cls.db.query(PlanPricingModel).filter(PlanPricingModel.name == "Test Basic Plan").first()
        if not cls.basic_plan:
            cls.basic_plan = PlanPricingModel(
                name="Test Basic Plan",
                price_amount=50000,
                currency="INR",
                billing_interval="month",
                interval_count=1,
                features=["Basic Support"],
                is_active=True,
            )
            cls.db.add(cls.basic_plan)
            cls.db.commit()
            cls.db.refresh(cls.basic_plan)

        # 3. Pro Plan: ₹1000 / month (100000 paise)
        cls.pro_plan = cls.db.query(PlanPricingModel).filter(PlanPricingModel.name == "Test Pro Plan").first()
        if not cls.pro_plan:
            cls.pro_plan = PlanPricingModel(
                name="Test Pro Plan",
                price_amount=100000,
                currency="INR",
                billing_interval="month",
                interval_count=1,
                features=["Priority Support", "Pro Features"],
                is_active=True,
            )
            cls.db.add(cls.pro_plan)
            cls.db.commit()
            cls.db.refresh(cls.pro_plan)

    @classmethod
    def tearDownClass(cls):
        # Cleanup plans and user
        cls.db.query(AuditLogModel).filter(AuditLogModel.user_id == cls.user.id).delete()
        cls.db.query(InvoiceModel).filter(InvoiceModel.user_id == cls.user.id).delete()
        cls.db.query(PaymentModel).filter(PaymentModel.user_id == cls.user.id).delete()
        cls.db.query(SubscriptionModel).filter(SubscriptionModel.user_id == cls.user.id).delete()
        if cls.basic_plan:
            cls.db.delete(cls.basic_plan)
        if cls.pro_plan:
            cls.db.delete(cls.pro_plan)
        if cls.user:
            cls.db.delete(cls.user)
        cls.db.commit()
        cls.db.close()

    def tearDown(self):
        # Cleanup subscriptions and invoices created during tests
        self.db.query(AuditLogModel).filter(AuditLogModel.user_id == self.user.id).delete()
        self.db.query(InvoiceModel).filter(InvoiceModel.user_id == self.user.id).delete()
        self.db.query(PaymentModel).filter(PaymentModel.user_id == self.user.id).delete()
        self.db.query(SubscriptionModel).filter(SubscriptionModel.user_id == self.user.id).delete()
        self.db.commit()

    def test_01_preview_plan_change(self):
        now = datetime.now(timezone.utc)
        sub = SubscriptionModel(
            user_id=self.user.id,
            plan_id=self.basic_plan.id,
            status=SubscriptionStatus.ACTIVE.value,
            price_amount=self.basic_plan.price_amount,
            currency="INR",
            billing_interval="month",
            interval_count=1,
            current_period_start=now - timedelta(days=15),
            current_period_end=now + timedelta(days=15),
        )
        self.db.add(sub)
        self.db.commit()
        self.db.refresh(sub)

        # Preview upgrade to Pro
        res = preview_plan_change(id=sub.id, new_plan_id=self.pro_plan.id, db=self.db, user=self.user)
        self.assertEqual(res.status, 200)
        data = res.data
        self.assertEqual(data["change_type"], "UPGRADE")
        self.assertGreater(data["net_amount_due"], 0)
        self.assertGreater(data["unused_credit"], 0)

        # Preview downgrade to Basic from Pro
        sub.plan_id = self.pro_plan.id
        sub.price_amount = self.pro_plan.price_amount
        self.db.commit()

        res_down = preview_plan_change(id=sub.id, new_plan_id=self.basic_plan.id, db=self.db, user=self.user)
        self.assertEqual(res_down.status, 200)
        self.assertEqual(res_down.data["change_type"], "DOWNGRADE")
        self.assertEqual(res_down.data["net_amount_due"], 0)

    def test_02_downgrade_scheduled_and_settled_on_renewal(self):
        now = datetime.now(timezone.utc)
        period_end = now + timedelta(days=5)
        sub = SubscriptionModel(
            user_id=self.user.id,
            plan_id=self.pro_plan.id,
            status=SubscriptionStatus.ACTIVE.value,
            price_amount=self.pro_plan.price_amount,
            currency="INR",
            billing_interval="month",
            interval_count=1,
            current_period_start=now - timedelta(days=25),
            current_period_end=period_end,
        )
        self.db.add(sub)
        self.db.commit()
        self.db.refresh(sub)

        # 1. Schedule downgrade to Basic
        req = PlanChangeRequestSchema(new_plan_id=self.basic_plan.id)
        change_res = execute_plan_change(id=sub.id, body=req, db=self.db, user=self.user)
        self.assertEqual(change_res.status, 200)
        self.assertEqual(change_res.data["pending_plan_id"], self.basic_plan.id)

        self.db.refresh(sub)
        self.assertEqual(sub.plan_id, self.pro_plan.id)
        self.assertEqual(sub.pending_plan_id, self.basic_plan.id)

        # 2. Advance time past current_period_end
        sub.current_period_end = now - timedelta(seconds=10)
        self.db.commit()

        # 3. Trigger renewal engine
        renewal_res = process_subscription_renewals(self.db)
        self.assertEqual(renewal_res["renewed"], 1)

        # 4. Verify subscription has now switched to Basic Plan
        self.db.refresh(sub)
        self.assertEqual(sub.plan_id, self.basic_plan.id)
        self.assertEqual(sub.price_amount, self.basic_plan.price_amount)
        self.assertIsNone(sub.pending_plan_id)
        self.assertEqual(sub.status, SubscriptionStatus.ACTIVE.value)

        # Verify renewal invoice was generated for Basic plan amount
        invoice = self.db.query(InvoiceModel).filter(InvoiceModel.subscription_id == sub.id).first()
        self.assertIsNotNone(invoice)
        self.assertEqual(invoice.total_amount, self.basic_plan.price_amount)
        self.assertEqual(invoice.billing_reason, "SUBSCRIPTION_CYCLE")

    @patch("src.subscription.controllers.create_razorpay_order")
    @patch("src.payment.controllers.verify_razorpay_signature")
    def test_03_upgrade_initiated_and_settled_via_verify_payment(self, mock_verify_sig, mock_create_rzp_order):
        mock_create_rzp_order.return_value = {"id": "order_test_upgrade_123"}
        mock_verify_sig.return_value = True

        now = datetime.now(timezone.utc)
        sub = SubscriptionModel(
            user_id=self.user.id,
            plan_id=self.basic_plan.id,
            status=SubscriptionStatus.ACTIVE.value,
            price_amount=self.basic_plan.price_amount,
            currency="INR",
            billing_interval="month",
            interval_count=1,
            current_period_start=now - timedelta(days=15),
            current_period_end=now + timedelta(days=15),
        )
        self.db.add(sub)
        self.db.commit()
        self.db.refresh(sub)
        original_end = sub.current_period_end

        # 1. Execute Upgrade
        req = PlanChangeRequestSchema(new_plan_id=self.pro_plan.id)
        res = execute_plan_change(id=sub.id, body=req, db=self.db, user=self.user)
        self.assertEqual(res.status, 200)
        self.db.refresh(sub)
        self.assertEqual(sub.pending_plan_id, self.pro_plan.id)
        self.assertEqual(sub.plan_id, self.basic_plan.id)

        payment_id = res.data["payment_id"]
        order_id = res.data["razorpay_order_id"]

        # 2. Verify Payment (customer completes checkout)
        verify_req = PaymentVerifySchema(
            razorpay_order_id=order_id,
            razorpay_payment_id="pay_test_upgrade_999",
            razorpay_signature="dummy_valid_sig",
        )
        v_res = verify_payment(body=verify_req, db=self.db, user=self.user)
        self.assertEqual(v_res.status, 200)

        # 3. Verify settlement in DB
        self.db.refresh(sub)
        self.assertEqual(sub.plan_id, self.pro_plan.id)
        self.assertEqual(sub.price_amount, self.pro_plan.price_amount)
        self.assertIsNone(sub.pending_plan_id)
        self.assertEqual(sub.status, SubscriptionStatus.ACTIVE.value)
        # Period end should be retained for current cycle
        self.assertEqual(sub.current_period_end, original_end)

        # Verify upgrade invoice was created with billing_reason PLAN_UPGRADE
        invoice = self.db.query(InvoiceModel).filter(InvoiceModel.payment_id == payment_id).first()
        self.assertIsNotNone(invoice)
        self.assertEqual(invoice.billing_reason, "PLAN_UPGRADE")
        self.assertEqual(invoice.total_amount, res.data["prorated_amount"])

    @patch("src.subscription.controllers.create_razorpay_order")
    @patch("src.payment.controllers.verify_razorpay_webhook_signature")
    def test_04_upgrade_settled_via_webhook(self, mock_webhook_sig, mock_create_rzp_order):
        import asyncio
        import json
        from src.payment.controllers import handle_razorpay_webhook

        mock_create_rzp_order.return_value = {"id": "order_webhook_upg_456"}
        mock_webhook_sig.return_value = True

        now = datetime.now(timezone.utc)
        sub = SubscriptionModel(
            user_id=self.user.id,
            plan_id=self.basic_plan.id,
            status=SubscriptionStatus.ACTIVE.value,
            price_amount=self.basic_plan.price_amount,
            currency="INR",
            billing_interval="month",
            interval_count=1,
            current_period_start=now - timedelta(days=10),
            current_period_end=now + timedelta(days=20),
        )
        self.db.add(sub)
        self.db.commit()
        self.db.refresh(sub)
        original_end = sub.current_period_end

        # 1. Initiate Upgrade
        req = PlanChangeRequestSchema(new_plan_id=self.pro_plan.id)
        res = execute_plan_change(id=sub.id, body=req, db=self.db, user=self.user)
        self.assertEqual(res.status, 200)
        payment_id = res.data["payment_id"]
        order_id = res.data["razorpay_order_id"]
        prorated_amount = res.data["prorated_amount"]

        # 2. Simulate Razorpay payment.captured webhook payload
        event_id = f"evt_upg_{int(datetime.now().timestamp())}"
        payload = {
            "id": event_id,
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_webhook_upg_789",
                        "order_id": order_id,
                        "amount": prorated_amount,
                        "currency": "INR",
                        "status": "captured",
                    }
                }
            },
        }
        body_bytes = json.dumps(payload).encode("utf-8")

        webhook_res = asyncio.run(
            handle_razorpay_webhook(
                request_body=body_bytes,
                signature="dummy_sig",
                db=self.db,
                event_id_header=event_id,
            )
        )
        self.assertEqual(webhook_res.get("status"), "ok")

        # 3. Verify settlement in DB
        self.db.refresh(sub)
        self.assertEqual(sub.plan_id, self.pro_plan.id)
        self.assertEqual(sub.price_amount, self.pro_plan.price_amount)
        self.assertIsNone(sub.pending_plan_id)
        self.assertEqual(sub.status, SubscriptionStatus.ACTIVE.value)
        self.assertEqual(sub.current_period_end, original_end)

        # 4. Verify upgrade invoice was created with billing_reason PLAN_UPGRADE
        invoice = self.db.query(InvoiceModel).filter(InvoiceModel.payment_id == payment_id).first()
        self.assertIsNotNone(invoice)
        self.assertEqual(invoice.billing_reason, "PLAN_UPGRADE")
        self.assertEqual(invoice.total_amount, prorated_amount)
