import unittest
from datetime import datetime, timezone, timedelta
from src.utils.db import LocalSession
from src.users.models import UserModel
from src.plans_pricing.models import PlanPricingModel
from src.subscription.models import SubscriptionModel, SubscriptionStatus
from src.payment.models import PaymentModel, PaymentStatus, RefundModel, RefundStatus
from src.invoices.models import InvoiceModel, InvoiceStatus
from src.audit_logs.models import AuditLogModel
from src.analytics import controllers, services


class TestAnalyticsEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = LocalSession()

        # 1. Admin User
        cls.admin_user = cls.db.query(UserModel).filter(UserModel.email_address == "analytics_admin@example.com").first()
        if not cls.admin_user:
            cls.admin_user = UserModel(
                full_name="Analytics Admin",
                email_address="analytics_admin@example.com",
                hashed_password="admin_hashed_pw",
                mobile_number="9900000001",
                role="ADMIN",
            )
            cls.db.add(cls.admin_user)
            cls.db.commit()
            cls.db.refresh(cls.admin_user)

        # 2. Customer User
        cls.customer_user = cls.db.query(UserModel).filter(UserModel.email_address == "analytics_customer@example.com").first()
        if not cls.customer_user:
            cls.customer_user = UserModel(
                full_name="Analytics Customer",
                email_address="analytics_customer@example.com",
                hashed_password="customer_hashed_pw",
                mobile_number="9900000002",
                role="CUSTOMER",
            )
            cls.db.add(cls.customer_user)
            cls.db.commit()
            cls.db.refresh(cls.customer_user)

        # 3. Monthly Plan: ₹500/mo = 50000 paise
        cls.monthly_plan = cls.db.query(PlanPricingModel).filter(PlanPricingModel.name == "Analytics Monthly Plan").first()
        if not cls.monthly_plan:
            cls.monthly_plan = PlanPricingModel(
                name="Analytics Monthly Plan",
                price_amount=50000,
                currency="INR",
                billing_interval="month",
                interval_count=1,
                features=["Monthly Access"],
                is_active=True,
            )
            cls.db.add(cls.monthly_plan)
            cls.db.commit()
            cls.db.refresh(cls.monthly_plan)

        # 4. Yearly Plan: ₹12000/yr = 1200000 paise (monthly normalized = 100000 paise)
        cls.yearly_plan = cls.db.query(PlanPricingModel).filter(PlanPricingModel.name == "Analytics Yearly Plan").first()
        if not cls.yearly_plan:
            cls.yearly_plan = PlanPricingModel(
                name="Analytics Yearly Plan",
                price_amount=1200000,
                currency="INR",
                billing_interval="year",
                interval_count=1,
                features=["Yearly Access"],
                is_active=True,
            )
            cls.db.add(cls.yearly_plan)
            cls.db.commit()
            cls.db.refresh(cls.yearly_plan)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.db.rollback()
            user_ids = [cls.admin_user.id, cls.customer_user.id]
            cls.db.query(AuditLogModel).filter(AuditLogModel.user_id.in_(user_ids)).delete(synchronize_session=False)
            cls.db.query(RefundModel).filter(RefundModel.user_id.in_(user_ids)).delete(synchronize_session=False)
            cls.db.query(InvoiceModel).filter(InvoiceModel.user_id.in_(user_ids)).delete(synchronize_session=False)
            cls.db.query(PaymentModel).filter(PaymentModel.user_id.in_(user_ids)).delete(synchronize_session=False)
            cls.db.query(SubscriptionModel).filter(SubscriptionModel.user_id.in_(user_ids)).delete(synchronize_session=False)
            if cls.monthly_plan:
                cls.db.delete(cls.monthly_plan)
            if cls.yearly_plan:
                cls.db.delete(cls.yearly_plan)
            if cls.admin_user:
                cls.db.delete(cls.admin_user)
            if cls.customer_user:
                cls.db.delete(cls.customer_user)
            cls.db.commit()
        except Exception:
            cls.db.rollback()
        finally:
            cls.db.close()

    def tearDown(self):
        try:
            self.db.rollback()
            user_ids = [self.admin_user.id, self.customer_user.id]
            self.db.query(AuditLogModel).filter(AuditLogModel.user_id.in_(user_ids)).delete(synchronize_session=False)
            self.db.query(RefundModel).filter(RefundModel.user_id.in_(user_ids)).delete(synchronize_session=False)
            self.db.query(InvoiceModel).filter(InvoiceModel.user_id.in_(user_ids)).delete(synchronize_session=False)
            self.db.query(PaymentModel).filter(PaymentModel.user_id.in_(user_ids)).delete(synchronize_session=False)
            self.db.query(SubscriptionModel).filter(SubscriptionModel.user_id.in_(user_ids)).delete(synchronize_session=False)
            self.db.commit()
        except Exception:
            self.db.rollback()

    def test_01_rbac_guard_blocks_non_admin(self):
        res1 = controllers.get_overview_kpis(db=self.db, user=self.customer_user)
        self.assertEqual(res1.status, 403)

        res2 = controllers.get_subscription_metrics(db=self.db, user=self.customer_user)
        self.assertEqual(res2.status, 403)

        res3 = controllers.get_revenue_metrics(db=self.db, user=self.customer_user)
        self.assertEqual(res3.status, 403)

        res4 = controllers.get_churn_metrics(db=self.db, user=self.customer_user)
        self.assertEqual(res4.status, 403)

        res5 = controllers.get_payment_metrics(db=self.db, user=self.customer_user)
        self.assertEqual(res5.status, 403)

    def test_02_mrr_and_arr_normalization(self):
        baseline_mrr, _ = services.calculate_mrr_and_arr(self.db)
        now = datetime.now(timezone.utc)

        # 1 Active monthly sub: 50000 paise/mo
        sub1 = SubscriptionModel(
            user_id=self.customer_user.id,
            plan_id=self.monthly_plan.id,
            status=SubscriptionStatus.ACTIVE.value,
            price_amount=50000,
            currency="INR",
            billing_interval="month",
            interval_count=1,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        )
        # 1 Active yearly sub: 1200000 paise/yr -> 100000 paise/mo
        sub2 = SubscriptionModel(
            user_id=self.customer_user.id,
            plan_id=self.yearly_plan.id,
            status=SubscriptionStatus.ACTIVE.value,
            price_amount=1200000,
            currency="INR",
            billing_interval="year",
            interval_count=1,
            current_period_start=now,
            current_period_end=now + timedelta(days=365),
        )
        # 1 Inactive (cancelled) sub: should NOT be included in MRR
        sub3 = SubscriptionModel(
            user_id=self.customer_user.id,
            plan_id=self.monthly_plan.id,
            status=SubscriptionStatus.CANCELLED.value,
            price_amount=50000,
            currency="INR",
            billing_interval="month",
            interval_count=1,
        )
        self.db.add_all([sub1, sub2, sub3])
        self.db.commit()

        mrr, arr = services.calculate_mrr_and_arr(self.db)
        # Delta should be exactly 50000 + 100000 = 150000 paise
        self.assertEqual(mrr - baseline_mrr, 150000)
        self.assertEqual(arr - (baseline_mrr * 12), 150000 * 12)

    def test_03_subscription_analytics_breakdown(self):
        # Baseline counts
        baseline_res = controllers.get_subscription_metrics(db=self.db, user=self.admin_user)
        baseline_active = baseline_res.data["by_status"].get("ACTIVE", 0)
        baseline_trial = baseline_res.data["by_status"].get("TRIALING", 0)
        baseline_past = baseline_res.data["by_status"].get("PAST_DUE", 0)

        # Add 1 active, 1 trialing, 1 past_due
        sub_act = SubscriptionModel(
            user_id=self.customer_user.id,
            plan_id=self.monthly_plan.id,
            status=SubscriptionStatus.ACTIVE.value,
            price_amount=50000,
            currency="INR",
            billing_interval="month",
            interval_count=1,
        )
        sub_tri = SubscriptionModel(
            user_id=self.customer_user.id,
            plan_id=self.monthly_plan.id,
            status=SubscriptionStatus.TRIALING.value,
            price_amount=50000,
            currency="INR",
            billing_interval="month",
            interval_count=1,
        )
        sub_past = SubscriptionModel(
            user_id=self.customer_user.id,
            plan_id=self.yearly_plan.id,
            status=SubscriptionStatus.PAST_DUE.value,
            price_amount=1200000,
            currency="INR",
            billing_interval="year",
            interval_count=1,
        )
        self.db.add_all([sub_act, sub_tri, sub_past])
        self.db.commit()

        res = controllers.get_subscription_metrics(db=self.db, user=self.admin_user)
        self.assertEqual(res.status, 200)
        data = res.data
        self.assertEqual(data["by_status"]["ACTIVE"], baseline_active + 1)
        self.assertEqual(data["by_status"]["TRIALING"], baseline_trial + 1)
        self.assertEqual(data["by_status"]["PAST_DUE"], baseline_past + 1)

    def test_04_revenue_report_with_refunds(self):
        now = datetime.now(timezone.utc)
        sub = SubscriptionModel(
            user_id=self.customer_user.id,
            plan_id=self.monthly_plan.id,
            status=SubscriptionStatus.ACTIVE.value,
            price_amount=50000,
            currency="INR",
            billing_interval="month",
            interval_count=1,
        )
        self.db.add(sub)
        self.db.commit()
        self.db.refresh(sub)

        # Paid invoice 1: ₹500 (50000 paise)
        inv1 = InvoiceModel(
            invoice_number=f"INV-TEST-01-{int(now.timestamp())}",
            user_id=self.customer_user.id,
            subscription_id=sub.id,
            payment_id=None,
            subtotal=50000,
            tax_amount=0,
            total_amount=50000,
            currency="INR",
            status=InvoiceStatus.PAID.value,
            billing_reason="SUBSCRIPTION_CREATE",
            paid_at=now - timedelta(days=2),
        )
        # Paid invoice 2: ₹1000 (100000 paise)
        inv2 = InvoiceModel(
            invoice_number=f"INV-TEST-02-{int(now.timestamp())}",
            user_id=self.customer_user.id,
            subscription_id=sub.id,
            payment_id=None,
            subtotal=100000,
            tax_amount=0,
            total_amount=100000,
            currency="INR",
            status=InvoiceStatus.PAID.value,
            billing_reason="SUBSCRIPTION_CYCLE",
            paid_at=now - timedelta(days=1),
        )
        self.db.add_all([inv1, inv2])
        self.db.commit()

        # Dummy payment to attach a refund
        pmt = PaymentModel(
            subscription_id=sub.id,
            user_id=self.customer_user.id,
            provider="RAZORPAY",
            provider_order_id=f"ord_test_rev_{int(now.timestamp())}",
            amount=100000,
            currency="INR",
            status=PaymentStatus.SUCCESS.value,
        )
        self.db.add(pmt)
        self.db.commit()
        self.db.refresh(pmt)

        # Refund of ₹300 (30000 paise)
        ref = RefundModel(
            payment_id=pmt.id,
            user_id=self.customer_user.id,
            amount=30000,
            currency="INR",
            status=RefundStatus.PROCESSED.value,
            created_at=now - timedelta(days=1),
        )
        self.db.add(ref)
        self.db.commit()

        # Generate report
        res = controllers.get_revenue_metrics(
            db=self.db, user=self.admin_user, group_by="daily",
            start_date=now - timedelta(days=5), end_date=now + timedelta(days=1)
        )
        self.assertEqual(res.status, 200)
        data = res.data
        self.assertGreaterEqual(data["total_gross_revenue"], 150000)
        self.assertGreaterEqual(data["total_refunded"], 30000)
        self.assertGreaterEqual(data["total_net_revenue"], 120000)
        self.assertGreaterEqual(len(data["breakdown"]), 1)

    def test_05_churn_analytics(self):
        now = datetime.now(timezone.utc)
        sub_active = SubscriptionModel(
            user_id=self.customer_user.id,
            plan_id=self.monthly_plan.id,
            status=SubscriptionStatus.ACTIVE.value,
            price_amount=50000,
            currency="INR",
            billing_interval="month",
            interval_count=1,
        )
        sub_cancelled = SubscriptionModel(
            user_id=self.customer_user.id,
            plan_id=self.monthly_plan.id,
            status=SubscriptionStatus.CANCELLED.value,
            price_amount=50000,
            currency="INR",
            billing_interval="month",
            interval_count=1,
            cancelled_at=now - timedelta(days=3),
        )
        self.db.add_all([sub_active, sub_cancelled])
        self.db.commit()

        res = controllers.get_churn_metrics(
            db=self.db, user=self.admin_user,
            start_date=now - timedelta(days=10), end_date=now
        )
        self.assertEqual(res.status, 200)
        data = res.data
        self.assertGreaterEqual(data["cancellations_count"], 1)
        self.assertGreaterEqual(data["lost_mrr"], 50000)
        self.assertGreater(data["churn_rate_percent"], 0.0)

    def test_06_payment_analytics(self):
        now = datetime.now(timezone.utc)
        sub = SubscriptionModel(
            user_id=self.customer_user.id,
            plan_id=self.monthly_plan.id,
            status=SubscriptionStatus.ACTIVE.value,
            price_amount=50000,
            currency="INR",
            billing_interval="month",
            interval_count=1,
        )
        self.db.add(sub)
        self.db.commit()
        self.db.refresh(sub)

        p1 = PaymentModel(
            subscription_id=sub.id,
            user_id=self.customer_user.id,
            provider="RAZORPAY",
            provider_order_id=f"ord_p1_{int(now.timestamp())}",
            amount=50000,
            currency="INR",
            status=PaymentStatus.SUCCESS.value,
            created_at=now - timedelta(days=2),
        )
        p2 = PaymentModel(
            subscription_id=sub.id,
            user_id=self.customer_user.id,
            provider="RAZORPAY",
            provider_order_id=f"ord_p2_{int(now.timestamp())}",
            amount=50000,
            currency="INR",
            status=PaymentStatus.FAILED.value,
            created_at=now - timedelta(days=1),
        )
        self.db.add_all([p1, p2])
        self.db.commit()

        res = controllers.get_payment_metrics(
            db=self.db, user=self.admin_user,
            start_date=now - timedelta(days=5), end_date=now
        )
        self.assertEqual(res.status, 200)
        data = res.data
        self.assertGreaterEqual(data["successful_count"], 1)
        self.assertGreaterEqual(data["failed_count"], 1)
        self.assertGreaterEqual(data["total_successful_volume"], 50000)

    def test_07_overview_kpis(self):
        res = controllers.get_overview_kpis(db=self.db, user=self.admin_user)
        self.assertEqual(res.status, 200)
        data = res.data
        self.assertIn("mrr", data)
        self.assertIn("arr", data)
        self.assertIn("active_subscriptions", data)
        self.assertIn("gross_revenue_period", data)
        self.assertIn("net_revenue_period", data)
        self.assertIn("churn_rate_percent", data)
