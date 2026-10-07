import { useEffect, useState, type RefObject } from "react";

/**
 * Inline size of an element, kept current with a ResizeObserver. `null` until the first
 * measurement, and always where ResizeObserver does not exist (jsdom), so callers can fall
 * back to a viewport breakpoint.
 */
export function useElementWidth(ref: RefObject<HTMLElement | null>): number | null {
  const [width, setWidth] = useState<number | null>(null);
  useEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[entries.length - 1];
      if (entry) setWidth(Math.round(entry.contentRect.width));
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
    };
  }, [ref]);
  return width;
}
