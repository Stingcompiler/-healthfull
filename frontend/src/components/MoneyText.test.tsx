import { render, screen } from "@testing-library/react";
import { afterAll, describe, expect, it } from "vitest";

import i18n from "@/i18n";

import { MoneyText } from "./MoneyText";

const plain = (s: string | null) =>
  (s ?? "")
    .replace(/[\u200e\u200f\u061c\u00a0]/g, " ")
    .replace(/\s+/g, " ")
    .trim();

describe("MoneyText", () => {
  afterAll(async () => {
    await i18n.changeLanguage("ar");
  });

  it("formats SDG for English", async () => {
    await i18n.changeLanguage("en");
    render(<MoneyText value="10000.00" />);
    expect(plain(screen.getByText(/10,000\.00/).textContent)).toBe("SDG 10,000.00");
  });

  it("formats SDG for Arabic with Latin digits and the Arabic symbol", async () => {
    await i18n.changeLanguage("ar");
    render(<MoneyText value="10000.00" />);
    const text = plain(screen.getByText(/10,000\.00/).textContent);
    expect(text).toContain("ج.س.");
    expect(text).not.toMatch(/[٠-٩]/);
  });

  it("re-renders when the language changes", async () => {
    await i18n.changeLanguage("en");
    const { container, rerender } = render(<MoneyText value="5.5" />);
    expect(plain(container.textContent)).toBe("SDG 5.50");
    await i18n.changeLanguage("ar");
    rerender(<MoneyText value="5.5" />);
    expect(plain(container.textContent)).toContain("ج.س.");
  });

  it("isolates bidi, uses tabular figures and tones negatives on request", async () => {
    await i18n.changeLanguage("en");
    const { container } = render(<MoneyText value="-250.00" toneNegative />);
    const el = container.querySelector("bdi");
    expect(el).not.toBeNull();
    expect(el).toHaveAttribute("data-negative", "true");
    expect(el).toHaveClass("tabular", "text-danger-fg");
    expect(plain(el?.textContent ?? null)).toBe("-SDG 250.00");
  });

  it("does not tone negatives unless asked", async () => {
    await i18n.changeLanguage("en");
    const { container } = render(<MoneyText value="-1.00" />);
    expect(container.querySelector("bdi")).not.toHaveClass("text-danger-fg");
  });
});
