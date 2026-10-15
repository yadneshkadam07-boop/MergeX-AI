import { api } from "./client";
import type { User } from "./client";

// SEEDED BUG (MX-API-002, path typo): the backend route is "/api/users/{user_id}",
// singular "user" here. A 404 at runtime.
export async function getUser(id: number): Promise<User> {
  const response = await api.get(`/api/user/${id}`);
  return response.data;
}

export async function listUsers(): Promise<User[]> {
  const response = await api.get("/api/users");
  return response.data;
}

// SEEDED BUG (MX-API-004, request field name mismatch): the backend expects
// snake_case "full_name"; this sends camelCase "fullName", so the field is
// dropped and the request fails validation.
export async function createUser(email: string, fullName: string): Promise<User> {
  const response = await api.post("/api/users", { email, fullName });
  return response.data;
}

// SEEDED BUG (MX-API-003, HTTP method mismatch): the backend declares this
// route as DELETE, not POST.
export async function deactivateUser(id: number): Promise<void> {
  await api.post(`/api/users/${id}/deactivate`);
}

// SEEDED BUG (MX-API-001, missing endpoint): no backend route defines
// "/api/users/export" at all.
export async function exportUsers(): Promise<Blob> {
  const response = await api.get("/api/users/export", { responseType: "blob" });
  return response.data;
}
