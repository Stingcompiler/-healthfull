import { HeartPulse, Plus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { AlertCard } from "@/components/AlertCard";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";
import { cn } from "@/lib/utils";

import { useConditions, useCreateCondition, useUpdateCondition } from "../api";
import type { Icd10 } from "../types";
import { Icd10Picker } from "./Icd10Picker";
import { QueryError } from "./QueryError";

/** Chronic conditions of the person (FEATURES 3.2): add by ICD-10 or name, resolve. */
export function ConditionManager({
  patientId,
  open,
  onOpenChange,
}: {
  patientId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation("clinic");
  const language = useLanguage();
  const registry = useConditions(patientId, open);
  const create = useCreateCondition(patientId);
  const update = useUpdateCondition(patientId);
  const translateError = useTranslateError();
  const [code, setCode] = useState<Icd10 | null>(null);
  const [name, setName] = useState("");
  const [since, setSince] = useState("");
  const [error, setError] = useState<string | null>(null);

  const add = () => {
    setError(null);
    create.mutate(
      { icd10_code: code?.code ?? null, name: name.trim(), since: since || null, note: "" },
      {
        onSuccess: () => {
          setCode(null);
          setName("");
          setSince("");
          toast.success(t("condition.addedToast"));
        },
        onError: (e) => {
          setError(translateError(e));
        },
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <HeartPulse className="size-5 text-muted" aria-hidden="true" />
            {t("condition.title")}
          </DialogTitle>
          <DialogDescription>{t("condition.description")}</DialogDescription>
        </DialogHeader>

        {registry.isError ? (
          <QueryError
            title={t("condition.loadError")}
            error={registry.error}
            onRetry={() => void registry.refetch()}
            retrying={registry.isFetching}
          />
        ) : !registry.data ? (
          <Skeleton className="h-20" />
        ) : registry.data.length === 0 ? (
          <p className="text-sm text-muted">{t("condition.none")}</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {registry.data.map((c) => (
              <li
                key={c.id}
                className="flex min-w-0 flex-wrap items-center gap-2 rounded-control border border-border px-3 py-2 text-sm"
              >
                {c.icd10 ? <bdi className="tabular font-semibold">{c.icd10.code}</bdi> : null}
                <span
                  className={cn(
                    "min-w-0 flex-1 break-words",
                    c.status === "active" ? "text-fg" : "text-muted line-through",
                  )}
                >
                  {c.name || (c.icd10 ? pickName({ ar: c.icd10.title_ar, en: c.icd10.title_en }, language) : "")}
                </span>
                {c.status === "active" ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() =>
                      update.mutate(
                        { id: c.id, body: { status: "inactive", reason: "" } },
                        { onError: (e) => toast.error(translateError(e)) },
                      )
                    }
                  >
                    {t("condition.resolve")}
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        )}

        <div className="flex flex-col gap-3 rounded-control bg-subtle p-3">
          <h3 className="text-sm font-semibold text-fg">{t("condition.add")}</h3>
          <Icd10Picker value={code} onChange={setCode} label={t("condition.icd10")} />
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="condition-name">{t("condition.name")}</Label>
              <Input id="condition-name" value={name} maxLength={200} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="condition-since">{t("condition.since")}</Label>
              <Input id="condition-since" type="date" value={since} onChange={(e) => setSince(e.target.value)} />
            </div>
          </div>
          {error ? (
            <AlertCard variant="danger" live title={t("condition.saveError")}>
              {error}
            </AlertCard>
          ) : null}
          <div className="flex justify-end">
            <Button onClick={add} loading={create.isPending} disabled={!code && !name.trim()}>
              <Plus aria-hidden="true" />
              {t("condition.add")}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
