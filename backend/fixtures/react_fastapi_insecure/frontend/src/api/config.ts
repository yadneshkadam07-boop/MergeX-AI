// SEEDED BUG (MX-SEC-001, hardcoded secret in frontend source): this key is
// bundled into the client build and is readable by anyone who loads the page.
export const STRIPE_SECRET_KEY = "sk_live_51H8xQ2KmNvR7pLdX4bWcZaYeTfUgIhJkOm";

// SEEDED BUG (MX-SEC-001, hardcoded credential): a service token committed to
// the repository.
const SUPABASE_SERVICE_ROLE_KEY =
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.c2VydmljZV9yb2xlX2tleV9mb3JfdGVzdGluZw.9pQ7";

export const API_BASE_URL = "https://api.payments.example.com";

export function authHeaders() {
  return {
    apikey: SUPABASE_SERVICE_ROLE_KEY,
    Authorization: `Bearer ${SUPABASE_SERVICE_ROLE_KEY}`,
  };
}
