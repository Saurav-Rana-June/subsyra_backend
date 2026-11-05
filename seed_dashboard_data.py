"""
Subsyra Dashboard Seed Script.

Populates realistic prototype and test data across:
- Users (Admin + multiple Customers)
- Plans & Pricing (Starter Pro, Growth Plan, Pro Tier, Enterprise Annual)
- Subscriptions (Active, Trialing, Past Due, Cancelled, Expired)
- Payments & Refunds (Captured transactions, failed renewal, partial refund)
- Invoices (Paid, Uncollectible / Overdue)
- Audit Logs
"""

import sys
import os
from datetime import datetime, timezone, timedelta

# Ensure local backend imports resolve properly
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

from src.utils.db import LocalSession
from src.utils.helpers import get_hashed_password
from src.users.models import UserModel, UserRole
from src.plans_pricing.models import PlanPricingModel
from src.subscription.models import SubscriptionModel, SubscriptionStatus
from src.payment.models import PaymentModel, PaymentStatus, RefundModel, RefundStatus
from src.invoices.models import InvoiceModel, InvoiceStatus
from src.audit_logs.models import AuditLogModel


def seed_database():
    db = LocalSession()
    now = datetime.now(timezone.utc)

    print("[*] Starting Subsyra Dashboard Database Seeding...")

    try:
        # =====================================================================
        # 1. SEED USERS
        # =====================================================================
        admin_pwd_hash = get_hashed_password("Admin@123")
        customer_pwd_hash = get_hashed_password("password123")

        # Migrate legacy test email if present
        legacy_saurav = db.query(UserModel).filter(UserModel.email_address == "saurav@testing.com").first()
        if legacy_saurav:
            legacy_saurav.email_address = "saurav@subsyra.com"
            legacy_saurav.full_name = "Saurav Rana"
            legacy_saurav.hashed_password = customer_pwd_hash
            db.flush()
            print("  * Migrated legacy saurav@testing.com -> saurav@subsyra.com")

        users_spec = [
            {
                "email": "admin@subsyra.com",
                "name": "Admin User",
                "mobile": "9876543210",
                "role": UserRole.ADMIN.value,
                "hashed_password": admin_pwd_hash,
                "address": "Subsyra HQ, Tower 4, Bengaluru, India",
            },
            {
                "email": "saurav@subsyra.com",
                "name": "Saurav Rana",
                "mobile": "9000000000",
                "role": UserRole.CUSTOMER.value,
                "hashed_password": customer_pwd_hash,
                "address": "12 Sector 14, Chandigarh, India",
            },
            {
                "email": "aarav@northwind.example",
                "name": "Northwind Labs",
                "mobile": "9876543211",
                "role": UserRole.CUSTOMER.value,
                "address": "14 MG Road, Bengaluru, India",
            },
            {
                "email": "diya@acme-studio.example",
                "name": "Acme Studio",
                "mobile": "9123456780",
                "role": UserRole.CUSTOMER.value,
                "address": "22 Park Street, Kolkata, India",
            },
            {
                "email": "ishita@brightloop.example",
                "name": "Brightloop Co.",
                "mobile": "9001122334",
                "role": UserRole.CUSTOMER.value,
                "address": "31 Marine Drive, Kochi, India",
            },
            {
                "email": "kabir@orbithealth.example",
                "name": "Orbit Health",
                "mobile": "9988776655",
                "role": UserRole.CUSTOMER.value,
                "address": "7 Linking Road, Mumbai, India",
            },
            {
                "email": "lumen@media.example",
                "name": "Lumen Media",
                "mobile": "9811223344",
                "role": UserRole.CUSTOMER.value,
                "address": "45 Residency Road, Pune, India",
            },
            {
                "email": "pinecrest@retail.example",
                "name": "Pinecrest Retail",
                "mobile": "9877665544",
                "role": UserRole.CUSTOMER.value,
                "address": "88 Anna Salai, Chennai, India",
            },
            {
                "email": "vantage@cloud.example",
                "name": "Vantage Cloud",
                "mobile": "9855443322",
                "role": UserRole.CUSTOMER.value,
                "address": "19 Hitec City, Hyderabad, India",
            },
            {
                "email": "rohan@startup.example",
                "name": "Rohan Verma",
                "mobile": "9844332211",
                "role": UserRole.CUSTOMER.value,
                "address": "5 Nehru Place, New Delhi, India",
            },
            {
                "email": "ananya@design.example",
                "name": "Ananya Gupta",
                "mobile": "9833221100",
                "role": UserRole.CUSTOMER.value,
                "address": "10 Koramangala, Bengaluru, India",
            },
        ]

        users_by_email = {}
        for spec in users_spec:
            user = db.query(UserModel).filter(UserModel.email_address == spec["email"]).first()
            if not user:
                user = UserModel(
                    full_name=spec["name"],
                    email_address=spec["email"],
                    hashed_password=spec.get("hashed_password", customer_pwd_hash),
                    mobile_number=spec["mobile"],
                    role=spec["role"],
                    address=spec["address"],
                )
                db.add(user)
                db.flush()
                print(f"  + Created User: {spec['name']} ({spec['email']}) [{spec['role']}]")
            else:
                user.role = spec["role"]
                user.full_name = spec["name"]
                if "hashed_password" in spec:
                    user.hashed_password = spec["hashed_password"]
                db.flush()
                print(f"  * Updated User: {spec['name']} ({spec['email']}) [{spec['role']}]")
            users_by_email[spec["email"]] = user

        db.commit()

        # =====================================================================
        # 2. SEED PLANS & PRICING
        # =====================================================================
        plans_spec = [
            {
                "name": "Starter Pro",
                "description": "Essential subscription tier for small projects and growing startups",
                "price_amount": 49900,  # ₹499.00
                "currency": "INR",
                "billing_interval": "month",
                "interval_count": 1,
                "trial_period_days": 14,
                "is_active": True,
                "features": {
                    "max_projects": 5,
                    "team_members": 2,
                    "custom_domain": False,
                    "api_rate_limit": 1000,
                },
            },
            {
                "name": "Growth Plan",
                "description": "Designed for scaling businesses with advanced integrations and priority queues",
                "price_amount": 176882,  # ₹1,768.82
                "currency": "INR",
                "billing_interval": "month",
                "interval_count": 1,
                "trial_period_days": 0,
                "is_active": True,
                "features": {
                    "max_projects": 25,
                    "team_members": 10,
                    "custom_domain": True,
                    "api_rate_limit": 10000,
                },
            },
            {
                "name": "Pro Tier",
                "description": "Power features with granular role-based permissions and high throughput",
                "price_amount": 199900,  # ₹1,999.00
                "currency": "INR",
                "billing_interval": "month",
                "interval_count": 1,
                "trial_period_days": 7,
                "is_active": True,
                "features": {
                    "max_projects": 50,
                    "team_members": 25,
                    "custom_domain": True,
                    "api_rate_limit": 50000,
                },
            },
            {
                "name": "Enterprise Annual",
                "description": "Custom enterprise contract with dedicated account manager and 99.99% SLA",
                "price_amount": 4999900,  # ₹49,999.00
                "currency": "INR",
                "billing_interval": "year",
                "interval_count": 1,
                "trial_period_days": 0,
                "is_active": True,
                "features": {
                    "max_projects": 9999,
                    "team_members": 999,
                    "custom_domain": True,
                    "api_rate_limit": 1000000,
                    "dedicated_sla": True,
                },
            },
        ]

        plans_by_name = {}
        for spec in plans_spec:
            plan = db.query(PlanPricingModel).filter(PlanPricingModel.name == spec["name"]).first()
            if not plan:
                plan = PlanPricingModel(
                    name=spec["name"],
                    description=spec["description"],
                    price_amount=spec["price_amount"],
                    currency=spec["currency"],
                    billing_interval=spec["billing_interval"],
                    interval_count=spec["interval_count"],
                    trial_period_days=spec["trial_period_days"],
                    is_active=spec["is_active"],
                    features=spec["features"],
                )
                db.add(plan)
                db.flush()
                print(f"  + Created Plan: {spec['name']} (₹{spec['price_amount']/100:.2f}/{spec['billing_interval']})")
            else:
                plans_by_name[spec["name"]] = plan
                print(f"  * Existing Plan: {spec['name']}")
            plans_by_name[spec["name"]] = plan

        db.commit()

        # =====================================================================
        # 3. SEED SUBSCRIPTIONS
        # =====================================================================
        # Clean existing test subscriptions to avoid duplicate test clutter
        db.query(RefundModel).delete()
        db.query(InvoiceModel).delete()
        db.query(PaymentModel).delete()
        db.query(SubscriptionModel).delete()
        db.commit()

        starter_plan = plans_by_name["Starter Pro"]
        growth_plan = plans_by_name["Growth Plan"]
        pro_plan = plans_by_name["Pro Tier"]
        enterprise_plan = plans_by_name["Enterprise Annual"]

        subs_spec = [
            # 1. Saurav Rana (Customer hero subscriber)
            {
                "user": users_by_email["saurav@subsyra.com"],
                "plan": growth_plan,
                "status": SubscriptionStatus.ACTIVE.value,
                "start": now - timedelta(days=11),
                "end": now + timedelta(days=19),
                "trial_start": None,
                "trial_end": None,
                "cancel_at_period_end": False,
            },
            # 2. Northwind Labs
            {
                "user": users_by_email["aarav@northwind.example"],
                "plan": enterprise_plan,
                "status": SubscriptionStatus.ACTIVE.value,
                "start": now - timedelta(days=60),
                "end": now + timedelta(days=305),
                "trial_start": None,
                "trial_end": None,
                "cancel_at_period_end": False,
            },
            # 3. Acme Studio
            {
                "user": users_by_email["diya@acme-studio.example"],
                "plan": pro_plan,
                "status": SubscriptionStatus.ACTIVE.value,
                "start": now - timedelta(days=11),
                "end": now + timedelta(days=19),
                "trial_start": None,
                "trial_end": None,
                "cancel_at_period_end": False,
            },
            # 4. Brightloop Co. (Free trial active)
            {
                "user": users_by_email["ishita@brightloop.example"],
                "plan": starter_plan,
                "status": SubscriptionStatus.TRIALING.value,
                "start": now - timedelta(days=5),
                "end": now + timedelta(days=9),
                "trial_start": now - timedelta(days=5),
                "trial_end": now + timedelta(days=9),
                "cancel_at_period_end": False,
            },
            # 5. Orbit Health (Past Due grace period)
            {
                "user": users_by_email["kabir@orbithealth.example"],
                "plan": pro_plan,
                "status": SubscriptionStatus.PAST_DUE.value,
                "start": now - timedelta(days=32),
                "end": now - timedelta(days=2),
                "trial_start": None,
                "trial_end": None,
                "cancel_at_period_end": False,
                "grace_period_end": now + timedelta(days=5),
            },
            # 6. Lumen Media (Cancelled - ends soon)
            {
                "user": users_by_email["lumen@media.example"],
                "plan": starter_plan,
                "status": SubscriptionStatus.CANCELLED.value,
                "start": now - timedelta(days=28),
                "end": now - timedelta(days=2),
                "trial_start": None,
                "trial_end": None,
                "cancel_at_period_end": True,
                "cancelled_at": now - timedelta(days=10),
            },
            # 7. Pinecrest Retail
            {
                "user": users_by_email["pinecrest@retail.example"],
                "plan": growth_plan,
                "status": SubscriptionStatus.ACTIVE.value,
                "start": now - timedelta(days=15),
                "end": now + timedelta(days=15),
                "trial_start": None,
                "trial_end": None,
                "cancel_at_period_end": False,
            },
            # 8. Vantage Cloud (Expired)
            {
                "user": users_by_email["vantage@cloud.example"],
                "plan": starter_plan,
                "status": SubscriptionStatus.EXPIRED.value,
                "start": now - timedelta(days=70),
                "end": now - timedelta(days=40),
                "trial_start": None,
                "trial_end": None,
                "cancel_at_period_end": True,
            },
            # 9. Rohan Verma
            {
                "user": users_by_email["rohan@startup.example"],
                "plan": starter_plan,
                "status": SubscriptionStatus.ACTIVE.value,
                "start": now - timedelta(days=8),
                "end": now + timedelta(days=22),
                "trial_start": None,
                "trial_end": None,
                "cancel_at_period_end": False,
            },
            # 10. Ananya Gupta (Trialing)
            {
                "user": users_by_email["ananya@design.example"],
                "plan": pro_plan,
                "status": SubscriptionStatus.TRIALING.value,
                "start": now - timedelta(days=2),
                "end": now + timedelta(days=5),
                "trial_start": now - timedelta(days=2),
                "trial_end": now + timedelta(days=5),
                "cancel_at_period_end": False,
            },
        ]

        created_subs = []
        for s in subs_spec:
            sub = SubscriptionModel(
                user_id=s["user"].id,
                plan_id=s["plan"].id,
                status=s["status"],
                price_amount=s["plan"].price_amount,
                currency=s["plan"].currency,
                billing_interval=s["plan"].billing_interval,
                interval_count=s["plan"].interval_count,
                current_period_start=s["start"],
                current_period_end=s["end"],
                cancel_at_period_end=s.get("cancel_at_period_end", False),
                cancelled_at=s.get("cancelled_at"),
                trial_start=s.get("trial_start"),
                trial_end=s.get("trial_end"),
                grace_period_end=s.get("grace_period_end"),
            )
            db.add(sub)
            db.flush()
            created_subs.append((sub, s["user"], s["plan"]))
            print(f"  + Subscription #{sub.id}: {s['user'].full_name} -> {s['plan'].name} [{s['status']}]")

        db.commit()

        # =====================================================================
        # 4. SEED PAYMENTS & REFUNDS
        # =====================================================================
        payments_by_sub = {}
        for sub, user, plan in created_subs:
            if sub.status in [SubscriptionStatus.ACTIVE.value, SubscriptionStatus.CANCELLED.value]:
                payment = PaymentModel(
                    subscription_id=sub.id,
                    user_id=user.id,
                    provider="RAZORPAY",
                    provider_order_id=f"order_seed_{sub.id}_{int(now.timestamp())}",
                    provider_payment_id=f"pay_seed_{sub.id}_{int(now.timestamp())}",
                    amount=sub.price_amount,
                    currency=sub.currency,
                    status=PaymentStatus.SUCCESS.value,
                    created_at=sub.current_period_start or now,
                )
                db.add(payment)
                db.flush()
                payments_by_sub[sub.id] = payment
                print(f"  + Payment #{payment.id}: ₹{payment.amount/100:.2f} for Sub #{sub.id} (SUCCESS)")
            elif sub.status == SubscriptionStatus.PAST_DUE.value:
                # Failed payment that triggered past due
                failed_payment = PaymentModel(
                    subscription_id=sub.id,
                    user_id=user.id,
                    provider="RAZORPAY",
                    provider_order_id=f"order_fail_{sub.id}",
                    provider_payment_id=None,
                    amount=sub.price_amount,
                    currency=sub.currency,
                    status=PaymentStatus.FAILED.value,
                    failure_reason="card_declined_insufficient_funds",
                    created_at=sub.current_period_end or now,
                )
                db.add(failed_payment)
                db.flush()
                payments_by_sub[sub.id] = failed_payment
                print(f"  + Payment #{failed_payment.id}: ₹{failed_payment.amount/100:.2f} for Sub #{sub.id} (FAILED)")

        # Add one partial refund on Acme Studio's payment to test net revenue & refund analytics
        acme_sub = next(s for s, u, p in created_subs if u.email_address == "diya@acme-studio.example")
        if acme_sub.id in payments_by_sub and payments_by_sub[acme_sub.id].status == PaymentStatus.SUCCESS.value:
            acme_payment = payments_by_sub[acme_sub.id]
            refund = RefundModel(
                payment_id=acme_payment.id,
                user_id=acme_sub.user_id,
                provider_refund_id=f"rfnd_seed_{acme_payment.id}",
                amount=25000,  # ₹250.00 partial refund
                currency="INR",
                status=RefundStatus.PROCESSED.value,
                created_at=now - timedelta(days=3),
            )
            db.add(refund)
            db.flush()
            print(f"  + Refund #{refund.id}: ₹250.00 issued on Payment #{acme_payment.id}")

        db.commit()

        # =====================================================================
        # 5. SEED INVOICES
        # =====================================================================
        # 5.1 Historical Invoices for Saurav Rana (Customer Hero)
        saurav_user = users_by_email["saurav@subsyra.com"]
        saurav_sub = next(s for s, u, p in created_subs if u.id == saurav_user.id)
        saurav_pay = payments_by_sub.get(saurav_sub.id)

        saurav_history = [
            ("INV-20260905-1001", now - timedelta(days=61), InvoiceStatus.PAID.value),
            ("INV-20261005-1002", now - timedelta(days=31), InvoiceStatus.PAID.value),
            ("INV-20261105-1003", now - timedelta(days=1), InvoiceStatus.PAID.value),
        ]
        for inv_num, inv_date, inv_status in saurav_history:
            inv = InvoiceModel(
                invoice_number=inv_num,
                user_id=saurav_user.id,
                subscription_id=saurav_sub.id,
                payment_id=saurav_pay.id if saurav_pay else None,
                subtotal=saurav_sub.price_amount,
                tax_amount=0,
                total_amount=saurav_sub.price_amount,
                currency=saurav_sub.currency,
                status=inv_status,
                billing_reason="SUBSCRIPTION_CREATE" if "1001" in inv_num else "RENEWAL",
                paid_at=inv_date,
                created_at=inv_date,
            )
            db.add(inv)
            print(f"  + Customer Invoice {inv_num} for {saurav_user.full_name}: ₹{inv.total_amount/100:.2f}")

        # 5.2 Invoices for other subscribers
        inv_sequence = 1004
        for sub, user, plan in created_subs:
            if user.id == saurav_user.id:
                continue

            pay = payments_by_sub.get(sub.id)
            if sub.status in [SubscriptionStatus.ACTIVE.value, SubscriptionStatus.CANCELLED.value]:
                inv_num = f"INV-20261024-{inv_sequence}"
                inv_sequence += 1
                inv = InvoiceModel(
                    invoice_number=inv_num,
                    user_id=user.id,
                    subscription_id=sub.id,
                    payment_id=pay.id if pay else None,
                    subtotal=sub.price_amount,
                    tax_amount=0,
                    total_amount=sub.price_amount,
                    currency=sub.currency,
                    status=InvoiceStatus.PAID.value,
                    billing_reason="SUBSCRIPTION_CREATE",
                    paid_at=sub.current_period_start or now,
                    created_at=sub.current_period_start or now,
                )
                db.add(inv)
                print(f"  + Paid Invoice {inv_num} for {user.full_name}: ₹{inv.total_amount/100:.2f}")

            elif sub.status == SubscriptionStatus.PAST_DUE.value:
                # Overdue invoice for Orbit Health!
                inv_num = f"INV-20261103-{inv_sequence}"
                inv_sequence += 1
                inv = InvoiceModel(
                    invoice_number=inv_num,
                    user_id=user.id,
                    subscription_id=sub.id,
                    payment_id=pay.id if pay else None,
                    subtotal=sub.price_amount,
                    tax_amount=0,
                    total_amount=sub.price_amount,
                    currency=sub.currency,
                    status=InvoiceStatus.UNCOLLECTIBLE.value,
                    billing_reason="RENEWAL",
                    paid_at=None,
                    created_at=sub.current_period_end or now,
                )
                db.add(inv)
                print(f"  + Overdue Invoice {inv_num} for {user.full_name}: ₹{inv.total_amount/100:.2f} (UNCOLLECTIBLE)")

        db.commit()

        # =====================================================================
        # 6. SEED AUDIT LOGS
        # =====================================================================
        admin_user = users_by_email["admin@subsyra.com"]
        audit_events = [
            ("CREATE_PLAN", "PLAN", growth_plan.id, admin_user.id, {"plan_name": "Growth Plan"}),
            ("ACTIVATE_SUBSCRIPTION", "SUBSCRIPTION", saurav_sub.id, saurav_user.id, {"plan_id": growth_plan.id}),
            ("PAYMENT_SUCCESS", "PAYMENT", saurav_pay.id if saurav_pay else 1, saurav_user.id, {"gateway": "RAZORPAY"}),
        ]
        for action, target_type, target_id, actor_id, details in audit_events:
            log = AuditLogModel(
                user_id=actor_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                details=details,
                created_at=now - timedelta(hours=2),
            )
            db.add(log)

        db.commit()

        print("\n[+] Database Seeding Completed Successfully!")
        print(f"   • Total Users:         {db.query(UserModel).count()}")
        print(f"   • Total Plans:         {db.query(PlanPricingModel).count()}")
        print(f"   • Total Subscriptions: {db.query(SubscriptionModel).count()}")
        print(f"   • Total Invoices:      {db.query(InvoiceModel).count()}")
        print(f"   • Total Payments:      {db.query(PaymentModel).count()}")
        print(f"   • Total Refunds:       {db.query(RefundModel).count()}")

    except Exception as e:
        db.rollback()
        print(f"[-] Database Seeding Failed: {e}")
        raise e
    finally:
        db.close()


if __name__ == "__main__":
    seed_database()
