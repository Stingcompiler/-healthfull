import { createMemoryHistory, createRouter, RouterProvider } from "@tanstack/react-router";
import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Providers } from "@/app/providers";
import { routeTree } from "@/app/routes";
import i18n from "@/i18n";
import type { MeOut } from "@/lib/api/contract";
import { authKeys } from "@/lib/auth/api";
import { createQueryClient } from "@/lib/query";

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

/** The whole app (real route tree and guards) at `path`, signed in as `me`. */
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
  await waitFor(() => {
    expect(router.state.status).toBe("idle");
  });
  await screen.findByTestId("user-menu");
  return { router, queryClient };
}

/** Lets pending navigations and effects run, so a redirect loop would show up. */
async function settle() {
  for (let i = 0; i < 5; i += 1) {
    await act(() => new Promise((resolve) => setTimeout(resolve, 20)));
  }
}

describe("AuthGuard", () => {
  const consoleError = vi.spyOn(console, "error");

  beforeEach(() => {
    // No real server: /me reports "logged out", anything else fails like a network error.
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = input instanceof Request ? input.url : String(input);
        if (url.includes("/api/auth/me")) {
          return Promise.resolve(
            new Response(JSON.stringify({ code: "NOT_AUTHENTICATED", message: "", details: {} }), {
              status: 401,
              headers: { "Content-Type": "application/json" },
            }),
          );
        }
        return Promise.reject(new TypeError("offline in unit tests"));
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function expectNoRenderLoop() {
    const messages = consoleError.mock.calls.map((args) => args.map(String).join(" "));
    expect(messages.filter((m) => m.includes("Maximum update depth"))).toEqual([]);
  }

  it("sends a user whose session ended to /login once, with a way back", async () => {
    const { router, queryClient } = await renderApp("/reports", ADMIN);
    expect(router.state.location.pathname).toBe("/reports");

    act(() => {
      queryClient.setQueryData(authKeys.me, null);
    });
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/login");
    });
    await settle();

    expect(router.state.location.pathname).toBe("/login");
    expect(router.state.location.search).toEqual({ redirect: "/reports" });
    expectNoRenderLoop();
  });

  it("does not fight an explicit logout navigation (user menu)", async () => {
    const { router, queryClient } = await renderApp("/patients", ADMIN);

    act(() => {
      // useLogout's onSettled, then the user menu's own navigation, back to back.
      queryClient.setQueryData(authKeys.me, null);
      void router.navigate({ to: "/login", replace: true });
    });
    await settle();

    expect(router.state.location.pathname).toBe("/login");
    const redirect = router.state.location.search.redirect;
    expect(redirect === undefined || redirect === "/patients").toBe(true);
    expect(router.state.location.href.match(/login/g)).toHaveLength(1);
    expectNoRenderLoop();
  });

  it("sends a user who must change the password to /change-password", async () => {
    const { router, queryClient } = await renderApp("/claims", ADMIN);

    act(() => {
      queryClient.setQueryData(authKeys.me, { ...ADMIN, must_change_password: true });
    });
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/change-password");
    });
    await settle();

    expect(router.state.location.pathname).toBe("/change-password");
    expectNoRenderLoop();
  });
});
