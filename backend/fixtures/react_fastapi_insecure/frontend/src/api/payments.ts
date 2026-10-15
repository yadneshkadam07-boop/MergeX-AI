import axios from "axios";

import { API_BASE_URL, STRIPE_SECRET_KEY, authHeaders } from "./config";

export async function listPayments() {
  const response = await axios.get(`${API_BASE_URL}/api/payments`, {
    headers: authHeaders(),
  });
  return response.data;
}

export async function refund(paymentId: string, amountCents: number) {
  const response = await axios.post(
    `${API_BASE_URL}/api/payments/${paymentId}/refund`,
    { amount_cents: amountCents },
    { headers: { Authorization: `Bearer ${STRIPE_SECRET_KEY}` } },
  );
  return response.data;
}
