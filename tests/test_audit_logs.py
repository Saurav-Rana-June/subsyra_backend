import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from fastapi.testclient import TestClient

from main import app
from src.utils.db import LocalSession
from src.users.models import UserModel
from src.plans_pricing.models import PlanPricingModel
from src.subscription.models import SubscriptionModel, SubscriptionStatus
from src.payment.models import PaymentModel, PaymentStatus, RefundModel
from src.invoices.models import InvoiceModel
from src.audit_logs.models import AuditLogModel
from src.audit_logs.services import record_audit_log
from src.subscription.controllers import cancel_subscription
from src.payment.dtos import RefundRequestSchema
from src.payment.controllers import issue_refund


class TestAuditLogs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.db = LocalSession()

        # 1. Admin User
        cls.admin_user = cls.db.query(UserModel).filter(UserModel.email_address == "admin_audit_test@example.com").first()
        if not cls.admin_user:
            cls.admin_user = UserModel(
                full_name="Admin Audit",
                email_address="admin_audit_test@example.com",
                hashed_password="dummy_admin_pw",
                mobile_number="9870000001",
                role="ADMIN",
            )
            cls.db.add(cls.admin_user)
            cls.db.commit()
            cls.db.refresh(cls.admin_user)

        # 2. Customer User
        cls.customer_user = cls.db.query(UserModel).filter(UserModel.email_address == "customer_audit_test@example.com").first()
        if not cls.customer_user:
            cls.customer_user = UserModel(
                full_name="Customer Audit",
                email_address="customer_audit_test@example.com",
                hashed_password="dummy_customer_pw",
                mobile_number="9870000002",
                role="CUSTOMER",
            )
            cls.db.add(cls.customer_user)
            cls.db.commit()
            cls.db.refresh(cls.customer_user)

        # 3. Plan
        cls.plan = cls.db.query(PlanPricingModel).filter(PlanPricingModel.name == "Audit Test Plan").first()
        if not cls.plan:
            cls.plan = PlanPricingModel(
                name="Audit Test Plan",
                price_amount=50000,
                currency="INR",
                billing_interval="month",
                interval_count=1,
                features=["Audit Feature"],
                is_active=True,
            )
            cls.db.add(cls.plan)
            cls.db.commit()
            cls.db.refresh(cls.plan)

    @classmethod
    def tearDownClass(cls):
        user_ids = [cls.admin_user.id, cls.customer_user.id]
        cls.db.query(AuditLogModel).filter(AuditLogModel.user_id.in_(user_ids)).delete(synchronize_session=False)
        cls.db.query(RefundModel).filter(RefundModel.user_id.in_(user_ids)).delete(synchronize_session=False)
        cls.db.query(InvoiceModel).filter(InvoiceModel.user_id.in_(user_ids)).delete(synchronize_session=False)
        cls.db.query(PaymentModel).filter(PaymentModel.user_id.in_(user_ids)).delete(synchronize_session=False)
        cls.db.query(SubscriptionModel).filter(SubscriptionModel.user_id.in_(user_ids)).delete(synchronize_session=False)
        if cls.plan:
            cls.db.delete(cls.plan)
        if cls.admin_user:
            cls.db.delete(cls.admin_user)
        if cls.customer_user:
            cls.db.delete(cls.customer_user)
        cls.db.commit()
        cls.db.close()

    def tearDown(self):
        user_ids = [self.admin_user.id, self.customer_user.id]
        self.db.query(AuditLogModel).filter(AuditLogModel.user_id.in_(user_ids)).delete(synchronize_session=False)
        self.db.query(RefundModel).filter(RefundModel.user_id.in_(user_ids)).delete(synchronize_session=False)
        self.db.query(InvoiceModel).filter(InvoiceModel.user_id.in_(user_ids)).delete(synchronize_session=False)
        self.db.query(PaymentModel).filter(PaymentModel.user_id.in_(user_ids)).delete(synchronize_session=False)
        self.db.query(SubscriptionModel).filter(SubscriptionModel.user_id.in_(user_ids)).delete(synchronize_session=False)
        self.db.commit()

    def test_01_record_audit_log_persists_details(self):
        log = record_audit_log(
            db=self.db,
            action="TEST_ACTION",
            target_type="TEST_TARGET",
            target_id=123,
            user_id=self.admin_user.id,
            details={"ip": "127.0.0.1", "note": "manual audit test"},
        )
        self.assertIsNotNone(log.id)
        self.assertEqual(log.action, "TEST_ACTION")
        self.assertEqual(log.details["note"], "manual audit test")

        # Verify from DB
        fetched = self.db.query(AuditLogModel).filter(AuditLogModel.id == log.id).first()
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.action, "TEST_ACTION")

    def test_02_subscription_cancellation_records_audit_log(self):
        now = datetime.now(timezone.utc)
        sub = SubscriptionModel(
            user_id=self.customer_user.id,
            plan_id=self.plan.id,
            status=SubscriptionStatus.ACTIVE.value,
            price_amount=self.plan.price_amount,
            currency="INR",
            billing_interval="month",
            interval_count=1,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        )
        self.db.add(sub)
        self.db.commit()
        self.db.refresh(sub)

        # Cancel subscription
        res = cancel_subscription(id=sub.id, db=self.db, user=self.customer_user)
        self.assertEqual(res.status, 200)

        # Verify audit log was created
        log = (
            self.db.query(AuditLogModel)
            .filter(
                AuditLogModel.action == "CANCEL_SUBSCRIPTION",
                AuditLogModel.target_id == sub.id,
            )
            .first()
        )
        self.assertIsNotNone(log)
        self.assertEqual(log.user_id, self.customer_user.id)
        self.assertEqual(log.target_type, "SUBSCRIPTION")
        self.assertTrue(log.details["cancel_at_period_end"])

    @patch("src.payment.controllers.create_razorpay_refund")
    def test_03_refund_issuance_records_audit_log(self, mock_refund):
        mock_refund.return_value = {"id": "rfnd_audit_test_99", "amount": 50000}

        now = datetime.now(timezone.utc)
        sub = SubscriptionModel(
            user_id=self.customer_user.id,
            plan_id=self.plan.id,
            status=SubscriptionStatus.ACTIVE.value,
            price_amount=self.plan.price_amount,
            currency="INR",
            billing_interval="month",
            interval_count=1,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        )
        self.db.add(sub)
        self.db.commit()

        payment = PaymentModel(
            subscription_id=sub.id,
            user_id=self.customer_user.id,
            provider="RAZORPAY",
            provider_order_id=f"order_audit_{int(now.timestamp())}",
            provider_payment_id=f"pay_audit_{int(now.timestamp())}",
            amount=50000,
            currency="INR",
            status=PaymentStatus.SUCCESS.value,
        )
        self.db.add(payment)
        self.db.commit()
        self.db.refresh(payment)

        # Admin issues refund
        req = RefundRequestSchema(amount=50000, reason="Audit check refund")
        res = issue_refund(payment_id=payment.id, body=req, db=self.db, user=self.admin_user)
        self.assertEqual(res.status, 201)

        # Verify audit log
        log = (
            self.db.query(AuditLogModel)
            .filter(
                AuditLogModel.action == "ISSUE_REFUND",
                AuditLogModel.target_id == payment.id,
            )
            .first()
        )
        self.assertIsNotNone(log)
        self.assertEqual(log.user_id, self.admin_user.id)
        self.assertEqual(log.target_type, "PAYMENT")
        self.assertEqual(log.details["reason"], "Audit check refund")
        self.assertTrue(log.details["is_full_refund"])
