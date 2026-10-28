import { createMemoryHistory, createRouter, RouterProvider } from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Providers } from "@/app/providers";
import { routeTree } from "@/app/routes";
import i18n from "@/i18n";
import { ar, en } from "@/i18n/resources";
import type { MeOut } from "@/lib/api/contract";
import { authKeys } from "@/lib/auth/api";
import { createQueryClient } from "@/lib/query";
import { setSiteConfig } from "@/lib/site";

/** The real route tree and guards at `path`, nobody signed in. */
async function renderAt(path: string, language: "ar" | "en" = "en", me: MeOut | null = null) {
  await i18n.changeLanguage(language);
  const queryClient = createQueryClient();
  if (me) queryClient.setQueryData(authKeys.me, me);
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
  return router;
}

beforeEach(() => {
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
  setSiteConfig(null);
});

describe("/login and /sign-in (ADR 0027)", () => {
  it("is off by default: /login is the staff sign-in form", async () => {
    await renderAt("/login");
    expect(await screen.findByRole("form", { name: en.auth.login.title })).toBeInTheDocument();
    expect(screen.queryByTestId("marketing-page")).not.toBeInTheDocument();
  });

  it("is off by default: /sign-in is an alias of the same form", async () => {
    await renderAt("/sign-in");
    expect(await screen.findByRole("form", { name: en.auth.login.title })).toBeInTheDocument();
  });

  it("is on: /login is the product page and has no sign-in form", async () => {
    setSiteConfig({ marketing: true });
    await renderAt("/login");
    expect(await screen.findByTestId("marketing-page")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: en.marketing.hero.title })).toBeInTheDocument();
    expect(screen.queryByRole("form")).not.toBeInTheDocument();
  });

  it("is on: /sign-in is still the staff sign-in, with the same accessible names", async () => {
    setSiteConfig({ marketing: true });
    await renderAt("/sign-in");
    const form = await screen.findByRole("form", { name: en.auth.login.title });
    expect(within(form).getByLabelText(new RegExp(en.auth.login.username))).toBeInTheDocument();
    expect(within(form).getByLabelText(new RegExp(en.auth.login.password))).toBeInTheDocument();
    expect(screen.queryByTestId("marketing-page")).not.toBeInTheDocument();
  });

  it("is on: every call to action leads to /sign-in, at least five of them", async () => {
    setSiteConfig({ marketing: true });
    await renderAt("/login");
    await screen.findByTestId("marketing-page");
    const ctas = screen.getAllByTestId("mk-cta");
    expect(ctas.length).toBeGreaterThanOrEqual(5);
    for (const cta of ctas) {
      expect(cta).toHaveAttribute("href", "/sign-in");
      expect(cta).toHaveTextContent(en.marketing.cta);
    }
    // One wording only: no other link or button carries a competing action label.
    expect(screen.getAllByRole("link", { name: en.marketing.cta })).toHaveLength(ctas.length);
    // The sticky header, the phone bar, the hero and the closing section are among them.
    const places = ctas.map((c) => c.getAttribute("data-cta"));
    expect(places).toEqual(
      expect.arrayContaining(["header", "hero", "cycle", "safety", "roles", "network", "final", "bar"]),
    );
  });

  it("is on: the page shows no sign-in form, password or account", async () => {
    setSiteConfig({ marketing: true });
    await renderAt("/login");
    await screen.findByTestId("marketing-page");
    expect(document.querySelector("input")).toBeNull();
    expect(screen.getByTestId("marketing-page").textContent).not.toMatch(/password|كلمة المرور/i);
  });

  it("is on: image sizes are reserved and only the hero loads eagerly", async () => {
    setSiteConfig({ marketing: true });
    await renderAt("/login");
    await screen.findByTestId("marketing-page");
    const images = Array.from(document.querySelectorAll("img"));
    expect(images.length).toBeGreaterThan(5);
    for (const img of images) {
      expect(img.getAttribute("width"), img.alt).toBeTruthy();
      expect(img.getAttribute("height"), img.alt).toBeTruthy();
      expect(img.alt, "every screenshot has a text alternative").not.toBe("");
      const hero = img.closest('[data-testid="mk-hero-image"]') !== null;
      expect(img.getAttribute("loading")).toBe(hero ? "eager" : "lazy");
    }
  });

  it("is on: contact links appear only when the deployment configures them", async () => {
    setSiteConfig({ marketing: true });
    await renderAt("/login");
    await screen.findByTestId("marketing-page");
    expect(document.querySelector('a[href^="mailto:"]')).toBeNull();
    expect(document.querySelector('a[href^="https://wa.me/"]')).toBeNull();
    expect(screen.getByText(en.marketing.final.demo)).toBeInTheDocument();
  });

  it("is on: configured contact values become plain links", async () => {
    setSiteConfig({ marketing: true, contactEmail: "sales@example.org", contactWhatsapp: "249912345678" });
    await renderAt("/login");
    await screen.findByTestId("marketing-page");
    expect(document.querySelector('a[href="mailto:sales@example.org"]')).not.toBeNull();
    expect(document.querySelector('a[href="https://wa.me/249912345678"]')).not.toBeNull();
  });

  it("is on: the page renders in Arabic too, with the same call to action count", async () => {
    setSiteConfig({ marketing: true });
    await renderAt("/login", "ar");
    await screen.findByTestId("marketing-page");
    expect(screen.getByRole("heading", { level: 1, name: ar.marketing.hero.title })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: ar.marketing.cta }).length).toBeGreaterThanOrEqual(5);
  });

  it("is on: a signed-out visitor at /login keeps the page, and the FAQ opens by keyboard-native details", async () => {
    setSiteConfig({ marketing: true });
    const router = await renderAt("/login");
    await screen.findByTestId("marketing-page");
    expect(router.state.location.pathname).toBe("/login");
    const items = document.querySelectorAll(".mk-faq details");
    expect(items.length).toBeGreaterThanOrEqual(4);
    expect(items.length).toBeLessThanOrEqual(8);
    for (const item of items) expect(item.querySelector("summary")).not.toBeNull();
  });

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

  describe("the site root", () => {
    it("is on, signed out: / is the product page, at the same address", async () => {
      setSiteConfig({ marketing: true });
      const router = await renderAt("/");
      await screen.findByTestId("marketing-page");
      expect(router.state.location.pathname).toBe("/");
      expect(screen.getAllByRole("link", { name: en.marketing.cta }).length).toBeGreaterThanOrEqual(5);
      for (const cta of screen.getAllByTestId("mk-cta")) expect(cta).toHaveAttribute("href", "/sign-in");
    });

    it("is on, signed in: / is the dashboard and the page never shows", async () => {
      setSiteConfig({ marketing: true });
      const router = await renderAt("/", "en", ADMIN);
      await screen.findByTestId("user-menu");
      expect(router.state.location.pathname).toBe("/");
      expect(screen.queryByTestId("marketing-page")).not.toBeInTheDocument();
    });

    it("is on, signed out: a protected route still goes to /sign-in, not to /", async () => {
      setSiteConfig({ marketing: true });
      const router = await renderAt("/patients");
      await waitFor(() => {
        expect(router.state.location.pathname).toBe("/sign-in");
      });
      expect(router.state.location.search).toEqual({ redirect: "/patients" });
      expect(screen.queryByTestId("marketing-page")).not.toBeInTheDocument();
    });

    it("is off, signed out: / goes to /login as before", async () => {
      const router = await renderAt("/");
      await waitFor(() => {
        expect(router.state.location.pathname).toBe("/login");
      });
      expect(screen.queryByTestId("marketing-page")).not.toBeInTheDocument();
    });

    it("is off, signed in: / is the dashboard", async () => {
      const router = await renderAt("/", "en", ADMIN);
      await screen.findByTestId("user-menu");
      expect(router.state.location.pathname).toBe("/");
    });

    it("is on: /portal stays the center page", async () => {
      setSiteConfig({ marketing: true });
      await renderAt("/portal");
      await waitFor(() => {
        expect(screen.queryByTestId("marketing-page")).not.toBeInTheDocument();
      });
    });
  });
});
