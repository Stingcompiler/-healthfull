import { createMemoryHistory, createRouter, RouterProvider } from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Providers } from "@/app/providers";
import { routeTree } from "@/app/routes";
import i18n from "@/i18n";
import type { MeOut } from "@/lib/api/contract";
import { authKeys } from "@/lib/auth/api";
import { createQueryClient } from "@/lib/query";
import { setViewportWidth } from "@/test/match-media";

const ADMIN: MeOut = {
  id: 1,
  username: "admin",
  full_name_ar: "مدير النظام",
  full_name_en: "System Admin",
  roles: ["admin"],
  permissions: [],
  language: "en",
  theme: "light",
  must_change_password: false,
};
const PHARMACIST: MeOut = {
  ...ADMIN,
  id: 5,
  username: "pharmacist",
  roles: ["pharmacist"],
  permissions: ["pharmacy.dispense"],
};

async function renderApp(path: string, me: MeOut) {
  await i18n.changeLanguage("en");
  const queryClient = createQueryClient();
  queryClient.setQueryData(authKeys.me, me);
  const router = createRouter({
    routeTree,
    context: { queryClient },
    history: createMemoryHistory({ initialEntries: [path] }),
  });
  render(
    <Providers queryClient={queryClient}>
      <RouterProvider router={router} />
    </Providers>,
  );
  await screen.findByTestId("user-menu");
  return { router };
}

const bottomNav = () => screen.getByRole("navigation", { name: "Quick navigation" });

describe("AppShell", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("offline in unit tests"))),
    );
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
    setViewportWidth(1280);
  });

  it("sizes the phone tab bar to the modules a role has, without an empty 'More'", async () => {
    setViewportWidth(375);
    await renderApp("/", PHARMACIST);
    const items = within(bottomNav()).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(within(bottomNav()).queryByTestId("nav-more")).not.toBeInTheDocument();
    expect(within(bottomNav()).getByRole("list")).toHaveStyle({
      gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    });
  });

  it("shows four modules and 'More' when there are more than five", async () => {
    setViewportWidth(375);
    await renderApp("/", ADMIN);
    const items = within(bottomNav()).getAllByRole("listitem");
    expect(items).toHaveLength(5);
    expect(within(bottomNav()).getByTestId("nav-more")).toBeInTheDocument();
  });

  it("marks the active tab with more than color (pill and weight)", async () => {
    setViewportWidth(375);
    await renderApp("/", PHARMACIST);
    const active = within(bottomNav()).getByTestId("nav-dashboard");
    expect(active).toHaveAttribute("data-status", "active");
    expect(active.className).toContain("data-[status=active]:font-bold");
    expect(active.querySelector("span")?.className).toContain("group-data-[status=active]:bg-primary-soft");
  });

  it("lets tablet users expand the icon rail to labels, remembered on the device", async () => {
    setViewportWidth(900);
    const user = userEvent.setup();
    await renderApp("/", ADMIN);
    const sidebar = document.querySelector("[data-slot=app-sidebar]");
    expect(sidebar).not.toHaveAttribute("data-labelled");
    const toggle = screen.getByTestId("rail-toggle");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveAccessibleName("Show menu labels");
    await user.click(toggle);
    await waitFor(() => {
      expect(sidebar).toHaveAttribute("data-labelled", "true");
    });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(localStorage.getItem("hs.rail")).toBe("expanded");
    const patients = within(sidebar as HTMLElement).getByTestId("nav-patients");
    expect(within(patients).getByText("Patients")).not.toHaveClass("sr-only");
  });

  it("has no rail toggle on desktop, where the sidebar is always labelled", async () => {
    setViewportWidth(1280);
    await renderApp("/", ADMIN);
    expect(screen.queryByTestId("rail-toggle")).not.toBeInTheDocument();
    expect(document.querySelector("[data-slot=app-sidebar]")).toHaveAttribute("data-labelled", "true");
  });

  it("names the user menu with the visible user name and titles the page", async () => {
    await renderApp("/", ADMIN);
    expect(screen.getByTestId("user-menu")).toHaveAccessibleName("User menu: System Admin");
    await waitFor(() => {
      expect(document.title).toMatch(/ - /);
    });
  });
});
