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
import { Separator } from "@/components/ui/separator";
import { Logo } from "@/components/Logo";
import { ArrowRight, Loader2 } from "lucide-react";
import { useDocumentTitle } from "@/hooks/use-document-title";

/**
 * Clean SVG GitHub icon to adhere to requirement of having a Github icon
 * without missing icon exports in lucide-react.
 */
function GitHubIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"
      />
    </svg>
  );
}

export function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const { loginWithCredentials, register, loginWithGitHub, isLoading } = useAuth();
  const [isSignUp, setIsSignUp] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
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
          setIsSubmitting(false);
        }
      })();
    }
  };

  const handleGitHubAuth = () => {
    void (async () => {
      try {
        await loginWithGitHub();
        void navigate(redirectPath, { replace: true });
      } catch {
        // Handled
      }
    })();
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
          {/* GitHub OAuth Button */}
          <Button
            type="button"
            variant="outline"
            className="hover:bg-muted h-auto min-h-10 w-full gap-2 py-2.5 font-medium transition-colors"
            onClick={handleGitHubAuth}
          >
            <GitHubIcon className="size-4" />
            <span>Continue with GitHub</span>
          </Button>

          {/* Divider */}
          <div className="relative my-2">
            <div className="absolute inset-0 flex items-center">
              <Separator />
            </div>
            <div className="relative flex justify-center text-xs uppercase">
              <span className="bg-card text-muted-foreground px-2 font-medium">or</span>
            </div>
          </div>

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
