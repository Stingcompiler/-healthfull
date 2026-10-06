import { render, screen } from "@testing-library/react";
import { afterAll, describe, expect, it } from "vitest";

import i18n from "@/i18n";
import { ar, en } from "@/i18n/resources";

import { STATUS_STYLES, STATUSES, SERVICE_LINE_STATES, VERIFICATION_STATES } from "./status";
import { StatusBadge } from "./StatusBadge";

describe("StatusBadge", () => {
  afterAll(async () => {
    await i18n.changeLanguage("ar");
  });

  it("covers every service-line and verification state", () => {
    expect([...SERVICE_LINE_STATES]).toEqual(["requested", "invoiced", "paid", "performed", "cancelled"]);
    expect([...VERIFICATION_STATES]).toEqual(["pending_verification", "confirmed", "rejected"]);
    for (const s of STATUSES) {
      expect(en.common.status[s]).toBeTruthy();
      expect(ar.common.status[s]).toBeTruthy();
      expect(en.common.statusHint[s]).toBeTruthy();
    }
  });

  it.each(STATUSES)("renders %s with its label, hint and semantic color", async (status) => {
    await i18n.changeLanguage("en");
    const { container } = render(<StatusBadge status={status} />);
    const badge = container.querySelector("[data-slot=status-badge]");
    expect(badge).toHaveAttribute("data-status", status);
    expect(badge).toHaveTextContent(en.common.status[status]);
    expect(badge).toHaveAttribute("title", en.common.statusHint[status]);
    for (const cls of STATUS_STYLES[status].className.split(" ")) expect(badge).toHaveClass(cls);
    // Never color alone: every badge carries an icon.
    expect(badge?.querySelector("svg")).not.toBeNull();
  });

  it("uses the service-line state tokens for line states", () => {
    for (const s of SERVICE_LINE_STATES) {
      expect(STATUS_STYLES[s].className).toContain(`bg-state-${s}-bg`);
    }
    expect(STATUS_STYLES.pending_verification.className).toContain("bg-state-pending-bg");
  });

  it("translates to Arabic", async () => {
    await i18n.changeLanguage("ar");
    render(<StatusBadge status="paid" />);
    expect(screen.getByText(ar.common.status.paid)).toBeInTheDocument();
  });

  it("can hide the hint and render compact", async () => {
    await i18n.changeLanguage("en");
    const { container } = render(<StatusBadge status="cancelled" size="sm" withHint={false} />);
    const badge = container.querySelector("[data-slot=status-badge]");
    expect(badge).not.toHaveAttribute("title");
    expect(badge).toHaveClass("text-[11px]");
  });
});
