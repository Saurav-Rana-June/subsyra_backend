# Subsyra Backend

Subsyra is a subscription and recurring billing management system that simplifies plan management, payments, renewals, invoicing, and revenue tracking with secure payment integration and analytics.

A production-grade SaaS Subscription & Billing Backend built with **FastAPI**, **PostgreSQL**, **SQLAlchemy**, **Alembic**, and **Razorpay**.

---

## Features

- **Authentication & RBAC**: JWT-based authentication with Argon2 password hashing and Admin/Customer role-based access control.
- **Plans & Pricing Management**: Flexible recurring subscription plans (monthly, yearly), trial periods, and tier features.
- **Subscription Lifecycle**:
  - Full state-machine transitions (`PENDING_PAYMENT`, `TRIALING`, `ACTIVE`, `PAST_DUE`, `CANCELLED`, `EXPIRED`).
  - Free trial tracking with anti-abuse prevention per user/plan.
  - Grace periods & dunning retry workers for handling payment failures.
- **Billing & Invoicing**: Automated invoice generation with unique invoice numbers and payment reconciliations.
- **Razorpay Integration & Webhooks**:
  - Secure webhook signature verification using HMAC SHA256.
  - Idempotent event processing (`payment.captured`, `payment.failed`, `order.paid`).
  - Strict currency and amount mismatch validations.
- **Plan Changes & Proration**:
  - Immediate upgrades with prorated instant credit adjustments.
  - Scheduled downgrades taking effect seamlessly on next billing renewal.
- **Refund Management**:
  - Admin-controlled partial and full refunds.
  - Automated subscription revocation upon full refund.
- **Audit Logs**:
  - Centralized audit trail recording critical administrative and financial actions (plan changes, cancellations, refunds).
- **Analytics & Reporting**:
  - Financial KPIs: MRR (Monthly Recurring Revenue), ARR (Annual Recurring Revenue), and Net Revenue.
  - Churn analytics (churn rate, lost revenue).
  - Subscription breakdown by status and plan tiers.
  - Payment success vs failure rates with date-range filtering.

---

## Tech Stack

- **Framework**: FastAPI (Python 3.12+)
- **Database**: PostgreSQL
- **ORM & Migrations**: SQLAlchemy 2.0 & Alembic
- **Payment Gateway**: Razorpay API & Webhooks
- **Auth**: PyJWT, Pwdlib (Argon2)
- **Validation**: Pydantic v2 & Pydantic-Settings
- **Testing**: Python unittest & FastAPI TestClient

---

## Getting Started

### 1. Clone the Repository
```bash
git clone https://github.com/Saurav-Rana-June/subsyra_backend.git
cd subsyra_backend
```

### 2. Set Up Virtual Environment
```bash
python -m venv venv

# Windows
.\venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy `.env.example` to `.env` and fill in your database and Razorpay credentials:
```bash
cp .env.example .env
```

### 5. Run Database Migrations
```bash
alembic upgrade head
```

### 6. Start the Development Server
```bash
uvicorn main:app --reload
```
Interactive API documentation will be available at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

---

## Running Tests

Run the complete test suite (40 unit and lifecycle integration tests):
```bash
python -m unittest discover -s tests -p "test_*.py" -v
```
