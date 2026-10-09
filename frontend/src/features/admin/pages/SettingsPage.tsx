import { zodResolver } from "@hookform/resolvers/zod";
import type { ColumnDef } from "@tanstack/react-table";
import { ImageOff, Trash2, Upload } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DataTable } from "@/components/DataTable";
import { Form, RadioGroupField, SwitchField, TextareaField, TextField } from "@/components/form";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { UnsavedChangesGuard } from "@/components/UnsavedChangesGuard";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";
import { translateKey } from "@/lib/validation";

import {
  useCenterProfile,
  useDeleteLogo,
  usePrintTemplates,
  useSavePrintTemplate,
  useSequences,
  useUpdateCenterProfile,
  useUploadLogo,
} from "../api";
import { AdminPage, QueryState } from "../components/AdminPage";
import { useDiscardConfirm, useReportDirty } from "../components/DiscardConfirm";
import { Code } from "../components/FormDialog";
import type { CenterProfileOut, PrintTemplateOut, SequencesOut } from "../types";

type Tab = "center" | "print" | "numbering";

export function SettingsPage() {
  const { t } = useTranslation("admin");
  const canPrint = usePermission("core.manage_print_templates");
  const [tab, setTab] = useState<Tab>("center");
  // Only the shown tab is mounted: switching away from unsaved edits asks first.
  const [dirty, setDirty] = useState(false);
  const discard = useDiscardConfirm();
  return (
    <AdminPage section="settings" title={t("sections.settings.title")} description={t("sections.settings.description")}>
      <Tabs
        value={tab}
        onValueChange={(v) => {
          discard.ask(dirty, () => {
            setTab(v as Tab);
          });
        }}
      >
        <TabsList aria-label={t("sections.settings.title")}>
          <TabsTrigger value="center">{t("settings.centerTab")}</TabsTrigger>
          {canPrint ? <TabsTrigger value="print">{t("settings.printTab")}</TabsTrigger> : null}
          <TabsTrigger value="numbering">{t("settings.numberingTab")}</TabsTrigger>
        </TabsList>
        <TabsContent value="center">
          <CenterProfileCard onDirtyChange={setDirty} />
        </TabsContent>
        {canPrint ? (
          <TabsContent value="print">
            <PrintTemplatesCard onDirtyChange={setDirty} />
          </TabsContent>
        ) : null}
        <TabsContent value="numbering">
          <NumberingCard />
        </TabsContent>
      </Tabs>
      {discard.dialog}
    </AdminPage>
  );
}

// --- Center profile and logo --------------------------------------------------------------

const centerSchema = z.object({
  name_ar: z.string().max(200),
  name_en: z.string().max(200),
  address: z.string().max(300),
  phone: z.string().max(50),
  registration_no: z.string().max(100),
  tax_no: z.string().max(100),
  digits: z.enum(["latin", "arabic"]),
});
type CenterValues = z.infer<typeof centerSchema>;

function centerValues(profile: CenterProfileOut): CenterValues {
  return {
    name_ar: profile.name_ar,
    name_en: profile.name_en,
    address: profile.address,
    phone: profile.phone,
    registration_no: profile.registration_no,
    tax_no: profile.tax_no,
    digits: profile.digits,
  };
}

function CenterProfileCard({ onDirtyChange }: { onDirtyChange: (dirty: boolean) => void }) {
  const center = useCenterProfile();
  return (
    <QueryState loading={center.isPending} error={center.error} onRetry={() => void center.refetch()}>
      {center.data ? (
        // The card sits beside the app and admin navigation: the logo goes beside the form
        // only when the screen is wide enough for the form to keep its own columns.
        <div className="grid gap-4 2xl:grid-cols-[1fr_18rem]">
          <CenterForm profile={center.data} onDirtyChange={onDirtyChange} />
          <LogoCard profile={center.data} />
        </div>
      ) : null}
    </QueryState>
  );
}

