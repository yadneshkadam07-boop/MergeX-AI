"""Stripe subscription, checkout, customer portal, and webhook handling service."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import get_logger
from app.models.user import User

log = get_logger("app.services.billing")

# Max scans allowed per tier
TIER_SCAN_LIMITS = {
    "free": 5,
    "pro": -1,  # Unlimited
    "team": -1,  # Unlimited
}


async def get_or_create_stripe_customer(
    user: User,
    session: AsyncSession,
    settings: Settings,
) -> str | None:
    """Ensure a Stripe customer exists for this user and return the customer id."""
    if not settings.stripe_secret_key:
        return None

    import stripe

    stripe.api_key = settings.stripe_secret_key

    if user.stripe_customer_id:
        return user.stripe_customer_id

    try:
        customer = stripe.Customer.create(
            email=user.email,
            name=user.display_name,
            metadata={"user_id": str(user.id)},
        )
        user.stripe_customer_id = customer.id
        await session.commit()
        return customer.id
    except Exception as exc:
        log.error("stripe_customer_create_failed", error=str(exc), user_id=str(user.id))
        return None


async def create_checkout_session(
    *,
    user: User,
    plan: str,
    success_url: str,
    cancel_url: str,
    session: AsyncSession,
    settings: Settings,
) -> tuple[str, str]:
    """Create a Gumroad redirect, Stripe checkout session, or simulated link."""
    # 1. Prefer Gumroad if configured and Stripe is not active
    if settings.gumroad_pro_url and not settings.stripe_secret_key:
        log.info("using_gumroad_checkout", user_id=str(user.id), plan=plan)
        base_gumroad = settings.gumroad_pro_url.split("?")[0]
        # Prepopulate customer's email so they don't have to retype it
        gumroad_url = f"{base_gumroad}?email={user.email}"
        session_id = f"gumroad_{user.id.hex[:12]}"
        return gumroad_url, session_id

    # 2. Simulated sandbox if neither is configured
    if not settings.stripe_secret_key:
        log.info("stripe_keys_missing_using_sandbox_simulation", user_id=str(user.id), plan=plan)
        # Sandbox simulated link for testing before adding live Stripe keys
        simulated_session_id = f"sim_cs_{user.id.hex[:12]}"
        simulated_url = (
            f"{success_url}?session_id={simulated_session_id}&simulated=true&plan={plan}"
        )
        # Automatically activate pro in simulated sandbox mode
        user.tier = plan if plan in ("pro", "team") else "pro"
        user.stripe_subscription_id = f"sim_sub_{user.id.hex[:12]}"
        await session.commit()
        return simulated_url, simulated_session_id

    import stripe

    stripe.api_key = settings.stripe_secret_key

    customer_id = await get_or_create_stripe_customer(user, session, settings)

    # Determine price ID from settings
    price_id = settings.stripe_price_id_team if plan == "team" else settings.stripe_price_id_pro

    if not price_id:
        # Fall back to dynamic price data if explicit price ID not configured
        unit_amount = 9900 if plan == "team" else 2900
        plan_name = "MergeX AI Team" if plan == "team" else "MergeX AI Pro"
        line_items: list[dict[str, Any]] = [
            {
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": plan_name,
                        "description": f"Monthly subscription to {plan_name}",
                    },
                    "unit_amount": unit_amount,
                    "recurring": {"interval": "month"},
                },
                "quantity": 1,
            }
        ]
    else:
        line_items = [{"price": price_id, "quantity": 1}]

    session_params: dict[str, Any] = {
        "mode": "subscription",
        "payment_method_types": ["card"],
        "line_items": line_items,
        "success_url": f"{success_url}?session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": cancel_url,
        "client_reference_id": str(user.id),
        "metadata": {
            "user_id": str(user.id),
            "plan": plan,
        },
    }

    if customer_id:
        session_params["customer"] = customer_id
    else:
        session_params["customer_email"] = user.email

    checkout = stripe.checkout.Session.create(**session_params)
    return checkout.url, checkout.id


async def create_portal_session(
    *,
    user: User,
    return_url: str,
    session: AsyncSession,
    settings: Settings,
) -> str:
    """Create a Stripe Customer Portal link so users can manage/cancel subscriptions."""
    if not settings.stripe_secret_key:
        return f"{return_url}?portal_simulated=true"

    import stripe

    stripe.api_key = settings.stripe_secret_key

    customer_id = await get_or_create_stripe_customer(user, session, settings)
    if not customer_id:
        return f"{return_url}?portal_error=no_customer"

    portal = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
    )
    return portal.url


async def handle_stripe_webhook(
    *,
    payload: bytes,
    sig_header: str | None,
    session: AsyncSession,
    settings: Settings,
) -> dict[str, Any]:
    """Verify and process Stripe webhooks to keep database tier in sync."""
    if not settings.stripe_secret_key:
        return {"status": "ignored", "reason": "stripe_not_configured"}

    import stripe

    stripe.api_key = settings.stripe_secret_key

    event: dict[str, Any]
    if settings.stripe_webhook_secret and sig_header:
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.stripe_webhook_secret
            )
        except Exception as exc:
            log.warning("stripe_webhook_signature_verification_failed", error=str(exc))
            return {"status": "error", "message": "Invalid signature"}
    else:
        # Fall back to decoding JSON directly if webhook secret is not set (testing mode)
        try:
            event = json.loads(payload.decode("utf-8"))
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    event_type = event.get("type", "")
    data_object = event.get("data", {}).get("object", {})

    log.info("stripe_webhook_received", event_type=event_type)

    if event_type == "checkout.session.completed":
        user_id_str = data_object.get("client_reference_id") or data_object.get("metadata", {}).get(
            "user_id"
        )
        plan = data_object.get("metadata", {}).get("plan", "pro")
        customer_id = data_object.get("customer")
        subscription_id = data_object.get("subscription")

        if user_id_str:
            import uuid

            try:
                user_id = uuid.UUID(user_id_str)
                user = await session.get(User, user_id)
                if user:
                    user.tier = plan if plan in ("pro", "team") else "pro"
                    if customer_id:
                        user.stripe_customer_id = str(customer_id)
                    if subscription_id:
                        user.stripe_subscription_id = str(subscription_id)
                    await session.commit()
                    log.info("user_upgraded_via_stripe", user_id=str(user.id), tier=user.tier)
            except Exception as exc:
                log.error("error_updating_user_after_checkout", error=str(exc))

    elif event_type in ("customer.subscription.deleted", "customer.subscription.paused"):
        subscription_id = data_object.get("id")
        if subscription_id:
            user = await session.scalar(
                select(User).where(User.stripe_subscription_id == str(subscription_id))
            )
            if user:
                user.tier = "free"
                user.stripe_subscription_id = None
                await session.commit()
                log.info("user_downgraded_after_cancellation", user_id=str(user.id))

    return {"status": "processed", "type": event_type}


async def handle_gumroad_ping(
    payload: dict[str, Any],
    session: AsyncSession,
) -> bool:
    """Handle an incoming Gumroad purchase, recurring payment, or cancellation ping."""
    email = payload.get("email")
    if not email:
        log.warning("gumroad_ping_missing_email", payload=payload)
        return False

    stmt = select(User).where(User.email == str(email).strip().lower())
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        log.warning("gumroad_ping_user_not_found", email=email)
        return False

    is_cancelled = str(payload.get("cancelled", "")).lower() in ("true", "1")
    is_refunded = str(payload.get("refunded", "")).lower() in ("true", "1")

    if is_cancelled or is_refunded:
        log.info("gumroad_subscription_cancelled_or_refunded", email=email)
        user.tier = "free"
    else:
        sale_id = (
            payload.get("sale_id") or payload.get("order_number") or f"gumroad_{user.id.hex[:8]}"
        )
        log.info("gumroad_subscription_activated", email=email, sale_id=sale_id)
        user.tier = "pro"
        user.stripe_subscription_id = str(sale_id)

    await session.commit()
    return True
