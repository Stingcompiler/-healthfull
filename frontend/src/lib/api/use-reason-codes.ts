/** Active reason codes of one category (core.ReasonCode), for reason dialogs. */
import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import type { Language } from "@/lib/preferences";

export type ReasonCategory = components["schemas"]["ReasonCodeIn"]["category"];
export type ReasonCodeRow = components["schemas"]["ReasonCodeOut"];

export function useReasonCodes(category: ReasonCategory, enabled = true) {
  return useQuery({
    queryKey: ["reason-codes", category],
    queryFn: () => unwrap(api.GET("/api/core/reason-codes", { params: { query: { category, active: true } } })),
    enabled,
    staleTime: 5 * 60_000,
  });
}

/** The reason's label in the current language, falling back to the other one. */
export function reasonLabel(reason: Pick<ReasonCodeRow, "label_ar" | "label_en">, language: Language): string {
  return (language === "ar" ? reason.label_ar : reason.label_en) || reason.label_en || reason.label_ar;
}
