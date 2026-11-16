import { lazy, type ComponentType, type LazyExoticComponent } from "react";

/**
 * Lazy loads a component with automatic page reload retry if a chunk fails to load
 * due to a newly deployed frontend version replacing old asset hashes.
 */
export function lazyRetry<T extends ComponentType<any>>(
  factory: () => Promise<{ default: T }>,
): LazyExoticComponent<T> {
  return lazy(async () => {
    try {
      return await factory();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err || "");
      const isChunkError =
        msg.includes("Failed to fetch dynamically imported module") ||
        msg.includes("dynamically imported module") ||
        msg.includes("Importing a module script failed");

      if (isChunkError && typeof window !== "undefined") {
        const lastReloadTs = Number(sessionStorage.getItem("mergex_chunk_reload_ts") || 0);
        const now = Date.now();
        // Allow automated recovery if at least 5 seconds have elapsed since last attempt
        if (now - lastReloadTs > 5000) {
          sessionStorage.setItem("mergex_chunk_reload_ts", String(now));
          const currentUrl = new URL(window.location.href);
          currentUrl.searchParams.set("_reload", String(now));
          window.location.replace(currentUrl.toString());
          // Return a hanging promise while browser reloads the page
          return new Promise(() => {});
        }
      }
      throw err;
    }
  });
}

