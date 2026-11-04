import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import { useAuth } from "@/hooks/use-auth";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Logo } from "@/components/Logo";
import { Loader2, AlertCircle, ArrowLeft } from "lucide-react";
import { useDocumentTitle } from "@/hooks/use-document-title";

export function AuthCallback() {
  useDocumentTitle("Authenticating with GitHub");
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { loginWithGitHubCallback } = useAuth();

  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const codeExchangedRef = useRef(false);

  useEffect(() => {
    // Prevent double execution in React StrictMode
    if (codeExchangedRef.current) return;

    const code = searchParams.get("code");
    const error = searchParams.get("error");
    const errorDescription = searchParams.get("error_description");

    if (error) {
      setErrorMessage(errorDescription || "GitHub authorization was denied or cancelled.");
      return;
    }

    if (!code) {
      setErrorMessage("No authorization code received from GitHub.");
      return;
    }

    codeExchangedRef.current = true;
    const redirectUri = `${window.location.origin}/login/callback`;

    void (async () => {
      try {
        await loginWithGitHubCallback(code, redirectUri);
        void navigate("/dashboard", { replace: true });
      } catch (err: unknown) {
        const msg =
          err instanceof Error
            ? err.message
            : "Failed to exchange GitHub authorization code. Please try again.";
        setErrorMessage(msg);
      }
    })();
  }, [searchParams, loginWithGitHubCallback, navigate]);

  return (
    <div className="flex min-h-[calc(100vh-12rem)] items-center justify-center px-4 py-12 sm:px-6">
      <Card className="bg-card w-full max-w-md border shadow-lg">
        <CardHeader className="space-y-3 pb-4 text-center">
          <div className="flex justify-center">
            <Logo size="lg" />
          </div>
          <div>
            <CardTitle className="text-foreground text-2xl font-bold tracking-tight">
              {errorMessage ? "Authentication Failed" : "Authenticating with GitHub"}
            </CardTitle>
            <CardDescription className="text-muted-foreground mt-1 text-sm">
              {errorMessage
                ? "We could not complete your GitHub sign-in."
                : "Securing connection, retrieving profile, and setting up your workspace..."}
            </CardDescription>
          </div>
        </CardHeader>

        <CardContent className="space-y-6 pt-2 text-center">
          {errorMessage ? (
            <div className="space-y-4">
              <div className="bg-destructive/10 text-destructive flex items-center justify-center gap-2 rounded-lg p-3 text-sm">
                <AlertCircle className="size-4 shrink-0" />
                <span>{errorMessage}</span>
              </div>
              <Button asChild variant="default" className="w-full gap-2 font-medium">
                <Link to="/login">
                  <ArrowLeft className="size-4" /> Return to Login
                </Link>
              </Button>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-6">
              <Loader2 className="text-primary size-10 animate-spin" />
              <p className="text-muted-foreground mt-4 text-xs font-medium">
                Completing OAuth handshake...
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
