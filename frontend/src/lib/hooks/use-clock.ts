import { useEffect, useState } from "react";

/** The wall clock, re-read every `intervalMs` (also lets a screen notice a feed that stopped). */
export function useClock(intervalMs = 5_000): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => {
      setNow(new Date());
    }, intervalMs);
    return () => {
      window.clearInterval(id);
    };
  }, [intervalMs]);
  return now;
}
