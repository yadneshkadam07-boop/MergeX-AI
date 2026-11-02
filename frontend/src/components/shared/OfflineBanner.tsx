import { useState, useEffect } from "react";
import { WifiOff, Wifi } from "lucide-react";

export function OfflineBanner() {
  const [isOffline, setIsOffline] = useState(
    typeof navigator !== "undefined" ? !navigator.onLine : false,
  );
  const [showRestored, setShowRestored] = useState(false);

  useEffect(() => {
    const handleOnline = () => {
      setIsOffline(false);
      setShowRestored(true);
      const timer = setTimeout(() => {
        setShowRestored(false);
      }, 3500);
      return () => clearTimeout(timer);
    };

    const handleOffline = () => {
      setIsOffline(true);
      setShowRestored(false);
    };

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);

    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  if (!isOffline && !showRestored) return null;

  if (showRestored) {
    return (
      <aside
        aria-label="Network status"
        role="status"
        className="bg-success text-primary-foreground animate-in fade-in slide-in-from-top-1 sticky top-0 z-50 flex items-center justify-center gap-2 px-4 py-1.5 text-xs font-semibold shadow-xs transition-all"
      >
        <Wifi className="size-3.5" />
        <span>Internet connection restored. Live features reconnected.</span>
      </aside>
    );
  }

  return (
    <aside
      aria-label="Network status"
      role="alert"
      className="bg-sev-high text-primary-foreground animate-in fade-in slide-in-from-top-1 sticky top-0 z-50 flex items-center justify-center gap-2 px-4 py-1.5 text-xs font-semibold shadow-xs transition-all"
    >
      <WifiOff className="size-3.5" />
      <span>You are currently offline. Changes will not sync until reconnected.</span>
    </aside>
  );
}
