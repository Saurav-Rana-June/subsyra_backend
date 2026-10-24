import razorpay
from src.utils.settings import settings

client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


def create_razorpay_order(
    amount: int, currency: str = "INR", receipt: str = ""
) -> dict:
    data = {
        "amount": amount,
        "currency": currency,
        "receipt": receipt,
        "payment_capture": 1,
    }

    return client.order.create(data=data)


def verify_razorpay_signature(order_id: str, payment_id: str, signature: str) -> bool:
    params_dict = {
        "razorpay_order_id": order_id,
        "razorpay_payment_id": payment_id,
        "razorpay_signature": signature,
    }

    try:
        client.utility.verify_payment_signature(params_dict)
        return True
    except razorpay.errors.SignatureVerificationError:
        return False


def verify_razorpay_webhook_signature(body_str: str, signature: str) -> bool:
    try:
        client.utility.verify_webhook_signature(
            body_str, signature, settings.RAZORPAY_WEBHOOK_SECRET
        )
        return True
    except razorpay.errors.SignatureVerificationError:
        return False


def create_razorpay_refund(
    payment_id: str, amount: int = None, notes: dict = None
) -> dict:
    data = {}
    if amount is not None:
        data["amount"] = amount
    if notes is not None:
        data["notes"] = notes
    return client.payment.refund(payment_id, data=data)
