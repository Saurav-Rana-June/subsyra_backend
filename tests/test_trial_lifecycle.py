import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from src.utils.db import LocalSession
from src.users.models import UserModel
from src.plans_pricing.models import PlanPricingModel
from src.subscription.models import SubscriptionModel, SubscriptionStatus
from src.payment.models import PaymentModel
from src.invoices.models import InvoiceModel
from src.subscription.dtos import SubscriptionCreateSchema
from src.subscription.controllers import create_subscription
from src.payment.dtos import PaymentCheckoutRequestSchema, PaymentVerifySchema
from src.payment.controllers import initiate_checkout, verify_payment
from src.utils.subscription_services import process_subscription_renewals


class TestFreeTrialLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = LocalSession()

        # 1. Test User
        cls.user = cls.db.query(UserModel).filter(UserModel.email_address == "trial_test_user@example.com").first()
        if not cls.user:
            cls.user = UserModel(
                full_name="Trial Test User",
                email_address="trial_test_user@example.com",
                hashed_password="hashed_pw_test",
                mobile_number="9123456780",
                role="CUSTOMER",
            )
            cls.db.add(cls.user)
            cls.db.commit()
            cls.db.refresh(cls.user)

        # 2. Plan WITH a 14-day trial
        cls.trial_plan = cls.db.query(PlanPricingModel).filter(PlanPricingModel.name == "Test Trial Plan").first()
        if not cls.trial_plan:
            cls.trial_plan = PlanPricingModel(
                name="Test Trial Plan",
                price_amount=79900,
                currency="INR",
                billing_interval="month",
                interval_count=1,
                features=["All Pro Features during trial"],
                trial_period_days=14,
                is_active=True,
            )
            cls.db.add(cls.trial_plan)
            cls.db.commit()
            cls.db.refresh(cls.trial_plan)

        # 3. Plan WITHOUT trial (0 days)
        cls.no_trial_plan = cls.db.query(PlanPricingModel).filter(PlanPricingModel.name == "Test No-Trial Plan").first()
        if not cls.no_trial_plan:
            cls.no_trial_plan = PlanPricingModel(
                name="Test No-Trial Plan",
                price_amount=49900,
                currency="INR",
                billing_interval="month",
                interval_count=1,
                features=["Basic Access"],
                trial_period_days=0,
                is_active=True,
            )
            cls.db.add(cls.no_trial_plan)
            cls.db.commit()
            cls.db.refresh(cls.no_trial_plan)

    @classmethod
    def tearDownClass(cls):
        cls.db.query(InvoiceModel).filter(InvoiceModel.user_id == cls.user.id).delete()
        cls.db.query(PaymentModel).filter(PaymentModel.user_id == cls.user.id).delete()
        cls.db.query(SubscriptionModel).filter(SubscriptionModel.user_id == cls.user.id).delete()
        if cls.trial_plan:
            cls.db.delete(cls.trial_plan)
        if cls.no_trial_plan:
            cls.db.delete(cls.no_trial_plan)
        if cls.user:
            cls.db.delete(cls.user)
        cls.db.commit()
        cls.db.close()

    def tearDown(self):
        self.db.query(InvoiceModel).filter(InvoiceModel.user_id == self.user.id).delete()
        self.db.query(PaymentModel).filter(PaymentModel.user_id == self.user.id).delete()
        self.db.query(SubscriptionModel).filter(SubscriptionModel.user_id == self.user.id).delete()
        self.db.commit()

    def test_01_create_subscription_grants_free_trial(self):
        body = SubscriptionCreateSchema(plan_id=self.trial_plan.id)
        res = create_subscription(body=body, db=self.db, user=self.user)

        self.assertEqual(res.status, 201)
        self.assertIn("14-day free trial", res.message)
        data = res.data
        self.assertEqual(data["status"], SubscriptionStatus.TRIALING.value)
        self.assertIsNotNone(data["trial_start"])
        self.assertIsNotNone(data["trial_end"])
        self.assertEqual(data["current_period_end"], data["trial_end"])

    def test_02_abuse_prevention_denies_second_trial(self):
        # First subscription gets the trial
        body = SubscriptionCreateSchema(plan_id=self.trial_plan.id)
        res1 = create_subscription(body=body, db=self.db, user=self.user)
        self.assertEqual(res1.status, 201)
        self.assertEqual(res1.data["status"], SubscriptionStatus.TRIALING.value)

        # Second attempt for the same plan by the same user
        res2 = create_subscription(body=body, db=self.db, user=self.user)
        self.assertEqual(res2.status, 201)
        self.assertEqual(res2.data["status"], SubscriptionStatus.PENDING_PAYMENT.value)
        self.assertIn("Trial already redeemed", res2.message)
        self.assertIsNone(res2.data["trial_start"])

    def test_03_create_subscription_without_trial_sets_pending_payment(self):
        body = SubscriptionCreateSchema(plan_id=self.no_trial_plan.id)
        res = create_subscription(body=body, db=self.db, user=self.user)

        self.assertEqual(res.status, 201)
        self.assertEqual(res.data["status"], SubscriptionStatus.PENDING_PAYMENT.value)
        self.assertIsNone(res.data["trial_start"])

    def test_04_trial_expiration_worker(self):
        now = datetime.now(timezone.utc)
        sub = SubscriptionModel(
            user_id=self.user.id,
            plan_id=self.trial_plan.id,
            status=SubscriptionStatus.TRIALING.value,
            price_amount=self.trial_plan.price_amount,
            currency="INR",
            billing_interval="month",
            interval_count=1,
            trial_start=now - timedelta(days=15),
            trial_end=now - timedelta(days=1),  # Expired yesterday
            current_period_start=now - timedelta(days=15),
            current_period_end=now - timedelta(days=1),
        )
        self.db.add(sub)
        self.db.commit()
        self.db.refresh(sub)

        # Run renewals worker
        result = process_subscription_renewals(self.db)
        self.assertGreaterEqual(result["trials_expired"], 1)

        self.db.refresh(sub)
        self.assertEqual(sub.status, SubscriptionStatus.EXPIRED.value)

    @patch("src.payment.controllers.create_razorpay_order")
    @patch("src.payment.controllers.verify_razorpay_signature")
    def test_05_trial_conversion_to_paid_active(self, mock_verify_sig, mock_create_rzp_order):
        mock_create_rzp_order.return_value = {"id": "order_convert_trial_123"}
        mock_verify_sig.return_value = True

        now = datetime.now(timezone.utc)
        sub = SubscriptionModel(
            user_id=self.user.id,
            plan_id=self.trial_plan.id,
            status=SubscriptionStatus.TRIALING.value,
            price_amount=self.trial_plan.price_amount,
            currency="INR",
            billing_interval="month",
            interval_count=1,
            trial_start=now,
            trial_end=now + timedelta(days=14),
            current_period_start=now,
            current_period_end=now + timedelta(days=14),
        )
        self.db.add(sub)
        self.db.commit()
        self.db.refresh(sub)

        # 1. Trialing user initiates checkout
        checkout_req = PaymentCheckoutRequestSchema(subscription_id=sub.id)
        checkout_res = initiate_checkout(body=checkout_req, db=self.db, user=self.user)
        self.assertEqual(checkout_res.status, 201)
        order_id = checkout_res.data["razorpay_order_id"]

        # 2. Customer completes checkout and verifies payment
        verify_req = PaymentVerifySchema(
            razorpay_order_id=order_id,
            razorpay_payment_id="pay_convert_trial_456",
            razorpay_signature="dummy_valid_sig",
        )
        verify_res = verify_payment(body=verify_req, db=self.db, user=self.user)
        self.assertEqual(verify_res.status, 200)

        # 3. Subscription status converts from TRIALING to ACTIVE
        self.db.refresh(sub)
        self.assertEqual(sub.status, SubscriptionStatus.ACTIVE.value)

        # 4. Invoice was generated for subscription creation
        invoice = self.db.query(InvoiceModel).filter(InvoiceModel.subscription_id == sub.id).first()
        self.assertIsNotNone(invoice)
        self.assertEqual(invoice.billing_reason, "SUBSCRIPTION_CREATE")
        self.assertEqual(invoice.total_amount, self.trial_plan.price_amount)
