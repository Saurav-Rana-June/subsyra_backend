import csv
import io
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import status
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.orm import Session, joinedload

from src.audit_logs.services import record_audit_log
from src.invoices.dtos import (
    InvoiceCreateSchema,
    InvoiceReadSchema,
    InvoiceSummarySchema,
)
from src.invoices.models import InvoiceModel, InvoiceStatus
from src.subscription.models import SubscriptionModel, SubscriptionStatus
from src.users.models import UserModel, UserRole
from src.utils.invoices_services import generate_invoice_number
from src.utils.redis_cache import redis_cache
from src.utils.responses import ApiResponse


_BILLING_REASON_ALIASES = {
    "RENEWAL": "SUBSCRIPTION_CYCLE",
    "UPGRADE_PRORATION": "PLAN_UPGRADE",
}


def _build_invoice_query(
    db: Session,
    user: UserModel,
    subscription_id: Optional[int] = None,
    invoice_status: Optional[str] = None,
    billing_reason: Optional[str] = None,
    search: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
):
    query = db.query(InvoiceModel).options(
        joinedload(InvoiceModel.user),
        joinedload(InvoiceModel.subscription).joinedload(SubscriptionModel.plan),
    )

    if user.role != UserRole.ADMIN.value:
        query = query.filter(InvoiceModel.user_id == user.id)

    if subscription_id is not None:
        query = query.filter(InvoiceModel.subscription_id == subscription_id)

    if invoice_status and invoice_status.upper() != "ALL":
        query = query.filter(InvoiceModel.status == invoice_status.upper())

    if billing_reason and billing_reason.upper() != "ALL":
        normalized_reason = _BILLING_REASON_ALIASES.get(
            billing_reason.upper(), billing_reason.upper()
        )
        query = query.filter(InvoiceModel.billing_reason == normalized_reason)

    if search and search.strip():
        pattern = f"%{search.strip()}%"
        query = query.join(InvoiceModel.user).filter(
            (InvoiceModel.invoice_number.ilike(pattern))
            | (UserModel.full_name.ilike(pattern))
            | (UserModel.email_address.ilike(pattern))
        )

    if start_date is not None:
        query = query.filter(InvoiceModel.created_at >= start_date)

    if end_date is not None:
        query = query.filter(InvoiceModel.created_at <= end_date)

    return query.order_by(InvoiceModel.id.desc())


def _get_invoice_with_access(id: int, db: Session, user: UserModel):
    invoice = (
        db.query(InvoiceModel)
        .options(
            joinedload(InvoiceModel.user),
            joinedload(InvoiceModel.subscription).joinedload(SubscriptionModel.plan),
        )
        .filter(InvoiceModel.id == id)
        .first()
    )
    if not invoice:
        return None, ApiResponse(
            status=status.HTTP_404_NOT_FOUND, message="Invoice not found"
        )
    if invoice.user_id != user.id and user.role != UserRole.ADMIN.value:
        return None, ApiResponse(
            status=status.HTTP_403_FORBIDDEN,
            message="You do not have permission to access this invoice.",
        )
    return invoice, None


def _invalidate_invoice_caches():
    redis_cache.delete_pattern("dashboard:*")
    redis_cache.delete_pattern("analytics:*")
    redis_cache.delete_pattern("subscription:*")


def get_all_invoices(
    db: Session,
    user: UserModel,
    subscription_id: Optional[int] = None,
    invoice_status: Optional[str] = None,
    billing_reason: Optional[str] = None,
    search: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
):
    invoices = _build_invoice_query(
        db=db,
        user=user,
        subscription_id=subscription_id,
        invoice_status=invoice_status,
        billing_reason=billing_reason,
        search=search,
        start_date=start_date,
        end_date=end_date,
    ).all()

    response_data = [
        InvoiceReadSchema.model_validate(inv).model_dump() for inv in invoices
    ]

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Invoices fetched successfully",
        data=response_data,
    )


