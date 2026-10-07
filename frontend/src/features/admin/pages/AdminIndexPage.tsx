import { Link } from "@tanstack/react-router";
import { Settings2 } from "lucide-react";
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
      <PageHeader title={t("title")} description={t("description")} icon={<Settings2 />} />
      <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {sections.map((s) => {
          const Icon = s.icon;
          return (
            <li key={s.id}>
              <Link
                to={s.to}
                className="card-surface group flex h-full items-start gap-4 p-4 focus-ring transition-colors hover:border-primary/40 md:p-5"
              >
                <span className="flex size-10 shrink-0 items-center justify-center rounded-control bg-primary-soft text-primary-strong">
                  <Icon className="size-5" aria-hidden="true" />
                </span>
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
