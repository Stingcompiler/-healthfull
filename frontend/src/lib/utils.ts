import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/**
 * tailwind-merge only knows Tailwind's default scale. Teach it the custom
 * semantic tokens so `cn("text-fg", "text-muted")` keeps the last color and
 * `cn("text-sm", "text-fg")` keeps both.
 */
const twMerge = extendTailwindMerge({
  extend: {
    theme: {
      color: [
        "bg",
        "surface",
        "surface-raised",
        "subtle",
        "fg",
        "fg-muted",
        "muted",
        "border",
        "border-strong",
        "card-border",
        "ring",
        "overlay",
        "transparent",
        "current",
        ...["primary", "secondary", "accent"].flatMap((k) => [k, `${k}-fg`, `${k}-hover`]),
        "primary-strong",
        "primary-soft",
        ...["success", "warning", "danger", "info"].flatMap((k) => [
          k,
          `${k}-contrast`,
          `${k}-bg`,
          `${k}-fg`,
          `${k}-border`,
        ]),
        ...["requested", "invoiced", "paid", "performed", "cancelled", "pending"].flatMap((k) => [
          `state-${k}`,
          `state-${k}-bg`,
          `state-${k}-fg`,
        ]),
      ],
      radius: ["card", "control"],
      shadow: ["card", "raised", "overlay"],
    },
  },
});

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** Exhaustiveness helper for switch statements over unions. */
export function assertNever(value: never): never {
  throw new Error(`Unexpected value: ${String(value)}`);
}
