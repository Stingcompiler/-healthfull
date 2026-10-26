/**
 * Inspection F06: a session that ends while a form is dirty must not lose the draft. The page
 * stays mounted (hidden) behind a sign-in dialog; the same user resumes with the draft, a
 * different user never sees it.
 */
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  RouterProvider,
} from "@tanstack/react-router";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Providers } from "@/app/providers";
import i18n from "@/i18n";
import type { MeOut } from "@/lib/api/contract";
import { ApiError } from "@/lib/api/errors";
import { authKeys } from "@/lib/auth/api";
import { getSessionState } from "@/lib/auth/session";
import { createQueryClient } from "@/lib/query";

import { AuthGuard } from "./AppLayout";

const DOCTOR: MeOut = {
  id: 7,
  username: "doctor1",
  full_name_ar: "د. أحمد",
  full_name_en: "Dr Ahmed",
  roles: ["doctor"],
  permissions: [],
  language: "en",
  theme: "light",
  must_change_password: false,
};
const NURSE: MeOut = { ...DOCTOR, id: 9, username: "nurse1", roles: ["nurse"] };

/** A page holding an unsaved draft in React state, like the clinic's NoteEditor. */
function DraftPage() {
  const [text, setText] = useState("");
  return (
    <label>
      Note
      <textarea aria-label="note" value={text} onChange={(e) => setText(e.target.value)} />
    </label>
  );
}

let signedInAs: MeOut = DOCTOR;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

async function renderPage() {
  await i18n.changeLanguage("en");
  const queryClient = createQueryClient();
  queryClient.setQueryData(authKeys.me, DOCTOR);
  queryClient.setQueryData(["visit", 1], { note: "server copy" });
  const root = createRootRoute({ component: Outlet });
  const page = createRoute({
    getParentRoute: () => root,
    path: "/clinic",
    component: () => (
      <AuthGuard>
        <DraftPage />
      </AuthGuard>
    ),
  });
  const home = createRoute({ getParentRoute: () => root, path: "/", component: () => <p>home page</p> });
  const loginRoute = createRoute({ getParentRoute: () => root, path: "/login", component: () => <p>login page</p> });
  const router = createRouter({
    routeTree: root.addChildren([page, home, loginRoute]),
    context: { queryClient },
    history: createMemoryHistory({ initialEntries: ["/clinic"] }),
  });
  render(
    <Providers queryClient={queryClient}>
      <RouterProvider router={router} />
    </Providers>,
  );
  const note = await screen.findByLabelText<HTMLTextAreaElement>("note");
  fireEvent.change(note, { target: { value: "Fever for two days, half written" } });
  return { router, queryClient };
}

/** What the cashier's save or any query sees when the server dropped the session. */
async function sessionEnds(queryClient: ReturnType<typeof createQueryClient>) {
  await act(async () => {
    await queryClient
      .query({
        queryKey: ["probe"],
        queryFn: () => Promise.reject(new ApiError(401, { code: "NOT_AUTHENTICATED", message: "", details: {} })),
        retry: false,
      })
      .catch(() => undefined);
  });
}

function signIn(username: string) {
  const user = screen.getByLabelText(/username/i);
  fireEvent.change(user, { target: { value: username } });
  fireEvent.change(screen.getByLabelText(/^password/i), { target: { value: "Correct-Horse-91" } });
  fireEvent.click(screen.getByTestId("reauth-submit"));
}

describe("session expiry with a dirty form", () => {
  beforeEach(() => {
    document.cookie = "csrftoken=test-token";
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = input instanceof Request ? input.url : String(input);
        if (url.includes("/api/auth/login")) return Promise.resolve(json(200, signedInAs));
        if (url.includes("/api/auth/me")) return Promise.resolve(json(200, signedInAs));
        return Promise.reject(new TypeError("offline in unit tests"));
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    signedInAs = DOCTOR;
  });

  it("keeps the page mounted but hidden, and the same user resumes with the draft", async () => {
    const { router, queryClient } = await renderPage();
    await sessionEnds(queryClient);

    const dialog = await screen.findByTestId("reauth-dialog");
    expect(dialog).toHaveTextContent("Your session has ended");
    // Still on the page, still signed in as the doctor in the cache, the draft hidden.
    expect(router.state.location.pathname).toBe("/clinic");
    expect(queryClient.getQueryData(authKeys.me)).toEqual(DOCTOR);
    expect(screen.getByTestId("auth-guarded")).toHaveClass("hidden");
    expect(screen.getByLabelText<HTMLTextAreaElement>("note", { selector: "textarea" }).value).toBe(
      "Fever for two days, half written",
    );
    expect(screen.getByLabelText(/username/i)).toHaveValue("doctor1");

    signedInAs = DOCTOR;
    signIn("doctor1");
    await waitFor(() => {
      expect(screen.queryByTestId("reauth-dialog")).toBeNull();
    });
    expect(getSessionState(queryClient)).toBeNull();
    expect(router.state.location.pathname).toBe("/clinic");
    expect(screen.getByTestId("auth-guarded")).toHaveClass("contents");
    expect(screen.getByLabelText<HTMLTextAreaElement>("note").value).toBe("Fever for two days, half written");
  });

  it("drops the draft without showing it when someone else signs in", async () => {
    const { router, queryClient } = await renderPage();
    await sessionEnds(queryClient);
    await screen.findByTestId("reauth-dialog");

    signedInAs = NURSE;
    signIn("nurse1");
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/");
    });
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(screen.queryByTestId("reauth-dialog")).toBeNull();
    expect(screen.queryByLabelText("note")).toBeNull();
    expect(document.body).not.toHaveTextContent("half written");
    expect(queryClient.getQueryData(authKeys.me)).toEqual(NURSE);
    // The doctor's cached data is gone.
    expect(queryClient.getQueryData(["visit", 1])).toBeUndefined();
    expect(getSessionState(queryClient)).toBeNull();
  });

  it("signs out from the dialog without keeping anything", async () => {
    const { router, queryClient } = await renderPage();
    await sessionEnds(queryClient);
    fireEvent.click(await screen.findByTestId("reauth-sign-out"));
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/login");
    });
    expect(queryClient.getQueryData(authKeys.me)).toBeNull();
    expect(queryClient.getQueryData(["visit", 1])).toBeUndefined();
    expect(document.body).not.toHaveTextContent("half written");
  });

  it("a wrong password keeps the dialog and the draft", async () => {
    const { queryClient } = await renderPage();
    await sessionEnds(queryClient);
    await screen.findByTestId("reauth-dialog");
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(json(401, { code: "INVALID_CREDENTIALS", message: "Invalid credentials", details: {} })),
      ),
    );
    signIn("doctor1");
    expect(await screen.findByText(/sign-in failed/i)).toBeInTheDocument();
    expect(screen.getByTestId("reauth-dialog")).toBeInTheDocument();
    expect(getSessionState(queryClient)?.kind).toBe("expired");
    expect(screen.getByLabelText<HTMLTextAreaElement>("note", { selector: "textarea" }).value).toBe(
      "Fever for two days, half written",
    );
  });
});
