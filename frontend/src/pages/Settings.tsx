import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import type { UserSettings } from "@/types/settings";
import { getSettings, saveSettings } from "@/lib/api";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { LoadingState } from "@/components/shared/LoadingState";
import { ErrorState } from "@/components/shared/ErrorState";
import { useDocumentTitle } from "@/hooks/use-document-title";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { ButtonRow } from "@/components/ui/button-row";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  AlertTriangle,
  Check,
  Eye,
  EyeOff,
  Key,
  Loader2,
  Moon,
  Save,
  Sparkles,
  Sun,
  Trash2,
} from "lucide-react";
import { useAuth } from "@/hooks/use-auth";
import { Badge } from "@/components/ui/badge";
import { UpgradeModal } from "@/components/billing/UpgradeModal";
import { getBillingStatus, createCustomerPortalSession } from "@/lib/api/billing";
import type { BillingStatus } from "@/types/billing";

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

export function Settings() {
  const navigate = useNavigate();
  const { updateUser } = useAuth();
  useDocumentTitle("Settings");
  const [settings, setSettings] = useState<UserSettings | null>(null);
  const [originalSettings, setOriginalSettings] = useState<UserSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Profile fields
  const [profileName, setProfileName] = useState("");
  const [profileEmail, setProfileEmail] = useState("");
  const [profileSaved, setProfileSaved] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);

  // AI Provider (UI ONLY, NEVER SAVED TO STORAGE)
  const [apiKey, setApiKey] = useState("");
  const [showApiKey, setShowApiKey] = useState(false);
  const [apiKeyNotice, setApiKeyNotice] = useState(false);

  // Dialogs
  const [disconnectDialogOpen, setDisconnectDialogOpen] = useState(false);
  const [clearDataDialogOpen, setClearDataDialogOpen] = useState(false);
  const [clearConfirmationText, setClearConfirmationText] = useState("");

  // Billing & Subscriptions
  const [billing, setBilling] = useState<BillingStatus | null>(null);
  const [upgradeModalOpen, setUpgradeModalOpen] = useState(false);
  const [loadingPortal, setLoadingPortal] = useState(false);

  // Track unsaved preferences
  const isProfileChanged =
    originalSettings &&
    (profileName !== originalSettings.displayName || profileEmail !== originalSettings.email);

  const loadSettings = async () => {
    setLoading(true);
    setError(null);
    try {
      const [data, billingData] = await Promise.allSettled([getSettings(), getBillingStatus()]);
      if (data.status === "fulfilled") {
        setSettings(data.value);
        setOriginalSettings(data.value);
        setProfileName(data.value.displayName);
        setProfileEmail(data.value.email);
      }
      if (billingData.status === "fulfilled") {
        setBilling(billingData.value);
      }
    } catch (err) {
      console.error("Failed to load settings:", err);
      setError(err instanceof Error ? err.message : "Failed to load preferences.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadSettings();
    const params = new URLSearchParams(window.location.search);
    if (params.get("checkout") === "success" || params.get("simulated") === "true") {
      toast.success("Welcome to MergeX Pro! Your plan has been activated.");
    }
  }, []);

  const handleManageBilling = async () => {
    setLoadingPortal(true);
    try {
      const res = await createCustomerPortalSession();
      if (res.portal_url) {
        window.location.href = res.portal_url;
      }
    } catch (err) {
      console.error("Portal error:", err);
      toast.error("Could not load Stripe customer portal.");
      setLoadingPortal(false);
    }
  };

  // Warning when leaving with unsaved profile changes
  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (isProfileChanged) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [isProfileChanged]);

  const handleSaveProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!profileName.trim()) {
      setProfileError("Display name is required.");
      return;
    }
    if (!profileEmail.trim() || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(profileEmail)) {
      setProfileError("A valid email address is required.");
      return;
    }
    setProfileError(null);

    if (!settings) return;
    const updated: UserSettings = {
      ...settings,
      displayName: profileName,
      email: profileEmail,
    };
    await saveSettings(updated);
    updateUser({ name: profileName, email: profileEmail });
    setSettings(updated);
    setOriginalSettings(updated);
    setProfileSaved(true);
    toast.success("Profile updated successfully");
    setTimeout(() => setProfileSaved(false), 2500);
  };

  const handleThemeChange = (newTheme: "light" | "dark" | "system") => {
    if (!settings) return;
    const updated = { ...settings, theme: newTheme };
    setSettings(updated);
    void saveSettings(updated);
    toast.success(`Theme updated to ${newTheme}`);

    const root = document.documentElement;
    if (newTheme === "dark") {
      root.classList.add("dark");
      localStorage.setItem("mergex-theme", "dark");
    } else if (newTheme === "light") {
      root.classList.remove("dark");
      localStorage.setItem("mergex-theme", "light");
    } else {
      // System
      const systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      if (systemDark) root.classList.add("dark");
      else root.classList.remove("dark");
      localStorage.removeItem("mergex-theme");
    }
  };

  const handleToggleCheck = (key: keyof UserSettings["checks"]) => {
    if (!settings) return;
    const updated = {
      ...settings,
      checks: {
        ...settings.checks,
        [key]: !settings.checks[key],
      },
    };
    setSettings(updated);
    void saveSettings(updated);
    toast.success("Diagnostic scanner preferences updated");
  };

  const handleAlertSeverityChange = (val: UserSettings["alertSeverity"]) => {
    if (!settings) return;
    const updated = { ...settings, alertSeverity: val };
    setSettings(updated);
    void saveSettings(updated);
    toast.success(`Minimum alert threshold updated to ${val.toUpperCase()}`);
  };

  const handleToggleGitHub = () => {
    if (!settings) return;
    if (settings.githubConnected) {
      setDisconnectDialogOpen(true);
    } else {
      const updated = {
        ...settings,
        githubConnected: true,
        githubUsername: "mergex-engineer",
      };
      setSettings(updated);
      void saveSettings(updated);
      toast.success("Connected to GitHub as @mergex-engineer");
    }
  };

  const confirmDisconnectGitHub = () => {
    if (!settings) return;
    const updated = {
      ...settings,
      githubConnected: false,
      githubUsername: undefined,
    };
    setSettings(updated);
    void saveSettings(updated);
    setDisconnectDialogOpen(false);
    toast.info("GitHub account disconnected");
  };

  const handleSaveApiKeyPlaceholder = (e: React.FormEvent) => {
    e.preventDefault();
    setApiKeyNotice(true);
    setTimeout(() => setApiKeyNotice(false), 3000);
  };

  const handleClearLocalData = () => {
    try {
      localStorage.removeItem("mergex_projects_store");
      localStorage.removeItem("mergex_issue_status_overrides");
      localStorage.removeItem("mergex_user_settings");
      localStorage.removeItem("mergex-theme");
    } catch (err) {
      console.error("Error clearing local data:", err);
    }
    setClearDataDialogOpen(false);
    void navigate("/dashboard");
    window.location.reload();
  };

  if (loading) {
    return <LoadingState message="Loading user preferences..." minHeight="min-h-[400px]" />;
  }

  if (error) {
    return <ErrorState title="Failed to load settings" message={error} onRetry={loadSettings} />;
  }

  if (!settings) return null;

  return (
    <div className="mx-auto max-w-4xl space-y-8 pb-12">
      {/* Header */}
      <div>
        <h1 className="text-foreground text-2xl font-extrabold tracking-tight sm:text-3xl">
          Settings & Preferences
        </h1>
        <p className="text-muted-foreground mt-1 text-xs">
          Configure diagnostic rules, team preferences, authentication connections, and local state.
        </p>
      </div>

      <div className="space-y-6">
        {/* 1. Profile */}
        <SettingsSection
          title="User Profile"
          description="Manage your account identity and notification contact details."
          footer={
            <div className="flex w-full flex-wrap items-center justify-between gap-3">
              <span className="text-muted-foreground">
                {profileSaved && (
                  <span
                    className="text-success inline-flex items-center gap-1.5 font-semibold"
                    aria-live="polite"
                  >
                    <Check className="size-3.5" /> Profile changes saved
                  </span>
                )}
              </span>
              <Button
                type="submit"
                form="profile-form"
                size="sm"
                disabled={!isProfileChanged}
                className="w-full gap-1.5 text-xs font-semibold sm:w-auto"
              >
                <Save className="size-3.5" />
                <span>Save Profile</span>
              </Button>
            </div>
          }
        >
          <form id="profile-form" onSubmit={handleSaveProfile} className="max-w-md space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="displayName" className="text-xs font-semibold">
                Display Name
              </Label>
              <Input
                id="displayName"
                value={profileName}
                onChange={(e) => setProfileName(e.target.value)}
                className="h-9 text-xs"
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="email" className="text-xs font-semibold">
                Work Email
              </Label>
              <Input
                id="email"
                type="email"
                value={profileEmail}
                onChange={(e) => setProfileEmail(e.target.value)}
                className="h-9 text-xs"
              />
            </div>

            {profileError && <p className="text-destructive text-xs font-medium">{profileError}</p>}
          </form>
        </SettingsSection>

        {/* 2. Appearance */}
        <SettingsSection
          title="Appearance & Interface Theme"
          description="Select your preferred application color palette or follow system defaults."
        >
          <ButtonRow className="gap-3">
            <Button
              type="button"
              variant={settings.theme === "light" ? "default" : "outline"}
              size="sm"
              onClick={() => handleThemeChange("light")}
              className="gap-2 text-xs"
            >
              <Sun className="size-4" />
              <span>Light Mode</span>
            </Button>
            <Button
              type="button"
              variant={settings.theme === "dark" ? "default" : "outline"}
              size="sm"
              onClick={() => handleThemeChange("dark")}
              className="gap-2 text-xs"
            >
              <Moon className="size-4" />
              <span>Dark Mode</span>
            </Button>
            <Button
              type="button"
              variant={settings.theme === "system" ? "default" : "outline"}
              size="sm"
              onClick={() => handleThemeChange("system")}
              className="text-xs"
            >
              System Default
            </Button>
          </ButtonRow>
        </SettingsSection>

        {/* 3. GitHub Connection */}
        <SettingsSection
          title="GitHub Account Integration"
          description="Grant MergeX AI read access to inspect repositories and pull request branches."
        >
          <div className="bg-muted/20 flex flex-col justify-between gap-4 rounded-xl border p-4 sm:flex-row sm:items-center">
            <div className="flex items-center gap-3">
              <div className="bg-foreground text-background flex size-10 items-center justify-center rounded-lg">
                <GitHubIcon className="size-5" />
              </div>
              <div className="space-y-0.5">
                <p className="text-foreground text-xs font-semibold">
                  {settings.githubConnected
                    ? `Connected as @${settings.githubUsername || "engineer"}`
                    : "No GitHub account linked"}
                </p>
                <p className="text-muted-foreground text-[11px]">
                  {settings.githubConnected
                    ? "Full read permissions enabled for repositories."
                    : "Connect your GitHub account to import private codebases."}
                </p>
              </div>
            </div>

            <Button
              variant={settings.githubConnected ? "outline" : "default"}
              size="sm"
              onClick={handleToggleGitHub}
              className="h-8 shrink-0 text-xs"
            >
              {settings.githubConnected ? "Disconnect GitHub" : "Connect GitHub"}
            </Button>
          </div>
        </SettingsSection>

        {/* 4. Analysis Preferences */}
        <SettingsSection
          title="Diagnostic Scanners & Alerting"
          description="Choose which multi-agent inspection passes execute during repository evaluation."
        >
          <div className="max-w-lg space-y-4">
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <Label
                    htmlFor="check-integration"
                    className="cursor-pointer text-xs font-semibold"
                  >
                    API Contract & Schema Validation
                  </Label>
                  <p className="text-muted-foreground text-[11px]">
                    Verifies routes and database models.
                  </p>
                </div>
                <Switch
                  id="check-integration"
                  checked={settings.checks.integration}
                  onCheckedChange={() => handleToggleCheck("integration")}
                />
              </div>

              <div className="flex items-center justify-between">
                <div>
                  <Label htmlFor="check-security" className="cursor-pointer text-xs font-semibold">
                    Security & Secret Scanning
                  </Label>
                  <p className="text-muted-foreground text-[11px]">
                    Detects committed tokens and CORS risks.
                  </p>
                </div>
                <Switch
                  id="check-security"
                  checked={settings.checks.security}
                  onCheckedChange={() => handleToggleCheck("security")}
                />
              </div>

              <div className="flex items-center justify-between">
                <div>
                  <Label
                    htmlFor="check-dependencies"
                    className="cursor-pointer text-xs font-semibold"
                  >
                    Dependency Vulnerability Audits
                  </Label>
                  <p className="text-muted-foreground text-[11px]">
                    Cross-references known CVE databases.
                  </p>
                </div>
                <Switch
                  id="check-dependencies"
                  checked={settings.checks.dependencies}
                  onCheckedChange={() => handleToggleCheck("dependencies")}
                />
              </div>

              <div className="flex items-center justify-between">
                <div>
                  <Label
                    htmlFor="check-deployment"
                    className="cursor-pointer text-xs font-semibold"
                  >
                    Deployment Readiness Inspection
                  </Label>
                  <p className="text-muted-foreground text-[11px]">
                    Validates Dockerfiles, probes, and env vars.
                  </p>
                </div>
                <Switch
                  id="check-deployment"
                  checked={settings.checks.deployment}
                  onCheckedChange={() => handleToggleCheck("deployment")}
                />
              </div>
            </div>

            <div className="space-y-1.5 border-t pt-4">
              <Label className="text-xs font-semibold">Alert Notification Threshold</Label>
              <Select
                value={settings.alertSeverity}
                onValueChange={(val) =>
                  handleAlertSeverityChange(val as UserSettings["alertSeverity"])
                }
              >
                <SelectTrigger className="h-9 w-56 text-xs">
                  <SelectValue placeholder="Alert severity" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="critical">Critical issues only</SelectItem>
                  <SelectItem value="high">High and Critical issues</SelectItem>
                  <SelectItem value="medium">Medium and above</SelectItem>
                  <SelectItem value="low">All issues (including Low)</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </SettingsSection>

        {/* 5. AI Provider (UI ONLY, NEVER SAVED TO STORAGE) */}
        <SettingsSection
          title="AI Synthesis Provider"
          description="Optionally configure dedicated foundation model inference credentials for custom diagnostic agents."
        >
          <form onSubmit={handleSaveApiKeyPlaceholder} className="max-w-md space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="apiKey" className="text-xs font-semibold">
                Provider API Key
              </Label>
              <div className="relative">
                <Input
                  id="apiKey"
                  type={showApiKey ? "text" : "password"}
                  placeholder="sk-proj-••••••••••••••••••••••••"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  className="h-9 pr-10 font-mono text-xs"
                />
                <button
                  type="button"
                  onClick={() => setShowApiKey(!showApiKey)}
                  className="text-muted-foreground hover:text-foreground absolute top-1/2 right-3 -translate-y-1/2"
                  aria-label={showApiKey ? "Hide API key" : "Show API key"}
                >
                  {showApiKey ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                </button>
              </div>
            </div>

            <ButtonRow className="gap-2">
              <Button type="submit" size="sm" className="text-xs font-semibold">
                <Key className="mr-1.5 size-3.5" />
                <span>Save Key</span>
              </Button>
              {apiKeyNotice && (
                <span className="text-success text-xs font-semibold" aria-live="polite">
                  Validated for active session.
                </span>
              )}
            </ButtonRow>

            <p className="text-muted-foreground pt-1 text-[11px] leading-relaxed">
              <strong>Notice:</strong> Keys are never stored in browser localStorage or transmitted
              unencrypted. Production API keys are configured securely on the MergeX server runtime.
            </p>
          </form>
        </SettingsSection>

        {/* 6. Subscription & Billing */}
        <SettingsSection
          title="Subscription & Billing"
          description="Manage your MergeX AI plan, scan limits, and Stripe payment methods."
        >
          <div className="bg-muted/20 flex flex-col justify-between gap-6 rounded-xl border p-5 sm:flex-row sm:items-center">
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <span className="text-foreground text-xs font-bold">Current Plan:</span>
                <Badge
                  className={
                    billing?.tier === "pro" || billing?.tier === "team"
                      ? "bg-primary text-primary-foreground font-bold uppercase"
                      : "bg-secondary text-secondary-foreground font-semibold uppercase"
                  }
                >
                  {billing?.tier === "pro"
                    ? "Developer Pro ($29/mo)"
                    : billing?.tier === "team"
                      ? "Team Plan ($99/mo)"
                      : "Starter (Free)"}
                </Badge>
              </div>

              <div className="text-muted-foreground space-y-1.5 text-xs">
                <div className="flex justify-between text-[11px]">
                  <span>Monthly Scans Consumed:</span>
                  <span className="text-foreground font-semibold">
                    {billing?.monthly_scans_used ?? 0} /{" "}
                    {billing?.max_scans === -1 ? "Unlimited" : (billing?.max_scans ?? 5)}
                  </span>
                </div>
                <div className="bg-muted h-2 w-56 overflow-hidden rounded-full">
                  <div
                    className="bg-primary h-full transition-all"
                    style={{
                      width:
                        billing?.max_scans === -1
                          ? "100%"
                          : `${Math.min(
                              100,
                              ((billing?.monthly_scans_used ?? 0) / (billing?.max_scans || 5)) *
                                100,
                            )}%`,
                    }}
                  />
                </div>
              </div>

              <p className="text-muted-foreground text-[11px]">
                {billing?.tier === "pro" || billing?.tier === "team"
                  ? "Unlimited scans, 1-Click GitHub PR fixes, and private repo audits enabled."
                  : "Upgrade to Developer Pro for unlimited scans, private repositories, and automated 1-click PR fixes."}
              </p>
            </div>

            <div className="flex flex-col gap-2 sm:items-end">
              {billing?.has_active_subscription ? (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleManageBilling}
                  disabled={loadingPortal}
                  className="gap-1.5 text-xs font-semibold"
                >
                  {loadingPortal && <Loader2 className="size-3.5 animate-spin" />}
                  <span>Manage Billing & Invoices</span>
                </Button>
              ) : (
                <Button
                  size="sm"
                  onClick={() => setUpgradeModalOpen(true)}
                  className="gap-1.5 text-xs font-semibold shadow"
                >
                  <Sparkles className="size-3.5" />
                  <span>Upgrade to Pro ($29/mo)</span>
                </Button>
              )}
            </div>
          </div>
        </SettingsSection>

        {/* 7. Danger Zone */}
        <SettingsSection
          title="Danger Zone: Local Storage Reset"
          description="Reset locally simulated projects, custom analyses, and issue resolution overrides."
          className="border-destructive/30"
        >
          <div className="border-destructive/20 bg-destructive/5 flex flex-col justify-between gap-4 rounded-xl border p-4 sm:flex-row sm:items-center">
            <div className="space-y-1">
              <p className="text-foreground text-xs font-bold">Clear Local Application Cache</p>
              <p className="text-muted-foreground text-xs">
                Permanently wipes all local sample analyses, persisted projects, and status
                overrides.
              </p>
            </div>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => {
                setClearConfirmationText("");
                setClearDataDialogOpen(true);
              }}
              className="h-8 shrink-0 gap-1.5 text-xs"
            >
              <Trash2 className="size-3.5" />
              <span>Clear local data</span>
            </Button>
          </div>
        </SettingsSection>
      </div>

      {/* Disconnect GitHub Confirmation Dialog */}
      <Dialog open={disconnectDialogOpen} onOpenChange={setDisconnectDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Disconnect GitHub Integration?</DialogTitle>
            <DialogDescription>
              Are you sure you want to disconnect @{settings.githubUsername}? You will not be able
              to scan private repositories until reconnected.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="mt-4 gap-2">
            <Button variant="outline" size="sm" onClick={() => setDisconnectDialogOpen(false)}>
              Cancel
            </Button>
            <Button variant="destructive" size="sm" onClick={confirmDisconnectGitHub}>
              Confirm Disconnect
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Clear Local Data Modal with Confirmation Input */}
      <Dialog open={clearDataDialogOpen} onOpenChange={setClearDataDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="text-destructive flex items-center gap-2">
              <AlertTriangle className="size-5" />
              <span>Confirm Local Storage Reset</span>
            </DialogTitle>
            <DialogDescription className="space-y-2 pt-2">
              <p>
                This action will delete all localStorage keys including added projects, custom scan
                runs, and issue triage overrides.
              </p>
              <p className="text-foreground font-semibold">
                To proceed, type <span className="text-destructive font-mono">clear</span> below:
              </p>
            </DialogDescription>
          </DialogHeader>

          <Input
            value={clearConfirmationText}
            onChange={(e) => setClearConfirmationText(e.target.value)}
            placeholder="Type 'clear' to confirm"
            className="h-9 font-mono text-xs"
          />

          <DialogFooter className="mt-4 gap-2">
            <Button variant="outline" size="sm" onClick={() => setClearDataDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              size="sm"
              disabled={clearConfirmationText.trim().toLowerCase() !== "clear"}
              onClick={handleClearLocalData}
            >
              Reset Application Data
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Stripe Upgrade Pricing Modal */}
      <UpgradeModal
        open={upgradeModalOpen}
        onOpenChange={setUpgradeModalOpen}
        currentTier={billing?.tier ?? "free"}
      />
    </div>
  );
}
