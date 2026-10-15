import { api } from "./client";
import type { Task } from "./client";

export async function listTasks(): Promise<Task[]> {
  const response = await api.get("/api/tasks");
  return response.data;
}

export async function createTask(title: string, ownerId: number): Promise<Task> {
  const response = await api.post("/api/tasks", { title, owner_id: ownerId });
  return response.data;
}

// SEEDED BUG (MX-API-005, missing auth header): the backend route depends on
// require_admin, but no Authorization header is attached here.
export async function deleteAllTasks(): Promise<void> {
  await api.delete("/api/tasks/all");
}
