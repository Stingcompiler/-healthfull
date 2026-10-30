import { useState } from "react";

import { initialsOf } from "@/lib/initials";
import { cn } from "@/lib/utils";

/**
 * The center's logo when one is set (and loads), else a monogram of its name. Used by the center
 * page's hero and its footer.
 */
export function CenterMark({
  logoUrl,
  name,
  className = "size-16 lg:size-20",
  testId = "center-monogram",
}: {
  logoUrl: string | null | undefined;
  name: string;
  className?: string;
  testId?: string;
}) {
  const [broken, setBroken] = useState(false);
  const logo = broken ? null : (logoUrl ?? null);
  if (logo) {
    return (
      <img
        src={logo}
        alt=""
        width={80}
        height={80}
        className={cn(className, "shrink-0 rounded-card bg-surface object-contain p-1.5")}
        onError={() => {
          setBroken(true);
        }}
      />
    );
  }
  return (
    <span
      aria-hidden="true"
      data-testid={testId}
      className={cn(
        className,
        "inline-flex shrink-0 items-center justify-center rounded-card bg-primary font-bold text-primary-fg",
      )}
    >
      {initialsOf(name) || "+"}
    </span>
  );
}
