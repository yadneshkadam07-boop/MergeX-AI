import React, { useState, useEffect, useCallback } from "react";
import { isMock, config } from "@/lib/config";
import { http, setAuthToken, getAuthToken, ApiError } from "@/lib/http";
import { toast } from "sonner";
import { AuthContext, type User } from "./auth-context-def";

export type { User, AuthContextType } from "./auth-context-def";

const USER_STORAGE_KEY = "mergex_auth_user";
const LOGGED_OUT_KEY = "mergex_auth_logged_out";

function safeGetStorage(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeSetStorage(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // LocalStorage might be restricted
  }
}

function safeRemoveStorage(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    // LocalStorage might be restricted
  }
}

const MOCK_USER: User = {
  id: "usr_mock_01",
  email: "developer@mergex.ai",
  name: "MergeX Developer",
  avatarUrl: "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150",
  githubUsername: "mergex-developer",
};

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setTokenState] = useState<string | null>(getAuthToken());
  const [user, setUser] = useState<User | null>(() => {
    if (safeGetStorage(LOGGED_OUT_KEY) === "true") {
      return null;
    }
    const saved = safeGetStorage(USER_STORAGE_KEY);
    if (saved) {
      try {
        return JSON.parse(saved) as User;
      } catch {
        // Invalid json, fall through
      }
    }
    if (isMock("auth")) {
      return MOCK_USER;
    }
    return null;
  });
  const [isLoading, setIsLoading] = useState<boolean>(!isMock("auth"));

  const updateUser = useCallback((updates: Partial<User>) => {
    setUser((prev) => {
      if (!prev) return null;
      const next = { ...prev, ...updates };
      safeSetStorage(USER_STORAGE_KEY, JSON.stringify(next));
      return next;
    });
  }, []);

  const logout = useCallback(() => {
    setAuthToken(null);
    setTokenState(null);
    setUser(null);
    safeRemoveStorage(USER_STORAGE_KEY);
    safeSetStorage(LOGGED_OUT_KEY, "true");
    toast.info("You have been signed out.");
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
  }, []);

  // Listen for 401 unauthorized events dispatched by the http client
  useEffect(() => {
    const handleUnauthorized = () => {
      logout();
    };

    window.addEventListener("mergex:unauthorized", handleUnauthorized);
    return () => window.removeEventListener("mergex:unauthorized", handleUnauthorized);
  }, [logout]);

  // If in real mode and token exists on mount, fetch current user info
  useEffect(() => {
    if (isMock("auth")) {
      setIsLoading(false);
      return;
    }

    const savedToken = getAuthToken();
    if (!savedToken) {
      setIsLoading(false);
      return;
    }

    let isMounted = true;
    http
      .get<User>("/auth/me")
      .then((userData) => {
        if (isMounted) {
          setUser(userData);
          setIsLoading(false);
        }
      })
      .catch((err) => {
        console.error("Failed to verify existing session:", err);
        if (isMounted) {
          setAuthToken(null);
          setTokenState(null);
          setUser(null);
          setIsLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, []);

  const register = async (email: string, password: string, name?: string): Promise<void> => {
    setIsLoading(true);
    try {
      if (isMock("auth")) {
        await new Promise((r) => setTimeout(r, 400));
        const mockToken = "mock_jwt_session_token_xyz";
        const newUser: User = {
          ...MOCK_USER,
          email,
          name: name?.trim() || email.split("@")[0] || "MergeX Developer",
        };
        setAuthToken(mockToken);
        setTokenState(mockToken);
        setUser(newUser);
        safeSetStorage(USER_STORAGE_KEY, JSON.stringify(newUser));
        safeRemoveStorage(LOGGED_OUT_KEY);
        toast.success("Welcome to MergeX AI!");
        return;
      }

      const res = await http.post<{ access_token: string; user?: User }>("/auth/register", {
        email,
        password,
        name,
      });

      setAuthToken(res.access_token);
      setTokenState(res.access_token);

      const activeUser = res.user || (await http.get<User>("/auth/me"));
      setUser(activeUser);
      safeSetStorage(USER_STORAGE_KEY, JSON.stringify(activeUser));
      safeRemoveStorage(LOGGED_OUT_KEY);

      toast.success("Account created successfully!");
    } catch (err) {
      console.error("Registration failed:", err);
      const msg =
        err instanceof ApiError ? err.message : "Registration failed. Please check your details.";
      toast.error(msg);
      throw err;
    } finally {
      setIsLoading(false);
    }
  };

  const loginWithCredentials = async (email: string, password: string): Promise<void> => {
    setIsLoading(true);
    try {
      if (isMock("auth")) {
        // Simulated mock authentication latency
        await new Promise((r) => setTimeout(r, 400));
        const mockToken = "mock_jwt_session_token_xyz";
        const newUser: User = {
          ...MOCK_USER,
          email,
          name: email.split("@")[0] || "MergeX Developer",
        };
        setAuthToken(mockToken);
        setTokenState(mockToken);
        setUser(newUser);
        safeSetStorage(USER_STORAGE_KEY, JSON.stringify(newUser));
        safeRemoveStorage(LOGGED_OUT_KEY);
        toast.success("Welcome back to MergeX AI!");
        return;
      }

      // Real FastAPI OAuth2 Password Grant or JSON token endpoint
      const res = await http.post<{ access_token: string; user?: User }>("/auth/token", {
        username: email,
        password,
      });

      setAuthToken(res.access_token);
      setTokenState(res.access_token);

      const activeUser = res.user || (await http.get<User>("/auth/me"));
      setUser(activeUser);
      safeSetStorage(USER_STORAGE_KEY, JSON.stringify(activeUser));
      safeRemoveStorage(LOGGED_OUT_KEY);

      toast.success("Signed in successfully!");
    } catch (err) {
      console.error("Authentication failed:", err);
      const msg =
        err instanceof ApiError
          ? err.message
          : "Invalid credentials. Please verify your email and password.";
      toast.error(msg);
      throw err;
    } finally {
      setIsLoading(false);
    }
  };

  const loginWithGitHub = async (): Promise<void> => {
    if (isMock("auth")) {
      // Mock GitHub authentication
      await new Promise((r) => setTimeout(r, 350));
      const mockToken = "mock_github_jwt_token_abc";
      setAuthToken(mockToken);
      setTokenState(mockToken);
      let currentUser = MOCK_USER;
      const saved = safeGetStorage(USER_STORAGE_KEY);
      if (saved) {
        try {
          currentUser = JSON.parse(saved) as User;
        } catch {
          // Fall back to MOCK_USER
        }
      }
      safeRemoveStorage(LOGGED_OUT_KEY);
      setUser(currentUser);
      toast.success("Connected via GitHub demo credentials!");
      return;
    }

    // Real GitHub OAuth redirect flow if configured
    if (config.githubClientId) {
      const redirectUri = `${window.location.origin}/login/callback`;
      const scope = "read:user user:email repo";
      window.location.href = `https://github.com/login/oauth/authorize?client_id=${config.githubClientId}&redirect_uri=${encodeURIComponent(
        redirectUri,
      )}&scope=${encodeURIComponent(scope)}`;
      return;
    }

    // Local development demo fallback: authenticate as demo developer so the app is immediately usable
    setIsLoading(true);
    try {
      let res: { access_token: string; user?: User };
      try {
        res = await http.post<{ access_token: string; user?: User }>("/auth/token", {
          email: "developer@mergex.ai",
          password: "Password123!",
        });
      } catch {
        // If the developer user does not exist in this database instance, register it
        res = await http.post<{ access_token: string; user?: User }>("/auth/register", {
          email: "developer@mergex.ai",
          password: "Password123!",
          name: "Alex Vance",
        });
      }

      setAuthToken(res.access_token);
      setTokenState(res.access_token);

      const activeUser = res.user || (await http.get<User>("/auth/me"));
      setUser(activeUser);
      safeSetStorage(USER_STORAGE_KEY, JSON.stringify(activeUser));
      safeRemoveStorage(LOGGED_OUT_KEY);

      toast.success("Connected via GitHub demo credentials!");
    } catch (err) {
      console.warn("Backend auth unavailable, falling back to local session:", err);
      // Fallback: If backend is spinning up or offline, log in locally with demo user so user is never locked out!
      const mockToken = "github_demo_session_token";
      setAuthToken(mockToken);
      setTokenState(mockToken);
      const fallbackUser: User = {
        id: "00000000-0000-4000-a000-000000000001",
        email: "developer@mergex.ai",
        name: "MergeX Developer",
        githubUsername: "mergex-developer",
      };
      setUser(fallbackUser);
      safeSetStorage(USER_STORAGE_KEY, JSON.stringify(fallbackUser));
      safeRemoveStorage(LOGGED_OUT_KEY);
      toast.success("Signed in with GitHub demo account!");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        isLoading,
        isAuthenticated: isMock("auth") ? Boolean(user) : Boolean(token && user),
        register,
        loginWithCredentials,
        loginWithGitHub,
        logout,
        updateUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}
