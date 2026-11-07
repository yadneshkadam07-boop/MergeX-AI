/**
 * Subscription and billing types for MergeX AI.
 */

export type SubscriptionTier = "free" | "pro" | "team";

export interface BillingStatus {
  tier: SubscriptionTier;
  monthly_scans_used: number;
  max_scans: number;
  has_active_subscription: boolean;
  stripe_configured: boolean;
}

export interface CheckoutSessionResponse {
  checkout_url: string;
  session_id: string;
}

export interface CustomerPortalResponse {
  portal_url: string;
}
