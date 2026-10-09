/**
 * A short undo window before an irreversible action is sent (FEATURES 10.2: one tap "done").
 *
 * `schedule(id, payload)` starts the window; `undo(id)` cancels it; when the window ends (or
 * `commitNow(id)`), `commit(id, payload)` runs once. Leaving the screen sends what is still
 * waiting: the nurse tapped "done", so the tap counts. Timing only; the server decides
 * whether the line may be performed.
 */
import { useCallback, useEffect, useRef, useState } from "react";

export interface PendingCommit<T> {
  payload: T;
  /** Epoch ms when the commit is sent. */
  deadline: number;
}

export interface UndoCommit<T> {
  pending: ReadonlyMap<number, PendingCommit<T>>;
  schedule: (id: number, payload: T) => void;
  undo: (id: number) => void;
  commitNow: (id: number) => void;
}

export function useUndoCommit<T>({
  delayMs,
  commit,
}: {
  delayMs: number;
  commit: (id: number, payload: T) => void;
}): UndoCommit<T> {
  const [pending, setPending] = useState<ReadonlyMap<number, PendingCommit<T>>>(() => new Map());
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());
  const waiting = useRef(new Map<number, PendingCommit<T>>());
  const commitRef = useRef(commit);
  useEffect(() => {
    commitRef.current = commit;
  });

  const drop = useCallback((id: number) => {
    const timer = timers.current.get(id);
    if (timer !== undefined) clearTimeout(timer);
    timers.current.delete(id);
    waiting.current.delete(id);
    setPending(new Map(waiting.current));
  }, []);

  const fire = useCallback(
    (id: number) => {
      const item = waiting.current.get(id);
      if (!item) return;
      drop(id);
      commitRef.current(id, item.payload);
    },
    [drop],
  );

  const schedule = useCallback(
    (id: number, payload: T) => {
      if (waiting.current.has(id)) return;
      waiting.current.set(id, { payload, deadline: Date.now() + delayMs });
      timers.current.set(
        id,
        setTimeout(() => {
          fire(id);
        }, delayMs),
      );
      setPending(new Map(waiting.current));
    },
    [delayMs, fire],
  );

  // Leaving the screen sends what is still waiting (the taps were meant).
  useEffect(() => {
    const timerMap = timers.current;
    const waitingMap = waiting.current;
    return () => {
      for (const timer of timerMap.values()) clearTimeout(timer);
      for (const [id, item] of waitingMap) commitRef.current(id, item.payload);
      timerMap.clear();
      waitingMap.clear();
    };
  }, []);

  return { pending, schedule, undo: drop, commitNow: fire };
}

/** Whole seconds left until `deadline`, ticking while it is in the future. */
export function useSecondsLeft(deadline: number | undefined): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (deadline === undefined) return;
    const tick = setInterval(() => {
      setNow(Date.now());
    }, 250);
    return () => {
      clearInterval(tick);
    };
  }, [deadline]);
  if (deadline === undefined) return 0;
  return Math.max(0, Math.ceil((deadline - now) / 1000));
}
