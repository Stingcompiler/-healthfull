import { Link, useCanGoBack, useRouter } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { Brand } from "@/components/BrandMark";
import { ArrowBack } from "@/components/icons";
import { Button } from "@/components/ui/button";

export function NotFoundPage() {
  const { t } = useTranslation();
  const router = useRouter();
  const canGoBack = useCanGoBack();
  return (
    <div className="flex min-h-dvh flex-col bg-bg">
      <header className="px-4 py-3 md:px-6">
        <Link
          to="/"
          className="inline-flex rounded-control focus-visible:ring-3 focus-visible:ring-ring/35 focus-visible:outline-none"
        >
          <Brand />
        </Link>
      </header>
      <main id="main" className="flex flex-1 items-center justify-center px-4 pb-16">
        <div className="flex max-w-md flex-col items-center text-center">
          <p
            className="bg-linear-to-b from-primary to-primary-strong bg-clip-text tabular text-7xl font-extrabold tracking-tight text-transparent md:text-8xl"
            aria-hidden="true"
          >
            {t("notFound.code")}
          </p>
          <h1 className="mt-4 text-2xl font-bold text-fg">{t("notFound.title")}</h1>
          <p className="mt-2 text-sm text-pretty text-muted">{t("notFound.description")}</p>
          <div className="mt-6 flex flex-wrap justify-center gap-2">
            <Button asChild>
              <Link to="/">{t("actions.goHome")}</Link>
            </Button>
            {canGoBack ? (
              <Button
                variant="outline"
                onClick={() => {
                  router.history.back();
                }}
              >
                <ArrowBack />
                {t("actions.back")}
              </Button>
            ) : null}
          </div>
        </div>
      </main>
    </div>
  );
}