function CenterForm({
  profile,
  onDirtyChange,
}: {
  profile: CenterProfileOut;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { t } = useTranslation(["admin", "errors"]);
  const save = useUpdateCenterProfile();
  const translateError = useTranslateError();
  const form = useForm<CenterValues>({ resolver: zodResolver(centerSchema), defaultValues: centerValues(profile) });
  useReportDirty(form.formState.isDirty, onDirtyChange);
  const submit = form.handleSubmit(async (values) => {
    const saved = await save.mutateAsync(values);
    form.reset(centerValues(saved));
    toast.success(t("admin:settings.saved"));
  });
  return (
    <section className="card-surface @container min-w-0 p-4 md:p-5" aria-labelledby="center-title">
      <h2 id="center-title" className="mb-4 font-semibold text-fg">
        {t("admin:settings.centerTitle")}
      </h2>
      <Form {...form}>
        <UnsavedChangesGuard when={form.formState.isDirty && !form.formState.isSubmitting} />
        <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
          {save.error ? (
            <AlertCard variant="danger" title={t("errors:title")} live>
              {translateError(save.error)}
            </AlertCard>
          ) : null}
          <div className="grid gap-4 @lg:grid-cols-2">
            <TextField control={form.control} name="name_ar" label={t("admin:settings.nameAr")} dir="rtl" />
            <TextField control={form.control} name="name_en" label={t("admin:settings.nameEn")} dir="ltr" />
          </div>
          <TextField control={form.control} name="address" label={t("admin:settings.address")} />
          <div className="grid gap-4 @lg:grid-cols-2 @3xl:grid-cols-3">
            <TextField control={form.control} name="phone" label={t("admin:settings.phone")} type="tel" dir="ltr" />
            <TextField
              control={form.control}
              name="registration_no"
              label={t("admin:settings.registrationNo")}
              dir="ltr"
            />
            <TextField control={form.control} name="tax_no" label={t("admin:settings.taxNo")} dir="ltr" />
          </div>
          <RadioGroupField
            control={form.control}
            name="digits"
            label={t("admin:settings.digits")}
            options={[
              { value: "latin", label: t("admin:settings.digitsLatin") },
              { value: "arabic", label: t("admin:settings.digitsArabic") },
            ]}
          />
          <div>
            <Button type="submit" loading={form.formState.isSubmitting} disabled={!form.formState.isDirty}>
              {t("admin:common.save")}
            </Button>
          </div>
        </form>
      </Form>
    </section>
  );
}

function LogoCard({ profile }: { profile: CenterProfileOut }) {
  const { t } = useTranslation("admin");
  const upload = useUploadLogo();
  const remove = useDeleteLogo();
  const translateError = useTranslateError();
  const input = useRef<HTMLInputElement>(null);
  const [confirmRemove, setConfirmRemove] = useState(false);
  return (
    <section className="card-surface flex flex-col gap-3 p-4 md:p-5" aria-labelledby="logo-title">
      <h2 id="logo-title" className="font-semibold text-fg">
        {t("settings.logo")}
      </h2>
      <div className="flex aspect-[3/2] w-full max-w-72 items-center justify-center overflow-hidden rounded-control border border-dashed border-border-strong bg-subtle">
        {profile.logo_url ? (
          <img src={profile.logo_url} alt={t("settings.logoAlt")} className="max-h-full max-w-full object-contain" />
        ) : (
          <span className="flex flex-col items-center gap-2 text-sm text-muted">
            <ImageOff className="size-6" aria-hidden="true" />
            {t("settings.noLogo")}
          </span>
        )}
      </div>
      <p className="text-xs text-muted">{t("settings.logoHint")}</p>
      <input
        ref={input}
        type="file"
        accept="image/png,image/jpeg,image/gif,image/webp"
        className="sr-only"
        // The visible button opens it: one "Upload logo" stop for keyboard and screen readers.
        tabIndex={-1}
        aria-hidden="true"
        data-testid="logo-input"
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (!file) return;
          upload.mutate(file, {
            onSuccess: () => toast.success(t("settings.logoSaved")),
            onError: (err) => toast.error(translateError(err)),
          });
        }}
      />
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" loading={upload.isPending} onClick={() => input.current?.click()}>
          <Upload />
          {t("settings.uploadLogo")}
        </Button>
        {profile.has_logo ? (
          <Button
            variant="destructive-soft"
            loading={remove.isPending}
            onClick={() => {
              setConfirmRemove(true);
            }}
          >
            <Trash2 />
            {t("settings.removeLogo")}
          </Button>
        ) : null}
      </div>
      <ConfirmDialog
        open={confirmRemove}
        onOpenChange={setConfirmRemove}
        title={t("settings.removeLogoTitle")}
        description={t("settings.removeLogoHint")}
        confirmLabel={t("settings.removeLogo")}
        destructive
        onConfirm={async () => {
          await remove.mutateAsync(undefined);
          toast.success(t("settings.logoRemoved"));
        }}
      />
    </section>
  );
}

