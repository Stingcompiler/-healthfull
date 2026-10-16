import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { ChevronNext } from "@/components/icons";
import { PageHeader } from "@/components/PageHeader";
import { useCurrentUser } from "@/lib/auth/hooks";
import { hasPermission } from "@/lib/auth/permissions";

import { ADMIN_SECTIONS } from "../sections";

export function AdminIndexPage() {
  const { t } = useTranslation("admin");
  const me = useCurrentUser();
  const sections = ADMIN_SECTIONS.filter((s) => hasPermission(me, s.permission));

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={t("title")} description={t("description")} />
      <ul className="card-surface divide-y divide-border overflow-hidden">
        {sections.map((s) => {
          return (
            <li key={s.id}>
              <Link
                to={s.to}
                className="group flex min-h-11 items-start gap-4 px-4 py-3 focus-ring transition-colors hover:bg-accent md:px-5"
              >
                <span className="min-w-0 flex-1">
                  <span className="block font-semibold text-fg">{t(`sections.${s.id}.title`)}</span>
                  <span className="mt-1 block text-sm text-muted">{t(`sections.${s.id}.description`)}</span>
                </span>
                <ChevronNext className="mt-1 size-4 shrink-0 text-muted transition-transform group-hover:translate-x-0.5 rtl:group-hover:-translate-x-0.5" />
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
