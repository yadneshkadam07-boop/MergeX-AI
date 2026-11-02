import React, { useState, useEffect, useCallback } from "react";
import { isMock, config } from "@/lib/config";
import { http, setAuthToken, getAuthToken, ApiError } from "@/lib/http";
import { toast } from "sonner";
import { AuthContext, type User } from "./auth-context-def";

export type { User, AuthContextType } from "./auth-context-def";

const MOCK_USER: User = {
  id: "usr_mock_01",
  email: "devin@mergex.ai",
  name: "Devin Vance",
  avatarUrl: "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150",
  githubUsername: "mergex-engineer",
};

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setTokenState] = useState<string | null>(getAuthToken());
  const [user, setUser] = useState<User | null>(() => {
    if (isMock("auth")) {
      return MOCK_USER;
    }
    return null;
  });
  const [isLoading, setIsLoading] = useState<boolean>(!isMock("auth"));

  const logout = useCallback(() => {
    setAuthToken(null);
    setTokenState(null);
    setUser(null);
    toast.info("You have been signed out.");
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
        setAuthToken(mockToken);
        setTokenState(mockToken);
        setUser({
          ...MOCK_USER,
          email,
          name: name?.trim() || email.split("@")[0] || "MergeX Developer",
        });
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

      if (res.user) {
        setUser(res.user);
      } else {
        const profile = await http.get<User>("/auth/me");
        setUser(profile);
      }

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
        setAuthToken(mockToken);
        setTokenState(mockToken);
        setUser({
          ...MOCK_USER,
          email,
          name: email.split("@")[0] || "MergeX Developer",
        });
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

      if (res.user) {
        setUser(res.user);
      } else {
        const profile = await http.get<User>("/auth/me");
        setUser(profile);
      }

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
      setUser(MOCK_USER);
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

      if (res.user) {
        setUser(res.user);
      } else {
        const profile = await http.get<User>("/auth/me");
        setUser(profile);
      }

      toast.success("Connected via GitHub demo credentials!");
    } catch (err) {
      console.error("Demo GitHub login failed:", err);
      toast.error("Failed to authenticate demo account. Please log in with email.");
      throw err;
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
        isAuthenticated: isMock("auth") ? true : Boolean(token && user),
        register,
        loginWithCredentials,
        loginWithGitHub,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}