def get_invoice_summary(db: Session, user: UserModel):
    query = db.query(InvoiceModel)
    if user.role != UserRole.ADMIN.value:
        query = query.filter(InvoiceModel.user_id == user.id)

    invoices = query.all()

    total_invoiced = sum(
        inv.total_amount
        for inv in invoices
        if inv.status not in (InvoiceStatus.DRAFT.value, InvoiceStatus.VOID.value)
    )
    collected_paid = sum(
        inv.total_amount for inv in invoices if inv.status == InvoiceStatus.PAID.value
    )
    pending_open = sum(
        inv.total_amount for inv in invoices if inv.status == InvoiceStatus.OPEN.value
    )
    uncollectible = sum(
        inv.total_amount
        for inv in invoices
        if inv.status == InvoiceStatus.UNCOLLECTIBLE.value
    )

    paid_count = sum(1 for inv in invoices if inv.status == InvoiceStatus.PAID.value)
    open_count = sum(1 for inv in invoices if inv.status == InvoiceStatus.OPEN.value)
    draft_count = sum(1 for inv in invoices if inv.status == InvoiceStatus.DRAFT.value)
    uncollectible_count = sum(
        1 for inv in invoices if inv.status == InvoiceStatus.UNCOLLECTIBLE.value
    )
    void_count = sum(1 for inv in invoices if inv.status == InvoiceStatus.VOID.value)

    collected_pct = (
        round((collected_paid / total_invoiced) * 100) if total_invoiced > 0 else 0
    )

    # Period-over-period growth (last 30 days vs preceding 30 days)
    now = datetime.now(timezone.utc)
    recent_cutoff = now - timedelta(days=30)
    prev_cutoff = now - timedelta(days=60)

    def _to_utc(dt: datetime) -> datetime:
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt

    recent_total = sum(
        inv.total_amount
        for inv in invoices
        if inv.status not in (InvoiceStatus.DRAFT.value, InvoiceStatus.VOID.value)
        and _to_utc(inv.created_at) >= recent_cutoff
    )
    prev_total = sum(
        inv.total_amount
        for inv in invoices
        if inv.status not in (InvoiceStatus.DRAFT.value, InvoiceStatus.VOID.value)
        and prev_cutoff <= _to_utc(inv.created_at) < recent_cutoff
    )
    if prev_total > 0:
        growth_pct = round(((recent_total - prev_total) / prev_total) * 100, 1)
    elif recent_total > 0:
        growth_pct = 100.0
    else:
        growth_pct = 0.0

    summary = InvoiceSummarySchema(
        total_invoiced_amount=total_invoiced,
        collected_paid_amount=collected_paid,
        pending_open_amount=pending_open,
        uncollectible_amount=uncollectible,
        total_count=len(invoices),
        paid_count=paid_count,
        open_count=open_count,
        draft_count=draft_count,
        uncollectible_count=uncollectible_count,
        void_count=void_count,
        collected_percentage=collected_pct,
        growth_percentage=growth_pct,
    ).model_dump()

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Invoice summary calculated successfully",
        data=summary,
    )


def export_invoices_csv(
    db: Session,
    user: UserModel,
    subscription_id: Optional[int] = None,
    invoice_status: Optional[str] = None,
    billing_reason: Optional[str] = None,
    search: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> StreamingResponse:
    invoices = _build_invoice_query(
        db=db,
        user=user,
        subscription_id=subscription_id,
        invoice_status=invoice_status,
        billing_reason=billing_reason,
        search=search,
        start_date=start_date,
        end_date=end_date,
    ).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "Invoice Number",
            "Customer Name",
            "Customer Email",
            "Plan",
            "Billing Reason",
            "Status",
            "Subtotal (INR)",
            "Tax (INR)",
            "Total (INR)",
            "Issued Date",
            "Paid Date",
        ]
    )

    for inv in invoices:
        writer.writerow(
            [
                inv.invoice_number,
                inv.user.full_name if inv.user else f"User #{inv.user_id}",
                inv.user.email_address if inv.user else "",
                inv.plan_name or f"Subscription #{inv.subscription_id}",
                inv.billing_reason,
                inv.status,
                f"{inv.subtotal / 100:.2f}",
                f"{inv.tax_amount / 100:.2f}",
                f"{inv.total_amount / 100:.2f}",
                inv.created_at.isoformat() if inv.created_at else "",
                inv.paid_at.isoformat() if inv.paid_at else "",
            ]
        )

    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=invoices_export.csv"},
    )


