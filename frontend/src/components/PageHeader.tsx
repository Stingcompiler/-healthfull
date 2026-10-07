import type { ReactNode } from "react";

import { useDocumentTitle } from "@/lib/hooks/use-document-title";
import { cn } from "@/lib/utils";

export interface PageHeaderProps {
  title: ReactNode;
  description?: ReactNode;
  /** Small line above the title, e.g. a breadcrumb or module name. */
  eyebrow?: ReactNode;
  /** Buttons aligned to the inline end; wrap under the title on phones. */
  actions?: ReactNode;
  icon?: ReactNode;
  /** Browser tab title; defaults to `title` when that is a string. */
  documentTitle?: string;
  className?: string;
}

export function PageHeader({ title, description, eyebrow, actions, icon, documentTitle, className }: PageHeaderProps) {
  useDocumentTitle(documentTitle ?? (typeof title === "string" ? title : undefined));
  return (
    <header
      data-slot="page-header"
      className={cn("flex flex-col gap-4 pb-2 sm:flex-row sm:items-end sm:justify-between", className)}
    >
      <div className="flex min-w-0 items-start gap-3">
        {icon ? (
          <div className="mt-0.5 flex size-11 shrink-0 items-center justify-center rounded-card bg-primary-soft text-primary-strong [&_svg]:size-5">
            {icon}
          </div>
        ) : null}
        <div className="min-w-0">
          {eyebrow ? <div className="mb-1 text-xs font-medium text-muted">{eyebrow}</div> : null}
          <h1 className="text-xl font-bold tracking-tight text-balance text-fg md:text-2xl">{title}</h1>
          {description ? <p className="mt-1 max-w-prose text-sm text-pretty text-muted">{description}</p> : null}
        </div>
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}
