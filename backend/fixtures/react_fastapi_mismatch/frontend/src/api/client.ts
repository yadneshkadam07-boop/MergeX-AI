import axios from "axios";

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? "http://localhost:8000",
  headers: { "Content-Type": "application/json" },
});

export interface User {
  id: number;
  email: string;
  fullName: string;
  createdAt: string;
}

export interface Task {
  id: number;
  title: string;
  completed: boolean;
  ownerId: number;
}
