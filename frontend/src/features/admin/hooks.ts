import { useCallback, useMemo } from "react";

import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import { useDepartments } from "./api";
import type { DepartmentOut } from "./types";

/** The name of a row in the UI language (name_ar / name_en with fallback). */
export function useLocalName(): (row: { name_ar?: string | null; name_en?: string | null }) => string {
  const language = useLanguage();
  return (row) => pickName({ ar: row.name_ar, en: row.name_en }, language);
}

/** A person's name in the UI language (full_name_ar / full_name_en), else the username. */
export function usePersonName(): (person: {
  full_name_ar?: string | null;
  full_name_en?: string | null;
  username: string;
}) => string {
  const language = useLanguage();
  return useCallback(
    (person) => pickName({ ar: person.full_name_ar, en: person.full_name_en }, language) || person.username,
    [language],
  );
}

/** The department of an id (undefined while the list loads or for an unknown id). */
export function useDepartmentById(): (id: number | null | undefined) => DepartmentOut | undefined {
  const departments = useDepartments();
  const byId = useMemo(() => new Map((departments.data ?? []).map((d) => [d.id, d])), [departments.data]);
  return useCallback((id) => (id === null || id === undefined ? undefined : byId.get(id)), [byId]);
}
