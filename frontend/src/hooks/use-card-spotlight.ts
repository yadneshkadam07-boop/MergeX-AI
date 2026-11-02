import * as React from "react";

/**
 * useCardSpotlight tracks pointer coordinates relative to a card element
 * and updates CSS variables --mx and --my via requestAnimationFrame.
 *
 * Designed for zero React re-renders during mouse movement.
 */
export function useCardSpotlight<T extends HTMLElement = HTMLDivElement>() {
  const rafId = React.useRef<number | null>(null);

  const onPointerMove = React.useCallback((e: React.PointerEvent<T>) => {
    // Skip pointer tracking on touch interactions where coordinates aren't fine
    if (e.pointerType === "touch") return;

    const el = e.currentTarget;
    const clientX = e.clientX;
    const clientY = e.clientY;

    if (rafId.current !== null) {
      cancelAnimationFrame(rafId.current);
    }

    rafId.current = requestAnimationFrame(() => {
      const rect = el.getBoundingClientRect();
      const x = clientX - rect.left;
      const y = clientY - rect.top;
      el.style.setProperty("--mx", `${x}px`);
      el.style.setProperty("--my", `${y}px`);
    });
  }, []);

  const onPointerLeave = React.useCallback((e: React.PointerEvent<T>) => {
    if (rafId.current !== null) {
      cancelAnimationFrame(rafId.current);
      rafId.current = null;
    }
    const el = e.currentTarget;
    el.style.setProperty("--mx", "50%");
    el.style.setProperty("--my", "0%");
  }, []);

  React.useEffect(() => {
    return () => {
      if (rafId.current !== null) {
        cancelAnimationFrame(rafId.current);
      }
    };
  }, []);

  return { onPointerMove, onPointerLeave };
}
