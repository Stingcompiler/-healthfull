import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import i18n from "@/i18n";
import type { MeOut } from "@/lib/api/contract";
import { authKeys } from "@/lib/auth/api";
import { ConnectionContext } from "@/lib/hooks/connection-context";
import { createQueryClient } from "@/lib/query";

import { PosStatusBar } from "./PosStatusBar";

const CASHIER: MeOut = {
  id: 7,
  username: "cashier",
  full_name_ar: "أمينة الصندوق",
  full_name_en: "Sara Cashier",
  roles: ["cashier"],
  permissions: [],
  language: "en",
  theme: "light",
  must_change_password: false,
};

function renderBar(connection: "connected" | "unreachable" | "restored", shift?: string) {
  const client = createQueryClient();
  client.setQueryData(authKeys.me, CASHIER);
  return render(
    <QueryClientProvider client={client}>
      <ConnectionContext value={connection}>
        <PosStatusBar shift={shift} />
      </ConnectionContext>
    </QueryClientProvider>,
  );
}

describe("PosStatusBar", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });
  afterEach(async () => {
    await i18n.changeLanguage("ar");
  });

  it("shows the operator, the shift, the time and the connection", () => {
    renderBar("connected", "SH-0001");
    const bar = screen.getByTestId("pos-status-bar");
    expect(bar).toHaveAccessibleName("Status bar");
    expect(bar).toHaveTextContent("Sara Cashier");
    expect(bar).toHaveTextContent("SH-0001");
    expect(bar.querySelector("time")).not.toBeNull();
    expect(screen.getByTestId("pos-connection")).toHaveTextContent("Connected");
  });

  it("omits the shift when the desk has none, and says so in words when the server is unreachable", () => {
    renderBar("unreachable");
    expect(screen.getByTestId("pos-status-bar")).not.toHaveTextContent("Shift");
    expect(screen.getByTestId("pos-connection")).toHaveAttribute("data-state", "unreachable");
    expect(screen.getByTestId("pos-connection")).toHaveTextContent("Server unreachable");
  });

  it("is hidden below md (a phone has no desk)", () => {
    renderBar("connected");
    expect(screen.getByTestId("pos-status-bar")).toHaveClass("hidden", "md:flex");
  });
});
