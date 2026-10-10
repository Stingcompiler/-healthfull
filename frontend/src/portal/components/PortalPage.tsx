import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

import type { AppPath } from "@/app/nav-types";
import { ArrowBack } from "@/components/icons";
import { useDocumentTitle } from "@/lib/hooks/use-document-title";
import { cn } from "@/lib/utils";

import { PILL_CLASSES, type PillTone } from "../lib/tones";

interface PortalPageProps {
  title: string;
  description?: ReactNode;
  /** A link back to the list this page belongs to. */
  back?: { to: AppPath; label: string };
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}

/** One portal screen: its h1 (which also names the tab), an optional back link and actions. */
export function PortalPage({ title, description, back, actions, children, className }: PortalPageProps) {
  useDocumentTitle(title);
  return (
    <div className={cn("flex min-w-0 flex-col gap-5", className)}>
      {back ? (
        <Link
          to={back.to}
          className="-ms-2 inline-flex min-h-11 w-fit items-center gap-1.5 rounded-control px-2 text-sm font-medium text-primary-strong focus-ring print:hidden"
        >
          <ArrowBack className="size-4" aria-hidden="true" />
          {back.label}
        </Link>
      ) : null}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-xl font-bold text-balance text-fg">{title}</h1>
          {description ? <p className="mt-1 text-sm text-pretty text-muted">{description}</p> : null}
        </div>
        {actions ? <div className="flex flex-wrap gap-2 print:hidden">{actions}</div> : null}
      </div>
      {children}
    </div>
  );
}

/** A titled card on a portal screen. */
export function PortalSection({
  title,
  action,
  children,
  className,
  testId,
}: {
  title: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  testId?: string;
}) {
  return (
    <section className={cn("card-surface flex min-w-0 flex-col gap-3 p-4 md:p-5", className)} data-testid={testId}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold text-fg">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

/** A small status label. */
export function Pill({ tone, children, testId }: { tone: PillTone; children: ReactNode; testId?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold",
        PILL_CLASSES[tone],
      )}
      data-testid={testId}
    >
      {children}
    </span>
  );
}

/** A label and value row in a definition list. */
export function Row({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 py-1.5">
      <dt className="text-sm text-muted">{label}</dt>
      <dd className="min-w-0 text-end text-sm break-words text-fg">{children}</dd>
    </div>
  );
}
