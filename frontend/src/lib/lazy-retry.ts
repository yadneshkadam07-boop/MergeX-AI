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
        const key = `mergex_lazy_retry_${window.location.pathname}`;
        const hasRetried = sessionStorage.getItem(key);
        if (!hasRetried) {
          sessionStorage.setItem(key, "1");
          window.location.reload();
          // Return a hanging promise while browser reloads the page
          return new Promise(() => {});
        }
      }
      throw err;
    }
  });
}
