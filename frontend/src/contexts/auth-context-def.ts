import { createContext } from "react";

export interface User {
  id: string;
  email: string;
  name: string;
  avatarUrl?: string;
  githubUsername?: string;
  tier?: "free" | "pro" | "team";
  monthlyScansUsed?: number;
}

export interface AuthContextType {
  user: User | null;
  token: string | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  register: (email: string, password: string, name?: string) => Promise<void>;
  loginWithCredentials: (email: string, password: string) => Promise<void>;
  loginWithGitHub: () => Promise<void>;
  loginWithGitHubCallback: (code: string, redirectUri?: string) => Promise<void>;
  logout: () => void;
  updateUser: (updates: Partial<User>) => void;
}

export const AuthContext = createContext<AuthContextType | undefined>(undefined);
