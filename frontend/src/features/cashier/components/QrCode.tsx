import { useMemo } from "react";

import { cn } from "@/lib/utils";

import { encodeQr } from "../lib/qr";

const QUIET = 4;

/** A QR code drawn as one SVG path in the current text color (bundled encoder, no network). */
export function QrCode({ value, label, className }: { value: string; label: string; className?: string }) {
  const { size, path } = useMemo(() => {
    const qr = encodeQr(value);
    const parts: string[] = [];
    qr.modules.forEach((row, y) => {
      row.forEach((dark, x) => {
        if (dark) parts.push(`M${String(x + QUIET)} ${String(y + QUIET)}h1v1h-1z`);
      });
    });
    return { size: qr.size + QUIET * 2, path: parts.join("") };
  }, [value]);
  return (
    <svg
      role="img"
      aria-label={label}
      viewBox={`0 0 ${String(size)} ${String(size)}`}
      shapeRendering="crispEdges"
      className={cn("bg-surface text-fg", className)}
      data-testid="receipt-qr"
    >
      <path d={path} fill="currentColor" />
    </svg>
  );
}
