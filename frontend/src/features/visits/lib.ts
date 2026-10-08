import { useState } from "react";

/** Remembers a per-device choice (the reception desk's clinic, the doctor on the day view). */
export function useDeviceChoice(key: string): [number | null, (value: number | null) => void] {
  const storageKey = `hs.visits.${key}`;
  const [value, setValue] = useState<number | null>(() => {
    try {
      const raw = window.localStorage.getItem(storageKey);
      const parsed = raw ? Number(raw) : NaN;
      return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
    } catch {
      return null;
    }
  });
  const update = (next: number | null) => {
    setValue(next);
    try {
      if (next === null) window.localStorage.removeItem(storageKey);
      else window.localStorage.setItem(storageKey, String(next));
    } catch {
      // Storage may be unavailable (private mode); the choice then lasts for this page only.
    }
  };
  return [value, update];
}

/** Value used by department selects for "every clinic". */
export const ALL = "all";
