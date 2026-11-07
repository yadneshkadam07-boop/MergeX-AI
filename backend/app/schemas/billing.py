"""Pydantic schemas for Stripe checkout, customer portal, and subscription status."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CheckoutSessionRequest(BaseModel):
    """Payload to create a new Stripe Checkout session."""

    model_config = ConfigDict(extra="ignore")

    plan: str = Field(default="pro", description="Selected plan: 'pro' or 'team'.")
    success_url: str | None = Field(
        default=None,
        description="URL to redirect upon successful payment.",
    )
    cancel_url: str | None = Field(
        default=None,
        description="URL to redirect upon cancellation.",
    )


class CheckoutSessionResponse(BaseModel):
    """Stripe Checkout session URL and session ID."""

    model_config = ConfigDict(extra="ignore")

    checkout_url: str = Field(description="Hosted Stripe Checkout URL.")
    session_id: str = Field(description="Stripe checkout session ID.")


class CustomerPortalRequest(BaseModel):
    """Payload to launch the Stripe Customer Portal."""

    model_config = ConfigDict(extra="ignore")

    return_url: str | None = Field(
        default=None,
        description="URL to return to after managing subscription.",
    )


class CustomerPortalResponse(BaseModel):
    """Stripe Customer Portal link."""

    model_config = ConfigDict(extra="ignore")

    portal_url: str = Field(description="Stripe Customer Portal link.")


class BillingStatusResponse(BaseModel):
    """User's current subscription status and usage limits."""

    model_config = ConfigDict(extra="ignore")

    tier: str = Field(default="free", description="Current subscription tier: free, pro, team.")
    monthly_scans_used: int = Field(default=0, description="Number of scans used this billing cycle.")
    max_scans: int = Field(
        default=5,
        description="Monthly scan cap for the current tier (-1 indicates unlimited).",
    )
    has_active_subscription: bool = Field(
        default=False,
        description="Whether the user has an active paying Stripe subscription.",
    )
    stripe_configured: bool = Field(
        default=False,
        description="Whether Stripe API keys are configured on the server.",
    )
