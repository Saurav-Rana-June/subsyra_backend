from src.utils.db import Base, engine
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.users.models import UserModel, RevokedTokenModel, DeletedUserModel
from src.plans_pricing.models import PlanPricingModel
from src.subscription.models import SubscriptionModel
from src.payment.models import PaymentModel, WebhookEventModel
from src.invoices.models import InvoiceModel
from src.audit_logs.models import AuditLogModel

from src.users.routers import user_routes
from src.plans_pricing.routers import plan_pricing_routes
from src.subscription.routers import subscription_routes
from src.payment.routers import payment_routes
from src.invoices.routers import invoice_routes
from src.audit_logs.routers import audit_log_routes
from src.analytics.routers import analytics_routes
from src.dashboard.routers import dashboard_routes

Base.metadata.create_all(engine)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:52221", "http://localhost:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(user_routes, prefix="/api")
app.include_router(plan_pricing_routes, prefix="/api")
app.include_router(subscription_routes, prefix="/api")
app.include_router(payment_routes, prefix="/api")
app.include_router(invoice_routes, prefix="/api")
app.include_router(audit_log_routes, prefix="/api")
app.include_router(analytics_routes, prefix="/api")
app.include_router(dashboard_routes, prefix="/api")
