import { createRoute, useSearch, type AnyRoute } from "@tanstack/react-router";

import { redirectIfLoggedIn, requireUser } from "@/app/guards";
import type { RouterContext } from "@/app/router-context";

import { ChangePasswordPage } from "./pages/ChangePasswordPage";
import { LoginPage } from "./pages/LoginPage";

interface LoginSearch {
  redirect?: string;
}

function LoginRoute() {
  const search: Record<string, unknown> = useSearch({ strict: false });
  return <LoginPage redirectTo={typeof search.redirect === "string" ? search.redirect : undefined} />;
}

/**
 * Public and semi-public auth screens, mounted on the root route (outside
 * the app shell): /login and /change-password.
 */
export function routes<TParent extends AnyRoute>(parent: TParent) {
  const login = createRoute({
    getParentRoute: () => parent,
    path: "/login",
    validateSearch: (search: Record<string, unknown>): LoginSearch =>
      typeof search.redirect === "string" ? { redirect: search.redirect } : {},
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

  return [login, changePassword] as const;
}
