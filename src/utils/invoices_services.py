from sqlalchemy.orm import Session
from datetime import datetime, timezone
from src.invoices.models import InvoiceModel, InvoiceStatus
from src.payment.models import PaymentModel
from src.subscription.models import SubscriptionModel


def generate_invoice_number(db: Session) -> str:
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"INV-{today_str}-"

    # Count how many invoices exist for today
    today_count = (
        db.query(InvoiceModel)
        .filter(InvoiceModel.invoice_number.like(f"{prefix}%"))
        .count()
    )

    sequence = str(today_count + 1).zfill(4)
    return f"{prefix}{sequence}"


def create_invoice_for_payment(
    db: Session,
    payment: PaymentModel,
    subscription: SubscriptionModel,
    billing_reason: str = "SUBSCRIPTION_CREATE",
) -> InvoiceModel:
    existing_invoice = (
        db.query(InvoiceModel).filter(InvoiceModel.payment_id == payment.id).first()
    )
    if existing_invoice:
        return existing_invoice

    invoice_num = generate_invoice_number(db)

    total_amount = payment.amount
    tax_amount = 0
    subtotal = total_amount - tax_amount

    invoice = InvoiceModel(
        invoice_number=invoice_num,
        user_id=payment.user_id,
        subscription_id=subscription.id,
        payment_id=payment.id,
        subtotal=subtotal,
        tax_amount=tax_amount,
        total_amount=total_amount,
        currency=payment.currency or "INR",
        status=InvoiceStatus.PAID.value,
        billing_reason=billing_reason,
        paid_at=datetime.now(timezone.utc),
    )
    db.add(invoice)
    return invoice
