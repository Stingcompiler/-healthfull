import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "@tanstack/react-router";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import { Form, PasswordField, TextField } from "@/components/form";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { toApiError, type ApiError } from "@/lib/api/errors";
import { useTranslateError } from "@/lib/api/translate-error";
import { authKeys, login } from "@/lib/auth/api";
import { setSessionState, type SessionState } from "@/lib/auth/session";
import { signInPath } from "@/lib/site";
import { vmsg } from "@/lib/validation";

const schema = z.object({
  username: z.string().trim().min(1, vmsg("validation.required")),
  password: z.string().min(1, vmsg("validation.required")),
});
type Values = z.infer<typeof schema>;

/** Lets React render the "switching" state (the page unmounted) before anything else runs. */
const nextFrame = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

/**
 * The session ended while the page was open (inspection F06). The page stays mounted behind
 * this dialog, hidden, so a half-written note or form is still in memory:
 *
 * - the same user signs in again: the dialog closes, every query is fetched again and the
 *   draft is exactly where it was (save again);
 * - someone else signs in (a shared workstation): the page is unmounted first, so the
 *   previous user's draft is dropped without being shown, the previous user's cached data is
 *   removed, and the app opens at the start for the new user;
 * - "Sign out": the same, back to the sign-in page.
 */
export function ReauthDialog({ session }: { session: Extract<SessionState, { kind: "expired" }> }) {
  const { t } = useTranslation(["auth", "common"]);
  const queryClient = useQueryClient();
  const router = useRouter();
  const translateError = useTranslateError();
  const [error, setError] = useState<ApiError | null>(null);
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { username: session.username, password: "" },
  });

  /** Unmounts the page, forgets the previous user's data, then starts over at `to`. */
  async function startOver(next: Awaited<ReturnType<typeof login>> | null) {
    setSessionState(queryClient, { kind: "switching" });
    await nextFrame();
    queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== "auth" });
    queryClient.setQueryData(authKeys.me, next);
    const to = next === null ? signInPath() : next.must_change_password ? "/change-password" : "/";
    await router.navigate({ to, replace: true, ignoreBlocker: true });
    setSessionState(queryClient, null);
  }

  const onSubmit = form.handleSubmit(async (values) => {
    setError(null);
    try {
      const me = await login(values);
      if (me.id === session.userId && !me.must_change_password) {
        queryClient.setQueryData(authKeys.me, me);
        setSessionState(queryClient, null);
        // Everything that failed while signed out is read again; the page keeps its state.
        void queryClient.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "auth" });
        return;
      }
      await startOver(me);
    } catch (e) {
      setError(toApiError(e));
      form.setValue("password", "");
      form.setFocus("password");
    }
  });

  return (
    <Dialog open onOpenChange={() => undefined}>
      <DialogContent
        showCloseButton={false}
        onEscapeKeyDown={(e) => {
          e.preventDefault();
        }}
        onInteractOutside={(e) => {
          e.preventDefault();
        }}
        data-testid="reauth-dialog"
      >
        <DialogHeader>
          <DialogTitle>{t("reauth.title")}</DialogTitle>
          <DialogDescription>{t("reauth.description")}</DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={(e) => void onSubmit(e)} noValidate className="grid gap-4" aria-label={t("reauth.title")}>
            {error ? (
              <AlertCard variant="danger" title={t("login.failedTitle")} live>
                {translateError(error)}
              </AlertCard>
            ) : null}
            <TextField
              control={form.control}
              name="username"
              label={t("login.username")}
              description={t("reauth.otherUser")}
              autoComplete="username"
              dir="ltr"
              required
            />
            <PasswordField
              control={form.control}
              name="password"
              label={t("login.password")}
              autoComplete="current-password"
              autoFocus
              required
            />
            <div className="flex flex-wrap items-center justify-end gap-2">
              <Button type="button" variant="ghost" onClick={() => void startOver(null)} data-testid="reauth-sign-out">
                {t("reauth.signOut")}
              </Button>
              <Button type="submit" loading={form.formState.isSubmitting} data-testid="reauth-submit">
                {form.formState.isSubmitting ? t("login.submitting") : t("reauth.submit")}
              </Button>
            </div>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
