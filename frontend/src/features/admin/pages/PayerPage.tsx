import { zodResolver } from "@hookform/resolvers/zod";
import { Link, useParams } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import { Ban, Pencil, Plus, Power, ShieldCheck } from "lucide-react";
import { useMemo, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import { DataTable } from "@/components/DataTable";
import { Form, RadioGroupField, SelectField, SwitchField, TextareaField, TextField } from "@/components/form";
import { ArrowBack } from "@/components/icons";
import { MoneyText } from "@/components/MoneyText";
import { SearchInput } from "@/components/SearchInput";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useTranslateError } from "@/lib/api/translate-error";
import { formatPercent } from "@/lib/format";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { useLanguage } from "@/lib/i18n-hooks";
import { vmsg } from "@/lib/validation";

import {
  useCoveragePreview,
  usePayer,
  usePriceLists,
  useSavePayer,
  useSaveExclusion,
  useSaveRule,
  useServices,
} from "../api";
import { AdminPage, QueryState } from "../components/AdminPage";
import { ListEmpty } from "../components/ListEmpty";
import { DateField } from "../components/DateField";
import { ActiveBadge, Code, FormDialog } from "../components/FormDialog";
import { useLocalName } from "../hooks";
import {
  CLAIM_PERIODS,
  PAYER_KINDS,
  RULE_KINDS,
  SERVICE_KINDS,
  type CoveragePreviewIn,
  type CoverageRuleOut,
  type ExclusionOut,
  type PayerKind,
  type PayerOut,
  type ClaimPeriod,
  type RuleKind,
  type ServiceKind,
} from "../types";

const NONE = "__none__";
const AMOUNT = /^[0-9٠-٩۰-۹]+([.٫][0-9٠-٩۰-۹]{1,2})?$/;
type Tab = "contract" | "rules" | "exclusions";

export function PayerPage() {
  const { t } = useTranslation("admin");
  const localName = useLocalName();
  const { payerId } = useParams({ from: "/_app/administration/payers/$payerId" });
  const payer = usePayer(Number(payerId));
  const [tab, setTab] = useState<Tab>("rules");
  const data = payer.data;
  return (
    <AdminPage
      section="payers"
      title={data ? localName(data) : t("sections.payers.title")}
      description={data ? <Code>{data.code}</Code> : undefined}
      documentTitle={data ? localName(data) : t("sections.payers.title")}
    >
      <div>
        <Button asChild variant="link">
          <Link to="/administration/payers">
            <ArrowBack />
            {t("payers.backToList")}
          </Link>
        </Button>
      </div>
      <QueryState loading={payer.isPending} error={payer.error} onRetry={() => void payer.refetch()}>
        {data ? (
          <Tabs
            value={tab}
            onValueChange={(v) => {
              setTab(v as Tab);
            }}
          >
            <TabsList aria-label={t("sections.payers.title")}>
              <TabsTrigger value="rules">{t("payers.rulesTab")}</TabsTrigger>
              <TabsTrigger value="exclusions">{t("payers.exclusionsTab")}</TabsTrigger>
              <TabsTrigger value="contract">{t("payers.contractTab")}</TabsTrigger>
            </TabsList>
            <TabsContent value="rules">
              <RulesTab payer={data} />
            </TabsContent>
            <TabsContent value="exclusions">
              <ExclusionsTab payer={data} />
            </TabsContent>
            <TabsContent value="contract">
              <ContractForm key={data.id} payer={data} />
            </TabsContent>
          </Tabs>
        ) : null}
      </QueryState>
    </AdminPage>
  );
}

// --- Contract ---------------------------------------------------------------------------------

