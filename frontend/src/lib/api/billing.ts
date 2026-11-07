import { http } from "@/lib/http";
import type {
  BillingStatus,
  CheckoutSessionResponse,
  CustomerPortalResponse,
} from "@/types/billing";

export async function getBillingStatus(): Promise<BillingStatus> {
  return http.get<BillingStatus>("/billing/status");
}

export async function createCheckoutSession(
  plan: "pro" | "team" = "pro",
  successUrl?: string,
  cancelUrl?: string,
): Promise<CheckoutSessionResponse> {
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  return http.post<CheckoutSessionResponse>("/billing/checkout", {
    plan,
    success_url: successUrl || `${origin}/settings?checkout=success`,
    cancel_url: cancelUrl || `${origin}/settings?checkout=cancel`,
  });
}

export async function createCustomerPortalSession(
  returnUrl?: string,
): Promise<CustomerPortalResponse> {
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  return http.post<CustomerPortalResponse>("/billing/portal", {
    return_url: returnUrl || `${origin}/settings`,
  });
}
