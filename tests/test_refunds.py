import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from src.utils.db import LocalSession
from src.users.models import UserModel
from src.plans_pricing.models import PlanPricingModel
from src.subscription.models import SubscriptionModel, SubscriptionStatus
from src.payment.models import PaymentModel, PaymentStatus, RefundModel, RefundStatus
from src.invoices.models import InvoiceModel
from src.payment.dtos import RefundRequestSchema
from src.payment.controllers import issue_refund, get_payment_refunds


from src.audit_logs.models import AuditLogModel


class TestRefundManagement(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = LocalSession()

        # 1. Admin User
        cls.admin_user = cls.db.query(UserModel).filter(UserModel.email_address == "admin_refund@example.com").first()
        if not cls.admin_user:
            cls.admin_user = UserModel(
                full_name="Admin Refund User",
                email_address="admin_refund@example.com",
                hashed_password="hashed_admin_pw",
                mobile_number="9000000001",
                role="ADMIN",
            )
            cls.db.add(cls.admin_user)
            cls.db.commit()
            cls.db.refresh(cls.admin_user)

        # 2. Customer User
        cls.customer_user = cls.db.query(UserModel).filter(UserModel.email_address == "customer_refund@example.com").first()
        if not cls.customer_user:
            cls.customer_user = UserModel(
                full_name="Customer Refund User",
                email_address="customer_refund@example.com",
                hashed_password="hashed_customer_pw",
                mobile_number="9000000002",
                role="CUSTOMER",
            )
            cls.db.add(cls.customer_user)
            cls.db.commit()
            cls.db.refresh(cls.customer_user)

        # 3. Another Customer (unauthorized)
        cls.other_user = cls.db.query(UserModel).filter(UserModel.email_address == "other_refund@example.com").first()
        if not cls.other_user:
            cls.other_user = UserModel(
                full_name="Other User",
                email_address="other_refund@example.com",
                hashed_password="hashed_other_pw",
                mobile_number="9000000003",
                role="CUSTOMER",
            )
            cls.db.add(cls.other_user)
            cls.db.commit()
            cls.db.refresh(cls.other_user)

        # 4. Plan
        cls.plan = cls.db.query(PlanPricingModel).filter(PlanPricingModel.name == "Refund Test Plan").first()
        if not cls.plan:
            cls.plan = PlanPricingModel(
                name="Refund Test Plan",
                price_amount=100000,  # ₹1000 (100000 paise)
                currency="INR",
                billing_interval="month",
                interval_count=1,
                features=["All Features"],
                is_active=True,
            )
            cls.db.add(cls.plan)
            cls.db.commit()
            cls.db.refresh(cls.plan)

    @classmethod
    def tearDownClass(cls):
        # Cleanup
        user_ids = [cls.admin_user.id, cls.customer_user.id, cls.other_user.id]
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
        if cls.other_user:
            cls.db.delete(cls.other_user)
        cls.db.commit()
        cls.db.close()

    def setUp(self):
        # Create a fresh subscription and successful payment for each test
        now = datetime.now(timezone.utc)
        self.sub = SubscriptionModel(
            user_id=self.customer_user.id,
            plan_id=self.plan.id,
            status=SubscriptionStatus.ACTIVE.value,
            price_amount=100000,
            currency="INR",
            billing_interval="month",
            interval_count=1,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        )
        self.db.add(self.sub)
        self.db.commit()
        self.db.refresh(self.sub)

        self.payment = PaymentModel(
            subscription_id=self.sub.id,
            user_id=self.customer_user.id,
            provider="RAZORPAY",
            provider_order_id=f"order_rf_{self.sub.id}_{int(now.timestamp())}",
            provider_payment_id=f"pay_rf_{self.sub.id}_{int(now.timestamp())}",
            amount=100000,
            currency="INR",
            status=PaymentStatus.SUCCESS.value,
        )
        self.db.add(self.payment)
        self.db.commit()
        self.db.refresh(self.payment)

    def tearDown(self):
        user_ids = [self.admin_user.id, self.customer_user.id, self.other_user.id]
        self.db.query(AuditLogModel).filter(AuditLogModel.user_id.in_(user_ids)).delete(synchronize_session=False)
        self.db.query(RefundModel).filter(RefundModel.user_id.in_(user_ids)).delete(synchronize_session=False)
        self.db.query(InvoiceModel).filter(InvoiceModel.user_id.in_(user_ids)).delete(synchronize_session=False)
        self.db.query(PaymentModel).filter(PaymentModel.user_id.in_(user_ids)).delete(synchronize_session=False)
        self.db.query(SubscriptionModel).filter(SubscriptionModel.user_id.in_(user_ids)).delete(synchronize_session=False)
        self.db.commit()

    @patch("src.payment.controllers.create_razorpay_refund")
    def test_01_customer_cannot_issue_refund_admin_required(self, mock_refund):
        req = RefundRequestSchema(amount=50000, reason="Customer trying to refund")
        res = issue_refund(payment_id=self.payment.id, body=req, db=self.db, user=self.customer_user)
        self.assertEqual(res.status, 403)
        self.assertIn("Only administrators", res.message)
        mock_refund.assert_not_called()

    @patch("src.payment.controllers.create_razorpay_refund")
    def test_02_partial_refund_updates_status_and_preserves_subscription(self, mock_refund):
        mock_refund.return_value = {"id": "rfnd_test_partial_123", "amount": 40000}

        req = RefundRequestSchema(amount=40000, reason="Partial goodwill refund")
        res = issue_refund(payment_id=self.payment.id, body=req, db=self.db, user=self.admin_user)

        self.assertEqual(res.status, 201)
        self.assertEqual(res.data["amount"], 40000)
        self.assertEqual(res.data["status"], RefundStatus.PROCESSED.value)

        # Payment status becomes PARTIALLY_REFUNDED
        self.db.refresh(self.payment)
        self.assertEqual(self.payment.status, PaymentStatus.PARTIALLY_REFUNDED.value)

        # Subscription remains ACTIVE
        self.db.refresh(self.sub)
        self.assertEqual(self.sub.status, SubscriptionStatus.ACTIVE.value)

    @patch("src.payment.controllers.create_razorpay_refund")
    def test_03_refund_amount_exceeding_balance_is_rejected(self, mock_refund):
        # 1. Partial refund of 60000 (leaves 40000)
        mock_refund.return_value = {"id": "rfnd_test_1", "amount": 60000}
        req1 = RefundRequestSchema(amount=60000)
        res1 = issue_refund(payment_id=self.payment.id, body=req1, db=self.db, user=self.admin_user)
        self.assertEqual(res1.status, 201)

        # 2. Attempt to refund 50000 when only 40000 remains
        req2 = RefundRequestSchema(amount=50000)
        res2 = issue_refund(payment_id=self.payment.id, body=req2, db=self.db, user=self.admin_user)
        self.assertEqual(res2.status, 400)
        self.assertIn("exceeds remaining refundable balance", res2.message)

    @patch("src.payment.controllers.create_razorpay_refund")
    def test_04_full_refund_cancels_subscription_access(self, mock_refund):
        mock_refund.return_value = {"id": "rfnd_test_full_456", "amount": 100000}

        # Omit amount to request full refund
        req = RefundRequestSchema(reason="Customer requested full cancellation refund")
        res = issue_refund(payment_id=self.payment.id, body=req, db=self.db, user=self.admin_user)

        self.assertEqual(res.status, 201)
        self.assertEqual(res.data["amount"], 100000)

        # Payment status becomes REFUNDED
        self.db.refresh(self.payment)
        self.assertEqual(self.payment.status, PaymentStatus.REFUNDED.value)

        # Subscription is immediately CANCELLED
        self.db.refresh(self.sub)
        self.assertEqual(self.sub.status, SubscriptionStatus.CANCELLED.value)
        self.assertIsNotNone(self.sub.cancelled_at)

        # Subsequent refund attempt on fully refunded payment is rejected
        res2 = issue_refund(payment_id=self.payment.id, body=req, db=self.db, user=self.admin_user)
        self.assertEqual(res2.status, 400)
        self.assertIn("Only successful or partially refunded payments can be refunded", res2.message)

    @patch("src.payment.controllers.create_razorpay_refund")
    def test_05_get_payment_refunds_and_permissions(self, mock_refund):
        mock_refund.return_value = {"id": "rfnd_list_1", "amount": 30000}
        req = RefundRequestSchema(amount=30000, reason="Test listing refunds")
        issue_refund(payment_id=self.payment.id, body=req, db=self.db, user=self.admin_user)

        # Customer who owns the payment can view its refunds
        res_owner = get_payment_refunds(payment_id=self.payment.id, db=self.db, user=self.customer_user)
        self.assertEqual(res_owner.status, 200)
        self.assertEqual(len(res_owner.data), 1)
        self.assertEqual(res_owner.data[0]["amount"], 30000)

        # Admin can view
        res_admin = get_payment_refunds(payment_id=self.payment.id, db=self.db, user=self.admin_user)
        self.assertEqual(res_admin.status, 200)
        self.assertEqual(len(res_admin.data), 1)

        # Another customer cannot view
        res_other = get_payment_refunds(payment_id=self.payment.id, db=self.db, user=self.other_user)
        self.assertEqual(res_other.status, 403)
