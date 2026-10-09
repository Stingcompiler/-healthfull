import { fireEvent, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { comboLabels, dialogOpen, matchesCombo, parseCombo, useShortcut } from "./use-shortcut";

const key = (init: KeyboardEventInit) => new KeyboardEvent("keydown", init);

describe("shortcuts", () => {
  it("parses combos", () => {
    expect(parseCombo("mod+shift+K")).toMatchObject({ key: "k", mod: true, shift: true, alt: false });
  });

  it("maps mod to Ctrl off macOS and ⌘ on macOS", () => {
    expect(matchesCombo(key({ key: "k", ctrlKey: true }), "mod+k", false)).toBe(true);
    expect(matchesCombo(key({ key: "k", metaKey: true }), "mod+k", false)).toBe(false);
    expect(matchesCombo(key({ key: "k", metaKey: true }), "mod+k", true)).toBe(true);
  });

  it("requires exact modifiers", () => {
    expect(matchesCombo(key({ key: "k" }), "mod+k", false)).toBe(false);
    expect(matchesCombo(key({ key: "k", ctrlKey: true, altKey: true }), "mod+k", false)).toBe(false);
  });

  it("works with an Arabic keyboard layout via event.code", () => {
    // On the Arabic layout the K key produces "ن".
    expect(matchesCombo(key({ key: "ن", code: "KeyK", ctrlKey: true }), "mod+k", false)).toBe(true);
    expect(matchesCombo(key({ key: "ش", code: "KeyA", altKey: true }), "alt+a", false)).toBe(true);
  });

  it("labels combos per platform", () => {
    expect(comboLabels("mod+k", true)).toEqual(["⌘", "K"]);
    expect(comboLabels("mod+k", false)).toEqual(["Ctrl", "K"]);
    expect(comboLabels("alt+escape", false)).toEqual(["Alt", "Esc"]);
  });
});

describe("shortcuts behind an open dialog", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  const openDialog = () => {
    const dialog = document.createElement("div");
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("data-state", "open");
    const textarea = document.createElement("textarea");
    dialog.append(textarea);
    document.body.append(dialog);
    return textarea;
  };

  it("stay quiet for the page and fire for the dialog's own shortcuts", () => {
    const page = vi.fn();
    const own = vi.fn();
    renderHook(() => {
      useShortcut("mod+enter", page, { allowInInputs: true });
      useShortcut("mod+enter", own, { allowInInputs: true, allowInDialogs: true });
    });
    fireEvent.keyDown(window, { key: "Enter", ctrlKey: true });
    fireEvent.keyDown(window, { key: "Enter", metaKey: true });
    expect(page).toHaveBeenCalledTimes(1);

    const textarea = openDialog();
    expect(dialogOpen()).toBe(true);
    own.mockClear();
    fireEvent.keyDown(textarea, { key: "Enter", ctrlKey: true });
    fireEvent.keyDown(textarea, { key: "Enter", metaKey: true });
    expect(page).toHaveBeenCalledTimes(1);
    expect(own).toHaveBeenCalledTimes(1);
  });

  it("ignore closed dialogs", () => {
    const dialog = document.createElement("div");
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("data-state", "closed");
    document.body.append(dialog);
    expect(dialogOpen()).toBe(false);
  });
});
