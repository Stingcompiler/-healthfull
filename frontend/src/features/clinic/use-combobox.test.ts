import { act, renderHook } from "@testing-library/react";
import type { KeyboardEvent } from "react";
import { describe, expect, it, vi } from "vitest";

import { useCombobox, type ComboboxOptions } from "./use-combobox";

const press = (key: string) => {
  const event = { key, preventDefault: vi.fn() };
  return event as unknown as KeyboardEvent<HTMLInputElement> & { preventDefault: ReturnType<typeof vi.fn> };
};

function setup(options: Partial<ComboboxOptions<string>>) {
  const onPick = vi.fn();
  const search = vi.fn();
  const props: ComboboxOptions<string> = {
    query: "para",
    term: "para",
    search,
    results: ["paracetamol", "paraffin"],
    settled: true,
    onPick,
    ...options,
  };
  const hook = renderHook((p: ComboboxOptions<string>) => useCombobox(p), { initialProps: props });
  return { hook, onPick, search, props };
}

describe("useCombobox", () => {
  it("Enter adds the highlighted row of the current query", () => {
    const { hook, onPick } = setup({});
    act(() => {
      hook.result.current.inputProps.onKeyDown(press("ArrowDown"));
    });
    expect(hook.result.current.active).toBe(1);
    expect(hook.result.current.inputProps["aria-activedescendant"]).toBe(hook.result.current.optionProps(1).id);
    act(() => {
      hook.result.current.inputProps.onKeyDown(press("Enter"));
    });
    expect(onPick).toHaveBeenCalledWith("paraffin");
  });

  it("never takes a row left from the previous query", () => {
    // The input says "amox" but the list still shows the "para" results (debounce pending).
    const { hook, onPick, search } = setup({ query: "amox", term: "para" });
    expect(hook.result.current.fresh).toBe(false);
    act(() => {
      hook.result.current.inputProps.onKeyDown(press("Enter"));
    });
    expect(onPick).not.toHaveBeenCalled();
    expect(search).toHaveBeenCalledWith("amox");
  });

  it("waits while kept (placeholder) data or a refetch is on screen", () => {
    const { hook, onPick, search } = setup({ settled: false });
    act(() => {
      hook.result.current.inputProps.onKeyDown(press("Enter"));
    });
    expect(onPick).not.toHaveBeenCalled();
    expect(search).not.toHaveBeenCalled();
  });

  it("goes back to the first row when the query or filter changes", () => {
    const { hook, props } = setup({ resetKey: "para|" });
    act(() => {
      hook.result.current.inputProps.onKeyDown(press("ArrowUp"));
    });
    expect(hook.result.current.active).toBe(1);
    hook.rerender({ ...props, resetKey: "para|drug", results: ["paracetamol", "paraffin", "x"] });
    expect(hook.result.current.active).toBe(0);
  });
});
