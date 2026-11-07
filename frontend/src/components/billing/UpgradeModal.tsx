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
import { Check, Crown, Loader2, Sparkles, Zap } from "lucide-react";
import { createCheckoutSession } from "@/lib/api/billing";
import { toast } from "sonner";

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
      }
    } catch (err) {
      console.error("Failed to start checkout:", err);
      toast.error("Could not initiate checkout. Please try again.");
      setLoadingPlan(null);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl overflow-hidden p-0 sm:max-w-4xl">
        <div className="bg-gradient-to-b from-primary/10 via-background to-background p-6 sm:p-8">
          <DialogHeader className="text-center">
            <div className="mx-auto mb-2 flex size-12 items-center justify-center rounded-full bg-primary/10 text-primary">
              <Sparkles className="size-6" />
            </div>
            <DialogTitle className="text-2xl font-extrabold sm:text-3xl">
              Supercharge your Code Quality
            </DialogTitle>
            <DialogDescription className="mx-auto max-w-lg text-sm text-muted-foreground">
              Prevent broken deployments, schema drift, and route mismatches before code hits production.
            </DialogDescription>
          </DialogHeader>

          <div className="mt-8 grid gap-6 sm:grid-cols-3">
            {/* Free Plan */}
            <div className="flex flex-col justify-between rounded-xl border bg-card p-5 shadow-sm">
              <div>
                <div className="flex items-center justify-between">
                  <h3 className="font-semibold text-foreground">Starter</h3>
                  {currentTier === "free" && <Badge variant="secondary">Current</Badge>}
                </div>
                <div className="mt-3 flex items-baseline">
                  <span className="text-3xl font-bold tracking-tight text-foreground">$0</span>
                  <span className="ml-1 text-xs text-muted-foreground">/month</span>
                </div>
                <p className="mt-2 text-xs text-muted-foreground">
                  Perfect for hobbyists and individual open-source testing.
                </p>
                <ul className="mt-4 space-y-2.5 text-xs text-muted-foreground">
                  <li className="flex items-center gap-2">
                    <Check className="size-3.5 text-primary" />
                    <span>Up to 5 repository scans/month</span>
                  </li>
                  <li className="flex items-center gap-2">
                    <Check className="size-3.5 text-primary" />
                    <span>Public GitHub repositories</span>
                  </li>
                  <li className="flex items-center gap-2">
                    <Check className="size-3.5 text-primary" />
                    <span>Deterministic rule auditing</span>
                  </li>
                </ul>
              </div>
              <Button
                variant="outline"
                className="mt-6 w-full text-xs"
                disabled
              >
                {currentTier === "free" ? "Active Plan" : "Downgrade"}
              </Button>
            </div>

            {/* Pro Plan (Highlighted) */}
            <div className="relative flex flex-col justify-between rounded-xl border-2 border-primary bg-card p-5 shadow-lg">
              <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                <Badge className="bg-primary px-3 py-0.5 text-[11px] font-semibold text-primary-foreground shadow">
                  MOST POPULAR
                </Badge>
              </div>
              <div>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5 font-semibold text-primary">
                    <Crown className="size-4" />
                    <span>Developer Pro</span>
                  </div>
                  {currentTier === "pro" && <Badge>Current</Badge>}
                </div>
                <div className="mt-3 flex items-baseline">
                  <span className="text-3xl font-extrabold tracking-tight text-foreground">$29</span>
                  <span className="ml-1 text-xs text-muted-foreground">/month</span>
                </div>
                <p className="mt-2 text-xs text-muted-foreground">
                  For professional developers and startups shipping fast.
                </p>
                <ul className="mt-4 space-y-2.5 text-xs text-foreground">
                  <li className="flex items-center gap-2">
                    <Check className="size-3.5 text-primary font-bold" />
                    <span className="font-medium">Unlimited repository scans</span>
                  </li>
                  <li className="flex items-center gap-2">
                    <Check className="size-3.5 text-primary font-bold" />
                    <span className="font-medium">1-Click GitHub Pull Request fixes</span>
                  </li>
                  <li className="flex items-center gap-2">
                    <Check className="size-3.5 text-primary font-bold" />
                    <span>Private & public repositories</span>
                  </li>
                  <li className="flex items-center gap-2">
                    <Check className="size-3.5 text-primary font-bold" />
                    <span>Real-time SSE live stream diagnostics</span>
                  </li>
                  <li className="flex items-center gap-2">
                    <Check className="size-3.5 text-primary font-bold" />
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
                    <span>Redirecting to Stripe...</span>
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
            <div className="flex flex-col justify-between rounded-xl border bg-card p-5 shadow-sm">
              <div>
                <div className="flex items-center justify-between">
                  <h3 className="font-semibold text-foreground">Team / Agency</h3>
                  {currentTier === "team" && <Badge>Current</Badge>}
                </div>
                <div className="mt-3 flex items-baseline">
                  <span className="text-3xl font-bold tracking-tight text-foreground">$99</span>
                  <span className="ml-1 text-xs text-muted-foreground">/month</span>
                </div>
                <p className="mt-2 text-xs text-muted-foreground">
                  For engineering teams, agencies, and multi-repo architectures.
                </p>
                <ul className="mt-4 space-y-2.5 text-xs text-muted-foreground">
                  <li className="flex items-center gap-2">
                    <Check className="size-3.5 text-primary" />
                    <span>Everything in Pro</span>
                  </li>
                  <li className="flex items-center gap-2">
                    <Check className="size-3.5 text-primary" />
                    <span>Up to 10 developer seats</span>
                  </li>
                  <li className="flex items-center gap-2">
                    <Check className="size-3.5 text-primary" />
                    <span>Custom Tree-sitter architectural rules</span>
                  </li>
                  <li className="flex items-center gap-2">
                    <Check className="size-3.5 text-primary" />
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
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
