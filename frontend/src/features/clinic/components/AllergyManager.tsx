import { Plus, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { AlertCard } from "@/components/AlertCard";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";
import { cn } from "@/lib/utils";

import { useAllergies, useCreateAllergy, useDrugClasses, useUpdateAllergy } from "../api";
import { allergyLabel } from "../lib";
import type { Allergy, AllergyInput } from "../types";
import { QueryError } from "./QueryError";

type AllergenType = AllergyInput["allergen_type"];
type Severity = NonNullable<AllergyInput["severity"]>;
const TYPES: readonly AllergenType[] = ["drug_class", "drug", "food", "environmental", "other"];
const SEVERITIES: readonly Severity[] = ["mild", "moderate", "severe", "life_threatening"];

/** The allergy registry of the person (FEATURES 3.2): add, resolve, mark entered in error. */
export function AllergyManager({
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
  const registry = useAllergies(patientId, open);
  const classes = useDrugClasses(open);
  const create = useCreateAllergy(patientId);
  const update = useUpdateAllergy(patientId);
  const translateError = useTranslateError();
  const [type, setType] = useState<AllergenType>("drug_class");
  const [drugClass, setDrugClass] = useState("");
  const [substance, setSubstance] = useState("");
  const [reaction, setReaction] = useState("");
  const [severity, setSeverity] = useState<Severity>("moderate");
  const [error, setError] = useState<string | null>(null);

  const ready = type === "drug_class" ? drugClass !== "" : substance.trim() !== "";

  const add = () => {
    setError(null);
    create.mutate(
      {
        allergen_type: type,
        drug_class_id: type === "drug_class" ? Number(drugClass) : null,
        substance: type === "drug_class" ? "" : substance.trim(),
        reaction: reaction.trim(),
        severity,
        note: "",
      },
      {
        onSuccess: () => {
          setDrugClass("");
          setSubstance("");
          setReaction("");
          toast.success(t("allergy.addedToast"));
        },
        onError: (e) => {
          setError(translateError(e));
        },
      },
    );
  };

  const [changing, setChanging] = useState<{ allergy: Allergy; status: AllergyStatus } | null>(null);

  const setStatus = (id: number, status: AllergyStatus) =>
    update.mutateAsync({ id, body: { status } }).then(() => {
      toast.success(t(`allergy.statusToast.${status}`));
    });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ShieldAlert className="size-5 text-danger" aria-hidden="true" />
            {t("allergy.title")}
          </DialogTitle>
          <DialogDescription>{t("allergy.description")}</DialogDescription>
        </DialogHeader>

        {registry.isError ? (
          <QueryError
            title={t("allergy.loadError")}
            error={registry.error}
            onRetry={() => void registry.refetch()}
            retrying={registry.isFetching}
          />
        ) : !registry.data ? (
          <Skeleton className="h-20" />
        ) : registry.data.length === 0 ? (
          <p className="text-sm text-muted">{t("allergy.none")}</p>
        ) : (
          <ul className="flex flex-col gap-2" data-testid="allergy-list">
            {registry.data.map((a) => (
              <li
                key={a.id}
                className={cn(
                  "flex min-w-0 flex-wrap items-center gap-2 rounded-control border px-3 py-2 text-sm",
                  a.status === "active" ? "border-danger-border bg-danger-bg" : "border-border",
                )}
              >
                <span
                  className={cn("font-semibold", a.status === "active" ? "text-danger-fg" : "text-muted line-through")}
                >
                  {allergyLabel(a, language)}
                </span>
                <Badge variant={a.severity === "mild" ? "neutral" : "danger"}>
                  {t(`allergy.severity.${a.severity}`)}
                </Badge>
                {a.reaction ? <span className="min-w-0 text-xs break-words text-fg-muted">{a.reaction}</span> : null}
                <div className="ms-auto flex flex-wrap gap-1">
                  {a.status === "active" ? (
                    <>
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={t("allergy.resolveNamed", { name: allergyLabel(a, language) })}
                        onClick={() => setChanging({ allergy: a, status: "inactive" })}
                        data-testid="allergy-resolve"
                      >
                        {t("allergy.resolve")}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={t("allergy.errorNamed", { name: allergyLabel(a, language) })}
                        onClick={() => setChanging({ allergy: a, status: "entered_in_error" })}
                        data-testid="allergy-error"
                      >
                        {t("allergy.error")}
                      </Button>
                    </>
                  ) : (
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={t("allergy.reactivateNamed", { name: allergyLabel(a, language) })}
                      onClick={() => {
                        setStatus(a.id, "active").catch((e: unknown) => toast.error(translateError(e)));
                      }}
                    >
                      {t("allergy.reactivate")}
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}

        <div className="flex flex-col gap-3 rounded-control bg-subtle p-3" data-testid="allergy-form">
          <h3 className="text-sm font-semibold text-fg">{t("allergy.add")}</h3>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="allergy-type">{t("allergy.type")}</Label>
              <Select value={type} onValueChange={(v) => setType(v as AllergenType)}>
                <SelectTrigger id="allergy-type">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TYPES.map((v) => (
                    <SelectItem key={v} value={v}>
                      {t(`allergy.types.${v}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {type === "drug_class" ? (
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="allergy-class">{t("allergy.drugClass")}</Label>
                <Select value={drugClass} onValueChange={setDrugClass}>
                  <SelectTrigger id="allergy-class" data-testid="allergy-class">
                    <SelectValue placeholder={t("allergy.choose")} />
                  </SelectTrigger>
                  <SelectContent>
                    {(classes.data ?? []).map((c) => (
                      <SelectItem key={c.id} value={String(c.id)}>
                        {pickName({ ar: c.name_ar, en: c.name_en }, language)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            ) : (
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="allergy-substance">{t("allergy.substance")}</Label>
                <Input
                  id="allergy-substance"
                  value={substance}
                  maxLength={200}
                  onChange={(e) => setSubstance(e.target.value)}
                />
              </div>
            )}
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="allergy-reaction">{t("allergy.reaction")}</Label>
              <Input
                id="allergy-reaction"
                value={reaction}
                maxLength={300}
                onChange={(e) => setReaction(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="allergy-severity">{t("allergy.severityLabel")}</Label>
              <Select value={severity} onValueChange={(v) => setSeverity(v as Severity)}>
                <SelectTrigger id="allergy-severity">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SEVERITIES.map((v) => (
                    <SelectItem key={v} value={v}>
                      {t(`allergy.severity.${v}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          {error ? (
            <AlertCard variant="danger" live title={t("allergy.saveError")}>
              {error}
            </AlertCard>
          ) : null}
          <div className="flex justify-end">
            <Button onClick={add} loading={create.isPending} disabled={!ready} data-testid="allergy-add">
              <Plus aria-hidden="true" />
              {t("allergy.add")}
            </Button>
          </div>
        </div>
        <ConfirmDialog
          open={changing !== null}
          onOpenChange={(o) => {
            if (!o) setChanging(null);
          }}
          destructive
          title={
            changing
              ? t(`allergy.confirm.${changing.status === "inactive" ? "resolve" : "error"}Title`, {
                  name: allergyLabel(changing.allergy, language),
                })
              : undefined
          }
          description={
            changing
              ? t(`allergy.confirm.${changing.status === "inactive" ? "resolve" : "error"}Description`)
              : undefined
          }
          confirmLabel={changing?.status === "inactive" ? t("allergy.resolve") : t("allergy.error")}
          onConfirm={async () => {
            if (!changing) return;
            await setStatus(changing.allergy.id, changing.status);
            setChanging(null);
          }}
        />
      </DialogContent>
    </Dialog>
  );
}

type AllergyStatus = "inactive" | "entered_in_error" | "active";