const contractSchema = z
  .object({
    name_ar: z.string().trim().min(1, vmsg("validation.required")).max(200),
    name_en: z.string().trim().min(1, vmsg("validation.required")).max(200),
    kind: z.enum(PAYER_KINDS as [PayerKind, ...PayerKind[]]),
    price_list: z.string(),
    contract_no: z.string().max(100),
    contract_start: z.string(),
    contract_end: z.string(),
    claim_period: z.enum(CLAIM_PERIODS as [ClaimPeriod, ...ClaimPeriod[]]),
    requires_card_number: z.boolean(),
    contact_name: z.string().max(150),
    phone: z.string().max(50),
    email: z.union([z.literal(""), z.email(vmsg("admin:payers.emailRule"))]),
    address: z.string().max(300),
    notes: z.string().max(2000),
    active: z.boolean(),
  })
  .refine((v) => !v.contract_start || !v.contract_end || v.contract_end >= v.contract_start, {
    path: ["contract_end"],
    message: vmsg("admin:payers.datesRule"),
  });
type ContractValues = z.infer<typeof contractSchema>;

function contractValues(p: PayerOut): ContractValues {
  return {
    name_ar: p.name_ar,
    name_en: p.name_en,
    kind: p.kind,
    price_list: p.price_list_id ? String(p.price_list_id) : NONE,
    contract_no: p.contract_no,
    contract_start: p.contract_start ?? "",
    contract_end: p.contract_end ?? "",
    claim_period: p.claim_period,
    requires_card_number: p.requires_card_number,
    contact_name: p.contact_name,
    phone: p.phone,
    email: p.email,
    address: p.address,
    notes: p.notes,
    active: p.active,
  };
}

function ContractForm({ payer }: { payer: PayerOut }) {
  const { t } = useTranslation(["admin", "errors"]);
  const localName = useLocalName();
  const save = useSavePayer();
  const lists = usePriceLists();
  const translateError = useTranslateError();
  const form = useForm<ContractValues>({ resolver: zodResolver(contractSchema), defaultValues: contractValues(payer) });
  const submit = form.handleSubmit(async ({ price_list, contract_start, contract_end, ...rest }) => {
    const saved = await save.mutateAsync({
      id: payer.id,
      body: {
        ...rest,
        price_list_id: price_list === NONE ? null : Number(price_list),
        contract_start: contract_start || null,
        contract_end: contract_end || null,
      },
    });
    form.reset(contractValues(saved));
    toast.success(t("admin:common.saved"));
  });
  const listOptions = [
    { value: NONE, label: t("admin:payers.cashList") },
    ...(lists.data ?? [])
      .filter((l) => l.active || l.id === payer.price_list_id)
      .map((l) => ({ value: String(l.id), label: `${localName(l)} (${l.code})` })),
  ];
  return (
    <Form {...form}>
      <form onSubmit={(e) => void submit(e)} noValidate className="card-surface grid gap-4 p-4 md:p-5">
        {save.error ? (
          <AlertCard variant="danger" title={t("errors:title")} live>
            {translateError(save.error)}
          </AlertCard>
        ) : null}
        <div className="grid gap-4 md:grid-cols-2">
          <TextField control={form.control} name="name_ar" label={t("admin:common.nameAr")} dir="rtl" required />
          <TextField control={form.control} name="name_en" label={t("admin:common.nameEn")} dir="ltr" required />
          <SelectField
            control={form.control}
            name="kind"
            label={t("admin:payers.kind")}
            options={PAYER_KINDS.map((k) => ({ value: k, label: t(`admin:payers.kinds.${k}`) }))}
          />
          <SelectField
            control={form.control}
            name="price_list"
            label={t("admin:payers.priceList")}
            options={listOptions}
          />
          <TextField control={form.control} name="contract_no" label={t("admin:payers.contractNo")} dir="ltr" />
          <SelectField
            control={form.control}
            name="claim_period"
            label={t("admin:payers.claimPeriod")}
            options={CLAIM_PERIODS.map((c) => ({ value: c, label: t(`admin:payers.periods.${c}`) }))}
          />
          <DateField control={form.control} name="contract_start" label={t("admin:payers.contractStart")} />
          <DateField control={form.control} name="contract_end" label={t("admin:payers.contractEnd")} />
          <TextField control={form.control} name="contact_name" label={t("admin:payers.contactName")} />
          <TextField control={form.control} name="phone" label={t("admin:payers.phone")} type="tel" dir="ltr" />
          <TextField control={form.control} name="email" label={t("admin:payers.email")} type="email" dir="ltr" />
          <TextField control={form.control} name="address" label={t("admin:payers.address")} />
        </div>
        <TextareaField control={form.control} name="notes" label={t("admin:payers.notes")} rows={2} />
        <div className="flex flex-col gap-3 sm:flex-row sm:gap-6">
          <SwitchField control={form.control} name="requires_card_number" label={t("admin:payers.requiresCard")} />
          <SwitchField control={form.control} name="active" label={t("admin:common.active")} />
        </div>
        <div>
          <Button type="submit" loading={form.formState.isSubmitting} disabled={!form.formState.isDirty}>
            {t("admin:common.save")}
          </Button>
        </div>
      </form>
    </Form>
  );
}

