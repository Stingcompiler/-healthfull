import { createRoute, useSearch, type AnyRoute } from "@tanstack/react-router";
import { lazy, Suspense } from "react";

import { redirectIfLoggedIn, requireUser } from "@/app/guards";
import type { RouterContext } from "@/app/router-context";
import { isMarketingSite } from "@/lib/site";

import { ChangePasswordPage } from "./pages/ChangePasswordPage";
import { LoginPage } from "./pages/LoginPage";

interface LoginSearch {
  redirect?: string;
}

function LoginRoute() {
  const search: Record<string, unknown> = useSearch({ strict: false });
  return <LoginPage redirectTo={typeof search.redirect === "string" ? search.redirect : undefined} />;
}

// The product page (its code, styles and screenshots) is fetched only where the deployment turns it on.
const MarketingPage = lazy(() =>
  import("@/features/marketing/MarketingPage").then((module) => ({ default: module.MarketingPage })),
);

/** `/login`: the product page when the deployment turns it on, otherwise the staff sign-in. */
function LoginEntry() {
  if (!isMarketingSite()) return <LoginRoute />;
  return (
    <Suspense fallback={null}>
      <MarketingPage />
    </Suspense>
  );
}

const validateLoginSearch = (search: Record<string, unknown>): LoginSearch =>
  typeof search.redirect === "string" ? { redirect: search.redirect } : {};

/**
 * Public and semi-public auth screens, mounted on the root route (outside
 * the app shell): /login, /sign-in and /change-password. `/sign-in` is the canonical staff
 * sign-in; `/login` is its alias unless the marketing page is on (ADR 0027).
 */
export function routes<TParent extends AnyRoute>(parent: TParent) {
  const login = createRoute({
    getParentRoute: () => parent,
    path: "/login",
    validateSearch: validateLoginSearch,
    beforeLoad: async ({ context, location, search }) => {
      await redirectIfLoggedIn({ context: context as RouterContext, location }, search.redirect, {
        marketingPage: true,
      });
    },
    component: LoginEntry,
  });

  const signIn = createRoute({
    getParentRoute: () => parent,
    path: "/sign-in",
    validateSearch: validateLoginSearch,
    beforeLoad: async ({ context, location, search }) => {
      await redirectIfLoggedIn({ context: context as RouterContext, location }, search.redirect);
    },
    component: LoginRoute,
  });

  const changePassword = createRoute({
    getParentRoute: () => parent,
    path: "/change-password",
    beforeLoad: async ({ context, location }) => {
      await requireUser({ context: context as RouterContext, location });
    },
    component: ChangePasswordPage,
  });

  return [login, signIn, changePassword] as const;
}
