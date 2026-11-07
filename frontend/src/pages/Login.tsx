import React, { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "@/hooks/use-auth";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Logo } from "@/components/Logo";
import { ArrowRight, Loader2 } from "lucide-react";
import { useDocumentTitle } from "@/hooks/use-document-title";

export function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const { loginWithCredentials, register, isLoading } = useAuth();
  const [isSignUp, setIsSignUp] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showWakingMessage, setShowWakingMessage] = useState(false);
  useDocumentTitle(isSignUp ? "Create an account" : "Sign in");

  const locationState = location.state as { from?: { pathname?: string } } | null;
  const redirectPath = locationState?.from?.pathname || "/dashboard";

  // Form states
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");

  // Validation errors
  const [errors, setErrors] = useState<{
    email?: string;
    password?: string;
    name?: string;
  }>({});

  const validate = () => {
    const newErrors: { email?: string; password?: string; name?: string } = {};

    if (isSignUp && !name.trim()) {
      newErrors.name = "Please enter your full name.";
    }

    if (!email.trim()) {
      newErrors.email = "Email address is required.";
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      newErrors.email = "Please enter a valid email address.";
    }

    if (!password) {
      newErrors.password = "Password is required.";
    } else if (password.length < 6) {
      newErrors.password = "Password must be at least 6 characters.";
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (validate()) {
      setIsSubmitting(true);
      setShowWakingMessage(false);
      const timer = setTimeout(() => setShowWakingMessage(true), 3500);

      void (async () => {
        try {
          if (isSignUp) {
            await register(email, password, name);
          } else {
            await loginWithCredentials(email, password);
          }
          void navigate(redirectPath, { replace: true });
        } catch {
          // Toast handled by AuthContext
        } finally {
          clearTimeout(timer);
          setShowWakingMessage(false);
          setIsSubmitting(false);
        }
      })();
    }
  };

  return (
    <div className="flex min-h-[calc(100vh-12rem)] items-center justify-center px-4 py-12 sm:px-6">
      <Card className="bg-card w-full max-w-md border shadow-lg">
        <CardHeader className="space-y-3 pb-4 text-center">
          <div className="flex justify-center">
            <Logo size="lg" />
          </div>
          <div>
            <CardTitle className="text-foreground text-2xl font-bold tracking-tight">
              {isSignUp ? "Create your account" : "Welcome to MergeX AI"}
            </CardTitle>
            <CardDescription className="text-muted-foreground mt-1 text-sm">
              {isSignUp
                ? "Start inspecting your multi-agent repositories in seconds."
                : "Sign in to inspect integration, security, and deployment readiness."}
            </CardDescription>
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          {/* Email / Password Form */}
          <form onSubmit={handleSubmit} noValidate className="space-y-3.5">
            {isSignUp && (
              <div className="space-y-1.5">
                <Label htmlFor="name" className="text-xs font-semibold">
                  Full Name
                </Label>
                <Input
                  id="name"
                  type="text"
                  placeholder="Alex Rivers"
                  value={name}
                  onChange={(e) => {
                    setName(e.target.value);
                    if (errors.name) {
                      const { name: _, ...rest } = errors;
                      setErrors(rest);
                    }
                  }}
                  className={errors.name ? "border-destructive focus-visible:ring-destructive" : ""}
                  aria-invalid={!!errors.name}
                  aria-describedby={errors.name ? "name-error" : undefined}
                />
                {errors.name && (
                  <p id="name-error" className="text-destructive text-xs font-medium">
                    {errors.name}
                  </p>
                )}
              </div>
            )}

            <div className="space-y-1.5">
              <Label htmlFor="email" className="text-xs font-semibold">
                Work Email
              </Label>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                placeholder="developer@company.com"
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  if (errors.email) {
                    const { email: _, ...rest } = errors;
                    setErrors(rest);
                  }
                }}
                className={errors.email ? "border-destructive focus-visible:ring-destructive" : ""}
                aria-invalid={!!errors.email}
                aria-describedby={errors.email ? "email-error" : undefined}
              />
              {errors.email && (
                <p id="email-error" className="text-destructive text-xs font-medium">
                  {errors.email}
                </p>
              )}
            </div>

            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <Label htmlFor="password" className="text-xs font-semibold">
                  Password
                </Label>
                {!isSignUp && (
                  <button
                    type="button"
                    onClick={() => alert("Password reset link will be sent to your email.")}
                    className="text-muted-foreground hover:text-foreground text-xs transition-colors hover:underline"
                  >
                    Forgot password?
                  </button>
                )}
              </div>
              <Input
                id="password"
                type="password"
                autoComplete={isSignUp ? "new-password" : "current-password"}
                placeholder="••••••••••••"
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  if (errors.password) {
                    const { password: _, ...rest } = errors;
                    setErrors(rest);
                  }
                }}
                className={
                  errors.password ? "border-destructive focus-visible:ring-destructive" : ""
                }
                aria-invalid={!!errors.password}
                aria-describedby={errors.password ? "password-error" : undefined}
              />
              {errors.password && (
                <p id="password-error" className="text-destructive text-xs font-medium">
                  {errors.password}
                </p>
              )}
            </div>

            <Button
              type="submit"
              className="mt-2 h-auto min-h-10 w-full py-2.5 font-semibold"
              disabled={isSubmitting || isLoading}
            >
              {isSubmitting || isLoading ? (
                <>
                  <Loader2 className="mr-2 size-4 animate-spin" />
                  <span>{isSignUp ? "Creating account..." : "Signing in..."}</span>
                </>
              ) : (
                <>
                  <span>{isSignUp ? "Create account" : "Log in"}</span>
                  <ArrowRight className="ml-1.5 size-4" />
                </>
              )}
            </Button>
            {showWakingMessage && (
              <p className="text-muted-foreground animate-pulse text-center text-xs">
                Waking server up... Render free tier instances take ~30s on cold start.
              </p>
            )}
          </form>
        </CardContent>

        <CardFooter className="text-muted-foreground flex justify-center border-t py-4 text-xs">
          {isSignUp ? (
            <p>
              Already have an account?{" "}
              <button
                type="button"
                onClick={() => {
                  setIsSignUp(false);
                  setErrors({});
                }}
                className="text-foreground font-semibold hover:underline"
              >
                Log in
              </button>
            </p>
          ) : (
            <p>
              New to MergeX AI?{" "}
              <button
                type="button"
                onClick={() => {
                  setIsSignUp(true);
                  setErrors({});
                }}
                className="text-foreground font-semibold hover:underline"
              >
                Create account
              </button>
            </p>
          )}
        </CardFooter>
      </Card>
    </div>
  );
}