def create_manual_invoice(
    body: InvoiceCreateSchema, db: Session, admin: UserModel
):
    target_user = db.query(UserModel).filter(UserModel.id == body.user_id).first()
    if not target_user:
        return ApiResponse(
            status=status.HTTP_404_NOT_FOUND, message="Customer not found"
        )

    sub = (
        db.query(SubscriptionModel)
        .filter(SubscriptionModel.id == body.subscription_id)
        .first()
    )
    if not sub:
        return ApiResponse(
            status=status.HTTP_404_NOT_FOUND, message="Subscription not found"
        )

    if sub.user_id != target_user.id:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Subscription does not belong to the specified customer.",
        )

    now = datetime.now(timezone.utc)
    invoice = InvoiceModel(
        invoice_number=generate_invoice_number(db),
        user_id=target_user.id,
        subscription_id=sub.id,
        payment_id=None,
        subtotal=body.subtotal,
        tax_amount=body.tax_amount,
        total_amount=body.subtotal + body.tax_amount,
        currency=sub.currency or "INR",
        status=body.status,
        billing_reason=body.billing_reason,
        paid_at=now if body.status == InvoiceStatus.PAID.value else None,
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)

    record_audit_log(
        db=db,
        action="CREATE_MANUAL_INVOICE",
        target_type="INVOICE",
        target_id=invoice.id,
        user_id=admin.id,
        details={
            "invoice_number": invoice.invoice_number,
            "customer_id": target_user.id,
            "subscription_id": sub.id,
            "total_amount": invoice.total_amount,
            "status": invoice.status,
        },
    )
    _invalidate_invoice_caches()

    # Reload relationships for serialization
    loaded, _ = _get_invoice_with_access(invoice.id, db, admin)
    data = InvoiceReadSchema.model_validate(loaded or invoice).model_dump()
    return ApiResponse(
        status=status.HTTP_201_CREATED,
        message="Manual invoice created successfully",
        data=data,
    )


def get_invoice_by_id(id: int, db: Session, user: UserModel):
    invoice, err = _get_invoice_with_access(id, db, user)
    if err:
        return err

    data = InvoiceReadSchema.model_validate(invoice).model_dump()
    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Invoice fetched successfully",
        data=data,
    )


