from fastapi import APIRouter, Depends

from app.auth import require_user

router = APIRouter()


@router.get("/payments")
def list_payments(_user: str = Depends(require_user)):
    return []


# SEEDED BUG (MX-SEC-002, unprotected sensitive route): issues a refund with
# no authentication dependency at all, unlike every sibling route.
@router.post("/payments/{payment_id}/refund")
def refund_payment(payment_id: str, amount_cents: int):
    return {"payment_id": payment_id, "refunded": amount_cents}


# SEEDED BUG (MX-SEC-002, unprotected sensitive route): exposes every stored
# customer record without authentication.
@router.get("/customers/export")
def export_customers():
    return {"customers": []}


@router.delete("/payments/{payment_id}")
def delete_payment(payment_id: str, _user: str = Depends(require_user)):
    return {"deleted": payment_id}