// --- Print templates ----------------------------------------------------------------------

const DOCUMENTS = ["invoice", "receipt", "prescription", "lab_result", "claim_export", "shift_report"] as const;
const PAPERS = ["a4", "thermal_80"] as const;

const templateSchema = z.object({
  show_logo: z.boolean(),
  header_ar: z.string().max(1000),
  header_en: z.string().max(1000),
  footer_ar: z.string().max(1000),
  footer_en: z.string().max(1000),
  active: z.boolean(),
});
type TemplateValues = z.infer<typeof templateSchema>;

function PrintTemplatesCard({ onDirtyChange }: { onDirtyChange: (dirty: boolean) => void }) {
  const { t } = useTranslation("admin");
  const templates = usePrintTemplates();
  const [document, setDocument] = useState<PrintTemplateOut["document"]>("invoice");
  const [paper, setPaper] = useState<PrintTemplateOut["paper"]>("a4");
  // Another document or paper shows another form: unsaved texts of this one are asked about.
  const [dirty, setDirty] = useState(false);
  useReportDirty(dirty, onDirtyChange);
  const discard = useDiscardConfirm();
  const current = templates.data?.find((row) => row.document === document && row.paper === paper);
  return (
    <section className="card-surface flex flex-col gap-4 p-4 md:p-5" aria-labelledby="print-title">
      <div>
        <h2 id="print-title" className="font-semibold text-fg">
          {t("settings.printTitle")}
        </h2>
        <p className="text-sm text-muted">{t("settings.printHint")}</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="grid gap-1.5">
          <Label htmlFor="print-document">{t("settings.document")}</Label>
          <Select
            value={document}
            onValueChange={(v) => {
              discard.ask(dirty, () => {
                setDocument(v as PrintTemplateOut["document"]);
              });
            }}
          >
            <SelectTrigger id="print-document">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {DOCUMENTS.map((d) => (
                <SelectItem key={d} value={d}>
                  {t(`settings.documents.${d}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="print-paper">{t("settings.paper")}</Label>
          <Select
            value={paper}
            onValueChange={(v) => {
              discard.ask(dirty, () => {
                setPaper(v as PrintTemplateOut["paper"]);
              });
            }}
          >
            <SelectTrigger id="print-paper">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PAPERS.map((p) => (
                <SelectItem key={p} value={p}>
                  {t(`settings.papers.${p}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      <QueryState loading={templates.isPending} error={templates.error} onRetry={() => void templates.refetch()}>
        {current ? (
          <TemplateForm
            key={`${document}-${paper}-${current.updated_at ?? ""}`}
            template={current}
            onDirtyChange={setDirty}
          />
        ) : null}
      </QueryState>
      {discard.dialog}
    </section>
  );
}

function TemplateForm({
  template,
  onDirtyChange,
}: {
  template: PrintTemplateOut;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { t } = useTranslation(["admin", "errors"]);
  const save = useSavePrintTemplate();
  const translateError = useTranslateError();
  const form = useForm<TemplateValues>({
    resolver: zodResolver(templateSchema),
    defaultValues: {
      show_logo: template.show_logo,
      header_ar: template.header_ar,
      header_en: template.header_en,
      footer_ar: template.footer_ar,
      footer_en: template.footer_en,
      active: template.active,
    },
  });
  useReportDirty(form.formState.isDirty, onDirtyChange);
  const submit = form.handleSubmit(async (values) => {
    await save.mutateAsync({ document: template.document, paper: template.paper, body: values });
    form.reset(values);
    toast.success(t("admin:settings.saved"));
  });
  return (
    <Form {...form}>
      <UnsavedChangesGuard when={form.formState.isDirty && !form.formState.isSubmitting} />
      <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
        {save.error ? (
          <AlertCard variant="danger" title={t("errors:title")} live>
            {translateError(save.error)}
          </AlertCard>
        ) : null}
        {!template.saved ? <p className="text-xs text-muted">{t("admin:settings.defaults")}</p> : null}
        <div className="grid gap-4 md:grid-cols-2">
          <TextareaField control={form.control} name="header_ar" label={t("admin:settings.headerAr")} rows={2} />
          <TextareaField control={form.control} name="header_en" label={t("admin:settings.headerEn")} rows={2} />
          <TextareaField control={form.control} name="footer_ar" label={t("admin:settings.footerAr")} rows={2} />
          <TextareaField control={form.control} name="footer_en" label={t("admin:settings.footerEn")} rows={2} />
        </div>
        <div className="flex flex-col gap-3 sm:flex-row sm:gap-6">
          <SwitchField control={form.control} name="show_logo" label={t("admin:settings.showLogo")} />
          <SwitchField control={form.control} name="active" label={t("admin:common.active")} />
        </div>
        <div>
          <Button type="submit" loading={form.formState.isSubmitting}>
            {t("admin:common.save")}
          </Button>
        </div>
      </form>
    </Form>
  );
}

// --- Numbering ----------------------------------------------------------------------------

type SequenceRow = SequencesOut["items"][number];

function NumberingCard() {
  const { t } = useTranslation("admin");
  const { t: tAny } = useTranslation();
  const [chosen, setYear] = useState<number | undefined>(undefined);
  const sequences = useSequences(chosen);
  const years = sequences.data?.years ?? [];
  const year = chosen ?? sequences.data?.year;

  const columns = useMemo<ColumnDef<SequenceRow>[]>(
    () => [
      {
        id: "document",
        accessorFn: (row) => row.code,
        header: t("numbering.document"),
        meta: { label: t("numbering.document") },
        cell: ({ row }) => (
          <div className="min-w-0">
            <div className="font-medium text-fg">
              {translateKey(tAny, `admin:numbering.codes.${row.original.code}`, { defaultValue: row.original.code })}
            </div>
            <Code>{row.original.code}</Code>
          </div>
        ),
      },
      {
        id: "last",
        accessorFn: (row) => row.last_value,
        header: t("numbering.last"),
        meta: { label: t("numbering.last") },
        cell: ({ row }) =>
          row.original.last_number ? <Code>{row.original.last_number}</Code> : <span className="text-muted">—</span>,
      },
      {
        id: "next",
        accessorFn: (row) => row.next_number,
        header: t("numbering.next"),
        meta: { label: t("numbering.next") },
        cell: ({ row }) => <Code className="text-fg">{row.original.next_number}</Code>,
      },
    ],
    [t, tAny],
  );

  return (
    <section className="card-surface flex flex-col gap-4 p-4 md:p-5" aria-labelledby="numbering-title">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 id="numbering-title" className="font-semibold text-fg">
            {t("numbering.title")}
          </h2>
          <p className="text-sm text-muted">{t("numbering.hint")}</p>
        </div>
        <div className="grid gap-1.5 sm:w-40">
          <Label htmlFor="numbering-year">{t("numbering.year")}</Label>
          <Select
            value={year === undefined ? "" : String(year)}
            onValueChange={(v) => {
              setYear(Number(v));
            }}
          >
            <SelectTrigger id="numbering-year">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {years.map((y) => (
                <SelectItem key={y} value={String(y)}>
                  {y}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      <QueryState loading={sequences.isPending} error={sequences.error} onRetry={() => void sequences.refetch()}>
        <DataTable
          caption={t("numbering.title")}
          columns={columns}
          data={sequences.data?.items ?? []}
          getRowId={(row) => row.code}
          pageSize={25}
        />
      </QueryState>
    </section>
  );
}
