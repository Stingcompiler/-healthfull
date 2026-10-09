import { useEffect, useRef } from "react";

/**
 * Keyboard shortcuts. A combo is "+"-separated, case-insensitive:
 *   "mod+k"      Ctrl+K on Windows/Linux, ⌘K on macOS
 *   "shift+/"    "?" on most layouts
 *   "f2", "escape", "alt+n"
 * Matching uses `event.key`, falling back to `event.code` so shortcuts keep
 * working while an Arabic keyboard layout is active (key would be Arabic).
 */
export interface ShortcutOptions {
  enabled?: boolean;
  /** Fire even when focus is in an input/textarea/select/contenteditable. */
  allowInInputs?: boolean;
  /**
   * Fire while a dialog is open. Page shortcuts stay quiet behind an open dialog (so Ctrl+Enter
   * in a dialog's textarea never submits the page underneath); a dialog's own shortcuts set it.
   */
  allowInDialogs?: boolean;
  preventDefault?: boolean;
}

export function isMac(): boolean {
  if (typeof navigator === "undefined") return false;
  return /mac|iphone|ipad|ipod/i.test(navigator.userAgent);
}

interface ParsedCombo {
  key: string;
  mod: boolean;
  ctrl: boolean;
  meta: boolean;
  alt: boolean;
  shift: boolean;
}

export function parseCombo(combo: string): ParsedCombo {
  const parts = combo
    .toLowerCase()
    .split("+")
    .map((p) => p.trim())
    .filter(Boolean);
  const key = parts.pop() ?? "";
  return {
    key,
    mod: parts.includes("mod"),
    ctrl: parts.includes("ctrl"),
    meta: parts.includes("meta") || parts.includes("cmd"),
    alt: parts.includes("alt"),
    shift: parts.includes("shift"),
  };
}

function keyFromCode(code: string): string {
  if (code.startsWith("Key")) return code.slice(3).toLowerCase();
  if (code.startsWith("Digit")) return code.slice(5);
  if (code === "Slash") return "/";
  return code.toLowerCase();
}

export function matchesCombo(event: KeyboardEvent, combo: string, mac = isMac()): boolean {
  const c = parseCombo(combo);
  const wantCtrl = c.ctrl || (c.mod && !mac);
  const wantMeta = c.meta || (c.mod && mac);
  if (event.ctrlKey !== wantCtrl || event.metaKey !== wantMeta) return false;
  if (event.altKey !== c.alt) return false;
  if (c.shift && !event.shiftKey) return false;
  const key = event.key.toLowerCase();
  return key === c.key || keyFromCode(event.code) === c.key;
}

const KEY_LABELS: Record<string, string> = {
  escape: "Esc",
  enter: "↵",
  arrowup: "↑",
  arrowdown: "↓",
  arrowleft: "←",
  arrowright: "→",
  " ": "Space",
  space: "Space",
};

/** Display labels for a combo: "mod+k" -> ["⌘", "K"] on macOS, ["Ctrl", "K"] elsewhere. */
export function comboLabels(combo: string, mac = isMac()): string[] {
  const c = parseCombo(combo);
  const keys: string[] = [];
  if (c.mod) keys.push(mac ? "⌘" : "Ctrl");
  if (c.ctrl) keys.push(mac ? "⌃" : "Ctrl");
  if (c.meta) keys.push(mac ? "⌘" : "Win");
  if (c.alt) keys.push(mac ? "⌥" : "Alt");
  if (c.shift) keys.push(mac ? "⇧" : "Shift");
  keys.push(KEY_LABELS[c.key] ?? c.key.toUpperCase());
  return keys;
}

const OPEN_DIALOG = '[role="dialog"][data-state="open"], [role="alertdialog"][data-state="open"]';

/** Whether a dialog (modal, alert dialog, popover) is open on the page. */
export function dialogOpen(doc: Document = document): boolean {
  return doc.querySelector(OPEN_DIALOG) !== null;
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
}

export function useShortcut(
  combo: string | readonly string[],
  handler: (event: KeyboardEvent) => void,
  { enabled = true, allowInInputs = false, allowInDialogs = false, preventDefault = true }: ShortcutOptions = {},
): void {
  const handlerRef = useRef(handler);
  useEffect(() => {
    handlerRef.current = handler;
  });

  const combos = typeof combo === "string" ? [combo] : combo;
  const comboKey = combos.join("|");

  useEffect(() => {
    if (!enabled) return undefined;
    const list = comboKey.split("|");
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.isComposing) return;
      if (!list.some((c) => matchesCombo(event, c))) return;
      const hasModifier = event.ctrlKey || event.metaKey || event.altKey;
      if (!allowInInputs && !hasModifier && isEditableTarget(event.target)) return;
      if (!allowInDialogs && dialogOpen()) return;
      if (preventDefault) event.preventDefault();
      handlerRef.current(event);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [comboKey, enabled, allowInInputs, allowInDialogs, preventDefault]);
}