// --- Coverage rules ---------------------------------------------------------------------------

function useScopeLabel() {
  const { t } = useTranslation("admin");
  const localName = useLocalName();
  return (
    row: Pick<CoverageRuleOut, "service_id" | "service_code" | "service_name_ar" | "service_name_en" | "service_kind">,
  ) => {
    if (row.service_id) return localName({ name_ar: row.service_name_ar, name_en: row.service_name_en });
    if (row.service_kind) return t("payers.allOfKind", { kind: t(`kinds.${row.service_kind}`) });
    return t("payers.defaultScope");
  };
}

function RuleSummary({ rule }: { rule: CoverageRuleOut }) {
  const { t } = useTranslation("admin");
  const language = useLanguage();
  if (rule.rule_kind === "percentage")
    return (
      <span>{t("payers.summary.percentage", { percent: formatPercent(rule.payer_percent ?? "0", language) })}</span>
    );
  if (rule.rule_kind === "copay")
    return (
      <span>
        {t("payers.summary.copay")} <MoneyText value={rule.copay_amount ?? "0"} />
      </span>
    );
  return (
    <span>
      {t("payers.summary.ceiling", { percent: formatPercent(rule.payer_percent ?? "100", language) })}{" "}
      <MoneyText value={rule.ceiling_amount ?? "0"} />
    </span>
  );
}

