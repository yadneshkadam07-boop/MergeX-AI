"""Billing and subscription endpoints: status, checkout session, portal, webhook."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.api.dependencies import CurrentUserDep, SessionDep, SettingsDep
from app.core.logging import get_logger
from app.schemas.billing import (
    BillingStatusResponse,
    CheckoutSessionRequest,
    CheckoutSessionResponse,
    CustomerPortalRequest,
    CustomerPortalResponse,
)
from app.services.billing import (
    TIER_SCAN_LIMITS,
    create_checkout_session,
    create_portal_session,
    handle_gumroad_ping,
    handle_stripe_webhook,
)

log = get_logger("app.api.routes.billing")

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get(
    "/status",
    response_model=BillingStatusResponse,
    summary="Get user's current subscription tier and usage limits",
)
async def get_billing_status(
    current_user: CurrentUserDep,
    settings: SettingsDep,
) -> BillingStatusResponse:
    """Return the user's current subscription plan, scan counts, and limits."""
    tier = getattr(current_user, "tier", "free") or "free"
    monthly_scans_used = getattr(current_user, "monthly_scans_used", 0) or 0
    max_scans = TIER_SCAN_LIMITS.get(tier, 5)
    has_active_subscription = bool(current_user.stripe_subscription_id)

    return BillingStatusResponse(
        tier=tier,
        monthly_scans_used=monthly_scans_used,
        max_scans=max_scans,
        has_active_subscription=has_active_subscription,
        stripe_configured=bool(settings.stripe_secret_key),
    )


@router.post(
    "/checkout",
    response_model=CheckoutSessionResponse,
    summary="Initiate a Stripe Checkout session for subscription upgrade",
)
async def create_checkout(
    payload: CheckoutSessionRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
) -> CheckoutSessionResponse:
    """Generate a Stripe Checkout URL for Pro or Team upgrade."""
    default_origin = (
        settings.cors_origins[0] if settings.cors_origins else "https://merge-x-ai.vercel.app"
    )
    success_url = payload.success_url or f"{default_origin}/settings"
    cancel_url = payload.cancel_url or f"{default_origin}/settings"

    try:
        url, session_id = await create_checkout_session(
            user=current_user,
            plan=payload.plan,
            success_url=success_url,
            cancel_url=cancel_url,
            session=session,
            settings=settings,
        )
        return CheckoutSessionResponse(checkout_url=url, session_id=session_id)
    except Exception as exc:
        log.error("checkout_creation_error", error=str(exc), user_id=str(current_user.id))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create checkout session: {str(exc)}",
        ) from exc


@router.post(
    "/portal",
    response_model=CustomerPortalResponse,
    summary="Generate a Stripe Customer Portal link to manage subscription",
)
async def create_portal(
    payload: CustomerPortalRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
) -> CustomerPortalResponse:
    """Generate a Stripe Customer Portal link for managing cards and subscriptions."""
    default_origin = (
        settings.cors_origins[0] if settings.cors_origins else "https://merge-x-ai.vercel.app"
    )
    return_url = payload.return_url or f"{default_origin}/settings"

    try:
        url = await create_portal_session(
            user=current_user,
            return_url=return_url,
            session=session,
            settings=settings,
        )
        return CustomerPortalResponse(portal_url=url)
    except Exception as exc:
        log.error("portal_creation_error", error=str(exc), user_id=str(current_user.id))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create portal session: {str(exc)}",
        ) from exc


@router.post(
    "/webhook",
    summary="Handle incoming Stripe events (payments, cancellations)",
)
async def stripe_webhook(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    stripe_signature: str | None = Header(None, alias="stripe-signature"),
) -> dict[str, str]:
    """Process verified webhook events from Stripe."""
    payload = await request.body()
    result = await handle_stripe_webhook(
        payload=payload,
        sig_header=stripe_signature,
        session=session,
        settings=settings,
    )
    return {"status": result.get("status", "ok")}


@router.post(
    "/gumroad-ping",
    summary="Process Gumroad purchase or cancellation webhooks",
)
async def gumroad_webhook_ping(
    request: Request,
    session: SessionDep,
) -> dict[str, Any]:
    """Receive and process instant subscription webhooks from Gumroad."""
    try:
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            payload = await request.json()
        else:
            form = await request.form()
            payload = dict(form)

        success = await handle_gumroad_ping(payload, session)
        return {"received": True, "processed": success}
    except Exception as exc:
        log.error("gumroad_ping_exception", error=str(exc))
        return {"received": True, "error": str(exc)}
