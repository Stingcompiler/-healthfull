import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";
import i18n from "@/i18n";
import type { MeOut } from "@/lib/api/contract";
import { renderWithProviders } from "@/test/render";

const me: MeOut = {
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

describe("preferences", () => {
  afterEach(async () => {
    vi.unstubAllGlobals();
    localStorage.clear();
    await i18n.changeLanguage("ar");
  });

  it("switches language instantly and updates <html lang dir> (logged out: localStorage only)", async () => {
    const fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    await renderWithProviders(<LanguageSwitcher />, { language: "ar" });
    expect(document.documentElement.lang).toBe("ar");
    expect(document.documentElement.dir).toBe("rtl");

    await user.click(screen.getByRole("button", { name: "التبديل إلى English" }));
    expect(document.documentElement.lang).toBe("en");
    expect(document.documentElement.dir).toBe("ltr");
    expect(localStorage.getItem("hs.lang")).toBe("en");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("persists to the server profile when logged in", async () => {
    const fetchMock = vi.fn<typeof fetch>((input) => {
      const url = typeof input === "string" ? input : input instanceof Request ? input.url : String(input);
      if (url.endsWith("/api/auth/csrf")) {
        document.cookie = "csrftoken=t1; path=/";
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      return Promise.resolve(
        new Response(JSON.stringify({ ...me, theme: "dark" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const { queryClient } = await renderWithProviders(<ThemeSwitcher variant="segmented" />, { language: "en" });
    queryClient.setQueryData(["auth", "me"], me);

    await user.click(screen.getByRole("radio", { name: "Dark" }));
    await waitFor(() => {
      expect(document.documentElement.dataset.theme).toBe("dark");
    });
    const findPatch = () =>
      fetchMock.mock.calls
        .map(([input]) => input)
        .filter((r): r is Request => r instanceof Request)
        .find((r) => r.method === "PATCH" && r.url.endsWith("/api/auth/me/preferences"));
    await waitFor(() => {
      expect(findPatch()).toBeDefined();
    });
    const patch = findPatch();
    expect(await patch?.clone().json()).toEqual({ theme: "dark" });
    expect(patch?.headers.get("X-CSRFToken")).toBe("t1");
    expect(localStorage.getItem("hs.theme")).toBe("dark");
    expect(screen.getByRole("radio", { name: "Dark" })).toHaveAttribute("aria-checked", "true");
  });
});
