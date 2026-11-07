import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Check, Crown, Loader2, ShieldCheck, Sparkles, Zap } from "lucide-react";
import { createCheckoutSession } from "@/lib/api/billing";
import { config } from "@/lib/config";

interface UpgradeModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  currentTier?: string;
}

export function UpgradeModal({ open, onOpenChange, currentTier = "free" }: UpgradeModalProps) {
  const [loadingPlan, setLoadingPlan] = useState<string | null>(null);

  const handleSelectPlan = async (plan: "pro" | "team") => {
    setLoadingPlan(plan);
    try {
      const res = await createCheckoutSession(plan);
      if (res.checkout_url) {
        window.location.href = res.checkout_url;
        return;
      }
    } catch (err) {
      console.warn("API checkout session fallback to Gumroad:", err);
      const cleanUrl = (config.gumroadProUrl || "https://yadnesh18.gumroad.com/l/hdcpvr").split(
        "?",
      )[0]!;
      window.location.href = cleanUrl;
      return;
    } finally {
      setLoadingPlan(null);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl overflow-hidden p-0 sm:max-w-4xl">
        <div className="from-primary/10 via-background to-background bg-gradient-to-b p-6 sm:p-8">
          <DialogHeader className="text-center">
            <div className="bg-primary/10 text-primary mx-auto mb-2 flex size-12 items-center justify-center rounded-full">
              <Sparkles className="size-6" />
            </div>
            <DialogTitle className="text-2xl font-extrabold sm:text-3xl">
              Supercharge your Code Quality
            </DialogTitle>
            <DialogDescription className="text-muted-foreground mx-auto max-w-lg text-sm">
              Prevent broken deployments, schema drift, and route mismatches before code hits
              production.
            </DialogDescription>
          </DialogHeader>

          <div className="mt-8 grid gap-6 sm:grid-cols-3">
            {/* Free Plan */}
            <div className="bg-card flex flex-col justify-between rounded-xl border p-5 shadow-sm">
              <div>
                <div className="flex items-center justify-between">
                  <h3 className="text-foreground font-semibold">Starter</h3>
                  {currentTier === "free" && <Badge variant="secondary">Current</Badge>}
                </div>
                <div className="mt-3 flex items-baseline">
                  <span className="text-foreground text-3xl font-bold tracking-tight">$0</span>
                  <span className="text-muted-foreground ml-1 text-xs">/month</span>
                </div>
                <p className="text-muted-foreground mt-2 text-xs">
                  Perfect for hobbyists and individual open-source testing.
                </p>
                <ul className="text-muted-foreground mt-4 space-y-2.5 text-xs">
                  <li className="flex items-center gap-2">
                    <Check className="text-primary size-3.5" />
                    <span>Up to 5 repository scans/month</span>
                  </li>
                  <li className="flex items-center gap-2">
                    <Check className="text-primary size-3.5" />
                    <span>Public GitHub repositories</span>
                  </li>
                  <li className="flex items-center gap-2">
                    <Check className="text-primary size-3.5" />
                    <span>Deterministic rule auditing</span>
                  </li>
                </ul>
              </div>
              <Button variant="outline" className="mt-6 w-full text-xs" disabled>
                {currentTier === "free" ? "Active Plan" : "Downgrade"}
              </Button>
            </div>

            {/* Pro Plan (Highlighted) */}
            <div className="border-primary bg-card relative flex flex-col justify-between rounded-xl border-2 p-5 shadow-lg">
              <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                <Badge className="bg-primary text-primary-foreground px-3 py-0.5 text-[11px] font-semibold shadow">
                  MOST POPULAR
                </Badge>
              </div>
              <div>
                <div className="flex items-center justify-between">
                  <div className="text-primary flex items-center gap-1.5 font-semibold">
                    <Crown className="size-4" />
                    <span>Developer Pro</span>
                  </div>
                  {currentTier === "pro" && <Badge>Current</Badge>}
                </div>
                <div className="mt-3 flex items-baseline">
                  <span className="text-foreground text-3xl font-extrabold tracking-tight">
                    $29
                  </span>
                  <span className="text-muted-foreground ml-1 text-xs">/month</span>
                </div>
                <p className="text-muted-foreground mt-2 text-xs">
                  For professional developers and startups shipping fast.
                </p>
                <ul className="text-foreground mt-4 space-y-2.5 text-xs">
                  <li className="flex items-center gap-2">
                    <Check className="text-primary size-3.5 font-bold" />
                    <span className="font-medium">Unlimited repository scans</span>
                  </li>
                  <li className="flex items-center gap-2">
                    <Check className="text-primary size-3.5 font-bold" />
                    <span className="font-medium">1-Click GitHub Pull Request fixes</span>
                  </li>
                  <li className="flex items-center gap-2">
                    <Check className="text-primary size-3.5 font-bold" />
                    <span className="text-primary font-semibold">
                      Private & public repositories
                    </span>
                  </li>
                  <li className="flex items-center gap-2">
                    <Check className="text-primary size-3.5 font-bold" />
                    <span>Real-time SSE live stream diagnostics</span>
                  </li>
                  <li className="flex items-center gap-2">
                    <Check className="text-primary size-3.5 font-bold" />
                    <span>Exportable PDF & Markdown reports</span>
                  </li>
                </ul>
              </div>
              <Button
                className="mt-6 w-full gap-2 font-semibold shadow"
                disabled={loadingPlan !== null || currentTier === "pro"}
                onClick={() => handleSelectPlan("pro")}
              >
                {loadingPlan === "pro" ? (
                  <>
                    <Loader2 className="size-4 animate-spin" />
                    <span>Redirecting to Checkout...</span>
                  </>
                ) : currentTier === "pro" ? (
                  "Active Plan"
                ) : (
                  <>
                    <Zap className="size-4" />
                    <span>Upgrade to Pro</span>
                  </>
                )}
              </Button>
            </div>

            {/* Team Plan */}
            <div className="bg-card flex flex-col justify-between rounded-xl border p-5 shadow-sm">
              <div>
                <div className="flex items-center justify-between">
                  <h3 className="text-foreground font-semibold">Team / Agency</h3>
                  {currentTier === "team" && <Badge>Current</Badge>}
                </div>
                <div className="mt-3 flex items-baseline">
                  <span className="text-foreground text-3xl font-bold tracking-tight">$99</span>
                  <span className="text-muted-foreground ml-1 text-xs">/month</span>
                </div>
                <p className="text-muted-foreground mt-2 text-xs">
                  For engineering teams, agencies, and multi-repo architectures.
                </p>
                <ul className="text-muted-foreground mt-4 space-y-2.5 text-xs">
                  <li className="flex items-center gap-2">
                    <Check className="text-primary size-3.5" />
                    <span>Everything in Pro</span>
                  </li>
                  <li className="flex items-center gap-2">
                    <Check className="text-primary size-3.5" />
                    <span>Up to 10 developer seats</span>
                  </li>
                  <li className="flex items-center gap-2">
                    <Check className="text-primary size-3.5" />
                    <span>Custom Tree-sitter architectural rules</span>
                  </li>
                  <li className="flex items-center gap-2">
                    <Check className="text-primary size-3.5" />
                    <span>Priority background worker queues</span>
                  </li>
                </ul>
              </div>
              <Button
                variant="outline"
                className="mt-6 w-full text-xs font-semibold"
                disabled={loadingPlan !== null || currentTier === "team"}
                onClick={() => handleSelectPlan("team")}
              >
                {loadingPlan === "team" ? (
                  <>
                    <Loader2 className="size-4 animate-spin" />
                    <span>Redirecting...</span>
                  </>
                ) : currentTier === "team" ? (
                  "Active Plan"
                ) : (
                  "Get Team Plan"
                )}
              </Button>
            </div>

            <div className="text-muted-foreground mt-6 flex items-center justify-center gap-2 text-xs">
              <ShieldCheck className="text-primary size-4" />
              <span>
                Instant activation via Gumroad · Cancel anytime · Supports International Cards, UPI,
                PayPal & Apple Pay
              </span>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
