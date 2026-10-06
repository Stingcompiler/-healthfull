import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export function Section({
  id,
  title,
  description,
  children,
}: {
  id: string;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="scroll-mt-24" data-testid={`ds-${id}`}>
      <div className="mb-4 border-b border-border pb-3">
        <h2 id={`${id}-title`} className="text-lg font-bold text-fg md:text-xl">
          {title}
        </h2>
        {description ? <p className="mt-1 max-w-3xl text-sm text-muted">{description}</p> : null}
      </div>
      <div className="flex flex-col gap-6">{children}</div>
    </section>
  );
}

/** A labelled group of examples inside a section. */
export function Demo({ label, children, className }: { label: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-3">
      <h3 className="text-xs font-semibold tracking-wide text-muted uppercase">{label}</h3>
      <div className={cn("min-w-0", className)}>{children}</div>
    </div>
  );
}