def get_invoice_receipt_html(id: int, db: Session, user: UserModel):
    invoice, err = _get_invoice_with_access(id, db, user)
    if err:
        return err

    customer_name = invoice.user.full_name if invoice.user else f"User #{invoice.user_id}"
    customer_email = invoice.user.email_address if invoice.user else ""
    plan_title = invoice.plan_name or f"Subscription #{invoice.subscription_id}"
    issued = invoice.created_at.strftime("%d.%m.%Y") if invoice.created_at else "-"
    paid_str = invoice.paid_at.strftime("%d.%m.%Y") if invoice.paid_at else "Unpaid"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Invoice {invoice.invoice_number}</title>
  <style>
    body {{ font-family: Arial, sans-serif; color: #111827; padding: 32px; max-width: 720px; margin: auto; }}
    .header {{ display: flex; justify-content: space-between; border-bottom: 1px solid #e5e7eb; padding-bottom: 16px; }}
    .badge {{ display: inline-block; padding: 4px 12px; border-radius: 999px; background: #ecfdf5; color: #065f46; font-weight: 600; font-size: 12px; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 24px; }}
    th, td {{ padding: 10px 8px; border-bottom: 1px solid #e5e7eb; text-align: left; }}
    .right {{ text-align: right; }}
    .total {{ font-weight: 700; font-size: 16px; }}
  </style>
</head>
<body>
  <div class="header">
    <div>
      <h1 style="margin:0;">SUBSYRA</h1>
      <p style="margin:4px 0 0; color:#6b7280; font-size:13px;">Subscription Billing Receipt</p>
    </div>
    <div style="text-align:right;">
      <span class="badge">{invoice.status}</span>
      <p style="margin:8px 0 0; font-weight:600;">{invoice.invoice_number}</p>
      <p style="margin:4px 0 0; color:#6b7280; font-size:12px;">Issued: {issued} | Paid: {paid_str}</p>
    </div>
  </div>
  <div style="margin-top:24px;">
    <p style="margin:0; font-size:12px; color:#6b7280; text-transform:uppercase;">Billed To</p>
    <p style="margin:4px 0 0; font-weight:600;">{customer_name}</p>
    <p style="margin:2px 0 0; color:#6b7280; font-size:13px;">{customer_email}</p>
  </div>
  <table>
    <thead><tr><th>Description</th><th class="right">Amount</th></tr></thead>
    <tbody>
      <tr><td>{plan_title} ({invoice.billing_reason})</td><td class="right">₹{invoice.subtotal / 100:,.2f}</td></tr>
      <tr><td>Tax / GST</td><td class="right">₹{invoice.tax_amount / 100:,.2f}</td></tr>
      <tr class="total"><td>Total</td><td class="right">₹{invoice.total_amount / 100:,.2f}</td></tr>
    </tbody>
  </table>
</body>
</html>"""

    return HTMLResponse(
        content=html,
        headers={
            "Content-Disposition": f"inline; filename={invoice.invoice_number}.html"
        },
    )


def mark_invoice_paid(id: int, db: Session, admin: UserModel):
    invoice, err = _get_invoice_with_access(id, db, admin)
    if err:
        return err

    if invoice.status == InvoiceStatus.PAID.value:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Invoice is already marked as paid.",
        )

    if invoice.status == InvoiceStatus.VOID.value:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="A voided invoice cannot be marked as paid.",
        )

    now = datetime.now(timezone.utc)
    previous_status = invoice.status
    invoice.status = InvoiceStatus.PAID.value
    invoice.paid_at = now

    # Recover linked subscription if it was waiting on payment or past due
    sub = (
        db.query(SubscriptionModel)
        .filter(SubscriptionModel.id == invoice.subscription_id)
        .first()
    )
    if sub and sub.status in (
        SubscriptionStatus.PAST_DUE.value,
        SubscriptionStatus.PENDING_PAYMENT.value,
    ):
        sub.status = SubscriptionStatus.ACTIVE.value
        sub.grace_period_end = None
        sub.renewal_retry_count = 0

    record_audit_log(
        db=db,
        action="MARK_INVOICE_PAID",
        target_type="INVOICE",
        target_id=invoice.id,
        user_id=admin.id,
        details={
            "invoice_number": invoice.invoice_number,
            "previous_status": previous_status,
            "status": invoice.status,
        },
    )
    db.commit()
    db.refresh(invoice)
    _invalidate_invoice_caches()

    data = InvoiceReadSchema.model_validate(invoice).model_dump()
    return ApiResponse(
        status=status.HTTP_200_OK,
        message=f"Invoice {invoice.invoice_number} marked as paid.",
        data=data,
    )


def void_invoice(id: int, db: Session, admin: UserModel):
    invoice, err = _get_invoice_with_access(id, db, admin)
    if err:
        return err

    if invoice.status == InvoiceStatus.VOID.value:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Invoice is already voided.",
        )

    if invoice.status == InvoiceStatus.PAID.value:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Paid invoices cannot be voided. Issue a refund instead.",
        )

    previous_status = invoice.status
    invoice.status = InvoiceStatus.VOID.value

    record_audit_log(
        db=db,
        action="VOID_INVOICE",
        target_type="INVOICE",
        target_id=invoice.id,
        user_id=admin.id,
        details={
            "invoice_number": invoice.invoice_number,
            "previous_status": previous_status,
            "status": invoice.status,
        },
    )
    db.commit()
    db.refresh(invoice)
    _invalidate_invoice_caches()

    data = InvoiceReadSchema.model_validate(invoice).model_dump()
    return ApiResponse(
        status=status.HTTP_200_OK,
        message=f"Invoice {invoice.invoice_number} has been voided.",
        data=data,
    )


def resend_invoice_receipt(id: int, db: Session, user: UserModel):
    invoice, err = _get_invoice_with_access(id, db, user)
    if err:
        return err

    if invoice.status == InvoiceStatus.VOID.value:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Cannot resend receipt for a voided invoice.",
        )

    recipient_email = (
        invoice.user.email_address if invoice.user else f"user_{invoice.user_id}"
    )

    record_audit_log(
        db=db,
        action="RESEND_INVOICE_RECEIPT",
        target_type="INVOICE",
        target_id=invoice.id,
        user_id=user.id,
        details={
            "invoice_number": invoice.invoice_number,
            "sent_to": recipient_email,
        },
    )

    return ApiResponse(
        status=status.HTTP_200_OK,
        message=f"Receipt for {invoice.invoice_number} sent to {recipient_email}.",
        data={
            "invoice_id": invoice.id,
            "invoice_number": invoice.invoice_number,
            "sent_to": recipient_email,
        },
    )
