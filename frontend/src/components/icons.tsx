import {
  ArrowLeft,
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  type LucideProps,
} from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Direction-aware icons. "Next/forward" points toward the inline end:
 * right in LTR, left in RTL. Implemented by mirroring the LTR glyph under
 * [dir=rtl] so the same component works without reading the language.
 */
export const flipInRtl = "rtl:-scale-x-100";

export function ChevronNext({ className, ...props }: LucideProps) {
  return <ChevronRight aria-hidden="true" className={cn(flipInRtl, className)} {...props} />;
}

export function ChevronPrev({ className, ...props }: LucideProps) {
  return <ChevronLeft aria-hidden="true" className={cn(flipInRtl, className)} {...props} />;
}

export function ChevronsNext({ className, ...props }: LucideProps) {
  return <ChevronsRight aria-hidden="true" className={cn(flipInRtl, className)} {...props} />;
}

export function ChevronsPrev({ className, ...props }: LucideProps) {
  return <ChevronsLeft aria-hidden="true" className={cn(flipInRtl, className)} {...props} />;
}

export function ArrowNext({ className, ...props }: LucideProps) {
  return <ArrowRight aria-hidden="true" className={cn(flipInRtl, className)} {...props} />;
}

export function ArrowBack({ className, ...props }: LucideProps) {
  return <ArrowLeft aria-hidden="true" className={cn(flipInRtl, className)} {...props} />;
}