function RulesTab({ payer }: { payer: PayerOut }) {
  const { t } = useTranslation("admin");
  const scopeLabel = useScopeLabel();
  const [editing, setEditing] = useState<CoverageRuleOut | "new" | null>(null);
  const columns = useMemo<ColumnDef<CoverageRuleOut>[]>(
    () => [
      {
        id: "scope",
        accessorFn: (r) => scopeLabel(r),
        header: t("payers.scope"),
        meta: { label: t("payers.scope") },
        cell: ({ row }) => (
          <div className="min-w-0">
            <div className="truncate font-medium text-fg">{scopeLabel(row.original)}</div>
            {row.original.service_code ? <Code>{row.original.service_code}</Code> : null}
          </div>
        ),
      },
      {
        id: "rule",
        accessorFn: (r) => r.rule_kind,
        header: t("payers.rule"),
        meta: { label: t("payers.rule") },
        cell: ({ row }) => <RuleSummary rule={row.original} />,
      },
      {
        id: "flags",
        accessorFn: (r) => (r.requires_pre_approval ? 1 : 0),
        header: t("payers.preApproval"),
        meta: { label: t("payers.preApproval") },
        cell: ({ row }) =>
          row.original.requires_pre_approval ? <Badge variant="warning">{t("payers.needsPreApproval")}</Badge> : "—",
      },
      {
        accessorKey: "active",
        header: t("common.status"),
        meta: { label: t("common.status") },
        cell: ({ row }) => <ActiveBadge active={row.original.active} />,
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps -- scopeLabel depends on t and the language only
    [t],
  );
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted">{t("payers.rulesHint")}</p>
      <div className="flex justify-end">
        <Button
          onClick={() => {
            setEditing("new");
          }}
        >
          <Plus />
          {t("payers.addRule")}
        </Button>
      </div>
      <DataTable
        caption={t("payers.rulesTab")}
        columns={columns}
        data={payer.coverage_rules}
        getRowId={(r) => String(r.id)}
        emptyState={
          <ListEmpty
            icon={<ShieldCheck />}
            title={t("empty.rules.title")}
            description={t("empty.rules.description")}
            actionLabel={t("payers.addRule")}
            onAction={() => {
              setEditing("new");
            }}
          />
        }
        onRowClick={setEditing}
        rowLabel={(r) => t("common.editNamed", { name: scopeLabel(r) })}
        rowActions={(r) => [
          {
            label: t("payers.editRule"),
            icon: <Pencil />,
            onSelect: () => {
              setEditing(r);
            },
          },
        ]}
      />
      {editing ? (
        <RuleDialog
          payer={payer}
          rule={editing === "new" ? null : editing}
          onClose={() => {
            setEditing(null);
          }}
        />
      ) : null}
    </div>
  );
}

const ruleSchema = z
  .object({
    scope: z.enum(["default", "kind", "service"]),
    service_kind: z.string(),
    service: z.string(),
    rule_kind: z.enum(RULE_KINDS as [RuleKind, ...RuleKind[]]),
    payer_percent: z.string().trim(),
    copay_amount: z.string().trim(),
    ceiling_amount: z.string().trim(),
    requires_pre_approval: z.boolean(),
    note: z.string().max(300),
    active: z.boolean(),
  })
  .superRefine((v, ctx) => {
    const need = (field: "payer_percent" | "copay_amount" | "ceiling_amount", optional = false) => {
      const value = v[field];
      if (value === "" && optional) return;
      if (!AMOUNT.test(value))
        ctx.addIssue({ code: "custom", path: [field], message: vmsg("admin:payers.amountRule") });
    };
    if (v.rule_kind === "percentage") need("payer_percent");
    if (v.rule_kind === "copay") need("copay_amount");
    if (v.rule_kind === "ceiling") {
      need("ceiling_amount");
      need("payer_percent", true);
    }
    if (v.scope === "kind" && !v.service_kind)
      ctx.addIssue({ code: "custom", path: ["service_kind"], message: vmsg("validation.selectOption") });
    if (v.scope === "service" && !v.service)
      ctx.addIssue({ code: "custom", path: ["service"], message: vmsg("validation.selectOption") });
  });
type RuleValues = z.infer<typeof ruleSchema>;

/** The API amounts of a rule form: only the fields its kind uses (null for the rest). */
function ruleAmounts(v: Pick<RuleValues, "rule_kind" | "payer_percent" | "copay_amount" | "ceiling_amount">) {
  return {
    payer_percent: v.rule_kind === "copay" || v.payer_percent === "" ? null : v.payer_percent,
    copay_amount: v.rule_kind === "copay" ? v.copay_amount : null,
    ceiling_amount: v.rule_kind === "ceiling" ? v.ceiling_amount : null,
  };
}

function RuleDialog({ payer, rule, onClose }: { payer: PayerOut; rule: CoverageRuleOut | null; onClose: () => void }) {
  const { t } = useTranslation("admin");
  const save = useSaveRule();
  const form = useForm<RuleValues>({
    resolver: zodResolver(ruleSchema),
    defaultValues: {
      scope: rule?.scope ?? "default",
      service_kind: rule?.service_kind ?? "",
      service: rule?.service_id ? String(rule.service_id) : "",
      rule_kind: rule?.rule_kind ?? "percentage",
      payer_percent: rule?.payer_percent ?? "",
      copay_amount: rule?.copay_amount ?? "",
      ceiling_amount: rule?.ceiling_amount ?? "",
      requires_pre_approval: rule?.requires_pre_approval ?? false,
      note: rule?.note ?? "",
      active: rule?.active ?? true,
    },
  });
  const [scope, ruleKind] = useWatch({ control: form.control, name: ["scope", "rule_kind"] });
  return (
    <FormDialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={rule ? t("payers.editRule") : t("payers.addRule")}
      form={form}
      error={save.error}
      wide
      onSubmit={async (v) => {
        const amounts = ruleAmounts(v);
        const common = {
          rule_kind: v.rule_kind,
          ...amounts,
          requires_pre_approval: v.requires_pre_approval,
          note: v.note,
          active: v.active,
        };
        await save.mutateAsync(
          rule
            ? { payerId: payer.id, id: rule.id, body: common }
            : {
                payerId: payer.id,
                body: {
                  ...common,
                  service_kind: v.scope === "kind" ? (v.service_kind as ServiceKind) : null,
                  service_id: v.scope === "service" ? Number(v.service) : null,
                },
              },
        );
        toast.success(t("common.saved"));
        onClose();
      }}
    >
      {rule ? null : (
        <>
          <RadioGroupField
            control={form.control}
            name="scope"
            label={t("payers.scope")}
            options={[
              { value: "default", label: t("payers.defaultScope") },
              { value: "kind", label: t("payers.kindScope") },
              { value: "service", label: t("payers.serviceScope") },
            ]}
          />
          {scope === "kind" ? (
            <SelectField
              control={form.control}
              name="service_kind"
              label={t("catalog.kind")}
              options={SERVICE_KINDS.map((k) => ({ value: k, label: t(`kinds.${k}`) }))}
              required
            />
          ) : null}
          {scope === "service" ? <ServicePicker form={form} /> : null}
        </>
      )}
      <RadioGroupField
        control={form.control}
        name="rule_kind"
        label={t("payers.rule")}
        options={RULE_KINDS.map((k) => ({ value: k, label: t(`payers.ruleKinds.${k}`) }))}
      />
      <div className="grid gap-4 sm:grid-cols-2">
        {ruleKind !== "copay" ? (
          <TextField
            control={form.control}
            name="payer_percent"
            label={ruleKind === "ceiling" ? t("payers.payerPercentOptional") : t("payers.payerPercent")}
            inputMode="decimal"
            dir="ltr"
            required={ruleKind === "percentage"}
          />
        ) : null}
        {ruleKind === "copay" ? (
          <TextField
            control={form.control}
            name="copay_amount"
            label={t("payers.copayAmount")}
            inputMode="decimal"
            dir="ltr"
            required
          />
        ) : null}
        {ruleKind === "ceiling" ? (
          <TextField
            control={form.control}
            name="ceiling_amount"
            label={t("payers.ceilingAmount")}
            inputMode="decimal"
            dir="ltr"
            required
          />
        ) : null}
      </div>
      <ExampleSplit form={form} />
      <SwitchField
        control={form.control}
        name="requires_pre_approval"
        label={t("payers.preApproval")}
        description={t("payers.preApprovalHint")}
      />
      <TextField control={form.control} name="note" label={t("payers.note")} />
      <SwitchField control={form.control} name="active" label={t("common.active")} />
    </FormDialog>
  );
}

function ServicePicker({ form }: { form: ReturnType<typeof useForm<RuleValues>> }) {
  const { t } = useTranslation("admin");
  const localName = useLocalName();
  const [q, setQ] = useState("");
  const services = useServices({ q: q || undefined, active: true });
  return (
    <div className="grid gap-2">
      <SearchInput label={t("catalog.search")} placeholder={t("catalog.search")} onSearch={setQ} />
      <SelectField
        control={form.control}
        name="service"
        label={t("prices.service")}
        options={(services.data?.items ?? []).map((s) => ({
          value: String(s.id),
          label: `${localName(s)} (${s.code})`,
        }))}
        required
      />
    </div>
  );
}

/**
 * Live example: how a line of `gross` splits under the rule being edited. The backend computes
 * it with the same coverage rule that splits invoice lines; the screen only shows the result.
 */
function ExampleSplit({ form }: { form: ReturnType<typeof useForm<RuleValues>> }) {
  const { t } = useTranslation("admin");
  const [gross, setGross] = useState("10000");
  const [ruleKind, payerPercent, copay, ceiling] = useWatch({
    control: form.control,
    name: ["rule_kind", "payer_percent", "copay_amount", "ceiling_amount"],
  });
  const amounts = ruleAmounts({
    rule_kind: ruleKind,
    payer_percent: payerPercent,
    copay_amount: copay,
    ceiling_amount: ceiling,
  });
  const complete =
    AMOUNT.test(gross.trim()) &&
    (ruleKind !== "percentage" || (amounts.payer_percent !== null && AMOUNT.test(amounts.payer_percent))) &&
    (ruleKind !== "copay" || (amounts.copay_amount !== null && AMOUNT.test(amounts.copay_amount))) &&
    (ruleKind !== "ceiling" ||
      (amounts.ceiling_amount !== null &&
        AMOUNT.test(amounts.ceiling_amount) &&
        (amounts.payer_percent === null || AMOUNT.test(amounts.payer_percent))));
  const body: CoveragePreviewIn | null = complete ? { rule_kind: ruleKind, gross: gross.trim(), ...amounts } : null;
  const debounced = useDebouncedValue(body, 250);
  const preview = useCoveragePreview(debounced);
  const translateError = useTranslateError();
  return (
    <section
      className="grid gap-3 rounded-control border border-info-border bg-info-bg p-3 text-info-fg"
      aria-labelledby="split-title"
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <h3 id="split-title" className="text-sm font-semibold">
          {t("payers.example")}
        </h3>
        <div className="grid gap-1 sm:w-40">
          <Label htmlFor="example-gross" className="text-xs">
            {t("payers.exampleGross")}
          </Label>
          <Input
            id="example-gross"
            value={gross}
            onChange={(e) => {
              setGross(e.target.value);
            }}
            inputMode="decimal"
            dir="ltr"
            className="bg-surface text-fg"
          />
        </div>
      </div>
      {!body ? (
        <p className="text-sm">{t("payers.exampleIncomplete")}</p>
      ) : preview.error ? (
        <p className="text-sm">{translateError(preview.error)}</p>
      ) : preview.data ? null : (
        <p className="text-sm">{t("payers.exampleLoading")}</p>
      )}
      {/* Only the final split is announced (not every keystroke in the amount fields). */}
      <div aria-live="polite" aria-atomic="true">
        {body && !preview.error && preview.data ? (
          <dl className="grid grid-cols-2 gap-2" data-testid="example-split">
            <div className="rounded-control bg-surface p-2 text-fg">
              <dt className="text-xs text-muted">{t("payers.payerShare")}</dt>
              <dd className="text-lg font-semibold" data-testid="example-payer">
                <MoneyText value={preview.data.payer_share} />
              </dd>
            </div>
            <div className="rounded-control bg-surface p-2 text-fg">
              <dt className="text-xs text-muted">{t("payers.patientShare")}</dt>
              <dd className="text-lg font-semibold" data-testid="example-patient">
                <MoneyText value={preview.data.patient_share} />
              </dd>
            </div>
          </dl>
        ) : null}
      </div>
    </section>
  );
}

// --- Exclusions -------------------------------------------------------------------------------

const exclusionSchema = z
  .object({
    scope: z.enum(["kind", "service"]),
    service_kind: z.string(),
    service: z.string(),
    note: z.string().max(300),
  })
  .superRefine((v, ctx) => {
    if (v.scope === "kind" && !v.service_kind)
      ctx.addIssue({ code: "custom", path: ["service_kind"], message: vmsg("validation.selectOption") });
    if (v.scope === "service" && !v.service)
      ctx.addIssue({ code: "custom", path: ["service"], message: vmsg("validation.selectOption") });
  });
type ExclusionValues = z.infer<typeof exclusionSchema>;

function ExclusionsTab({ payer }: { payer: PayerOut }) {
  const { t } = useTranslation("admin");
  const scopeLabel = useScopeLabel();
  const save = useSaveExclusion();
  const translateError = useTranslateError();
  const [adding, setAdding] = useState(false);
  const toggle = async (row: ExclusionOut) => {
    try {
      await save.mutateAsync({ payerId: payer.id, id: row.id, body: { active: !row.active } });
    } catch (e) {
      toast.error(translateError(e));
    }
  };
  const columns = useMemo<ColumnDef<ExclusionOut>[]>(
    () => [
      {
        id: "scope",
        accessorFn: (r) => scopeLabel(r),
        header: t("payers.excluded"),
        meta: { label: t("payers.excluded") },
        cell: ({ row }) => (
          <div className="min-w-0">
            <div className="truncate font-medium text-fg">{scopeLabel(row.original)}</div>
            {row.original.service_code ? <Code>{row.original.service_code}</Code> : null}
          </div>
        ),
      },
      { accessorKey: "note", header: t("payers.note"), meta: { label: t("payers.note") } },
      {
        accessorKey: "active",
        header: t("common.status"),
        meta: { label: t("common.status") },
        cell: ({ row }) => <ActiveBadge active={row.original.active} />,
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps -- scopeLabel depends on t and the language only
    [t],
  );
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted">{t("payers.exclusionsHint")}</p>
      <div className="flex justify-end">
        <Button
          onClick={() => {
            setAdding(true);
          }}
        >
          <Ban />
          {t("payers.addExclusion")}
        </Button>
      </div>
      <DataTable
        caption={t("payers.exclusionsTab")}
        columns={columns}
        data={payer.exclusions}
        getRowId={(r) => String(r.id)}
        emptyState={
          <ListEmpty
            icon={<Ban />}
            title={t("empty.exclusions.title")}
            description={t("empty.exclusions.description")}
            actionLabel={t("payers.addExclusion")}
            actionIcon={<Ban />}
            onAction={() => {
              setAdding(true);
            }}
          />
        }
        rowActions={(r) => [
          {
            label: r.active ? t("payers.switchOff") : t("payers.switchOn"),
            icon: <Power />,
            onSelect: () => void toggle(r),
          },
        ]}
      />
      {adding ? (
        <ExclusionDialog
          payer={payer}
          onClose={() => {
            setAdding(false);
          }}
        />
      ) : null}
    </div>
  );
}

function ExclusionDialog({ payer, onClose }: { payer: PayerOut; onClose: () => void }) {
  const { t } = useTranslation("admin");
  const save = useSaveExclusion();
  const form = useForm<ExclusionValues>({
    resolver: zodResolver(exclusionSchema),
    defaultValues: { scope: "service", service_kind: "", service: "", note: "" },
  });
  const scope = useWatch({ control: form.control, name: "scope" });
  return (
    <FormDialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={t("payers.addExclusion")}
      form={form}
      error={save.error}
      onSubmit={async (v) => {
        await save.mutateAsync({
          payerId: payer.id,
          body: {
            service_id: v.scope === "service" ? Number(v.service) : null,
            service_kind: v.scope === "kind" ? (v.service_kind as ServiceKind) : null,
            note: v.note,
          },
        });
        toast.success(t("common.saved"));
        onClose();
      }}
    >
      <RadioGroupField
        control={form.control}
        name="scope"
        label={t("payers.excluded")}
        options={[
          { value: "service", label: t("payers.serviceScope") },
          { value: "kind", label: t("payers.kindScope") },
        ]}
      />
      {scope === "kind" ? (
        <SelectField
          control={form.control}
          name="service_kind"
          label={t("catalog.kind")}
          options={SERVICE_KINDS.map((k) => ({ value: k, label: t(`kinds.${k}`) }))}
          required
        />
      ) : (
        <ExclusionServicePicker form={form} />
      )}
      <TextField control={form.control} name="note" label={t("payers.note")} />
    </FormDialog>
  );
}

function ExclusionServicePicker({ form }: { form: ReturnType<typeof useForm<ExclusionValues>> }) {
  const { t } = useTranslation("admin");
  const localName = useLocalName();
  const [q, setQ] = useState("");
  const services = useServices({ q: q || undefined, active: true });
  return (
    <div className="grid gap-2">
      <SearchInput label={t("catalog.search")} placeholder={t("catalog.search")} onSearch={setQ} />
      <SelectField
        control={form.control}
        name="service"
        label={t("prices.service")}
        options={(services.data?.items ?? []).map((s) => ({
          value: String(s.id),
          label: `${localName(s)} (${s.code})`,
        }))}
        required
      />
    </div>
  );
}
