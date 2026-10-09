import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useSecondsLeft, useUndoCommit } from "./use-undo-commit";

describe("useUndoCommit", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  function setup(delayMs = 5000) {
    const commit = vi.fn();
    const hook = renderHook(() => useUndoCommit<string>({ delayMs, commit }));
    return { hook, commit };
  }

  it("commits once when the window ends", () => {
    const { hook, commit } = setup();
    act(() => {
      hook.result.current.schedule(7, "note");
    });
    expect(hook.result.current.pending.has(7)).toBe(true);
    act(() => {
      vi.advanceTimersByTime(4999);
    });
    expect(commit).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(commit).toHaveBeenCalledExactlyOnceWith(7, "note");
    expect(hook.result.current.pending.size).toBe(0);
  });

  it("undo cancels the commit", () => {
    const { hook, commit } = setup();
    act(() => {
      hook.result.current.schedule(7, "");
    });
    act(() => {
      hook.result.current.undo(7);
    });
    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    expect(commit).not.toHaveBeenCalled();
    expect(hook.result.current.pending.size).toBe(0);
  });

  it("a second tap does not schedule twice; commitNow sends at once", () => {
    const { hook, commit } = setup();
    act(() => {
      hook.result.current.schedule(1, "a");
      hook.result.current.schedule(1, "b");
      hook.result.current.schedule(2, "c");
    });
    act(() => {
      hook.result.current.commitNow(2);
    });
    expect(commit).toHaveBeenCalledExactlyOnceWith(2, "c");
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(commit).toHaveBeenCalledTimes(2);
    expect(commit).toHaveBeenLastCalledWith(1, "a");
  });

  it("leaving the screen sends what is still waiting", () => {
    const { hook, commit } = setup();
    act(() => {
      hook.result.current.schedule(3, "x");
    });
    hook.unmount();
    expect(commit).toHaveBeenCalledExactlyOnceWith(3, "x");
    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    expect(commit).toHaveBeenCalledTimes(1);
  });
});

describe("useSecondsLeft", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("counts down to zero", () => {
    const deadline = Date.now() + 3000;
    const hook = renderHook(() => useSecondsLeft(deadline));
    expect(hook.result.current).toBe(3);
    act(() => {
      vi.advanceTimersByTime(1250);
    });
    expect(hook.result.current).toBe(2);
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(hook.result.current).toBe(0);
  });
});
