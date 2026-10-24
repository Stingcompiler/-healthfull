import { useState } from "react";

import { BrandMark } from "@/components/BrandMark";
import { useCenterPage } from "@/lib/center/api";
import { useCenterName } from "@/lib/center/hooks";
import { cn } from "@/lib/utils";

/** The center's logo, or the app mark when there is none or it fails to load. Sized up front. */
export function CenterLogo({ size = "md", className }: { size?: "md" | "lg"; className?: string }) {
  const center = useCenterPage();
  const [broken, setBroken] = useState(false);
  const logo = broken ? null : (center.data?.logo_url ?? null);
  const box = size === "lg" ? "size-14" : "size-9";
  return logo ? (
    <img
      src={logo}
      alt=""
      width={size === "lg" ? 56 : 36}
      height={size === "lg" ? 56 : 36}
      className={cn(box, "shrink-0 rounded-control object-contain", className)}
      onError={() => {
        setBroken(true);
      }}
    />
  ) : (
    <BrandMark className={cn(box, className)} />
  );
}

/** The center's logo and name, with an optional second line (headers and sign-in pages). */
export function CenterIdentity({
  subtitle,
  size = "md",
  className,
  nameClassName,
}: {
  subtitle?: string;
  size?: "md" | "lg";
  className?: string;
  nameClassName?: string;
}) {
  const name = useCenterName();
  return (
    <span className={cn("flex min-w-0 items-center gap-2.5", className)} data-testid="center-identity">
      <CenterLogo size={size} />
      <span className="min-w-0 leading-tight">
        <span className={cn("block truncate text-sm font-bold text-fg", nameClassName)}>{name}</span>
        {subtitle ? <span className="block truncate text-xs text-muted">{subtitle}</span> : null}
      </span>
    </span>
  );
}
