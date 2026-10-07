import { describe, expect, it } from "vitest";

import { comboLabels, matchesCombo, parseCombo } from "./use-shortcut";

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
