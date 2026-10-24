import { zodResolver } from "@hookform/resolvers/zod";
import { Link } from "@tanstack/react-router";
import { ExternalLink, Pencil, Plus } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { useForm, useWatch, type UseFormReturn } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import { DateText } from "@/components/DateText";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
  SwitchField,
  TextareaField,
  TextField,
} from "@/components/form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { UnsavedChangesGuard } from "@/components/UnsavedChangesGuard";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";
import { vmsg } from "@/lib/validation";
import { WEEK_ORDER, weekdayName } from "@/lib/weekdays";

import {
  useAnnouncements,
  useCenterPageSettings,
  useCenterProfile,
  useDepartments,
  useDoctors,
  useSaveAnnouncement,
  useUpdateCenterPage,
} from "../api";
import { AdminPage, QueryState } from "../components/AdminPage";
import { DateField } from "../components/DateField";
import { FormDialog } from "../components/FormDialog";
import { centerDate, CLOCK_TIME, normalizeClockTime } from "../dates";
import type { AnnouncementOut, CenterPageOut } from "../types";

/**
 * The public center page of the patient portal (/portal): fixed sections, not a page builder.
 * Name, logo, address and the main phone come from the center settings; departments and
 * doctors with their clinic days from the departments screen. Here: a short text, opening
 * hours, WhatsApp and e-mail, directions, which sections show, what to keep off the page, and
 * the notices.
 */
export function CenterPageSettingsPage() {
  const { t } = useTranslation("admin");
  return (
    <AdminPage
      section="centerPage"
      title={t("sections.centerPage.title")}
      description={t("sections.centerPage.description")}
      actions={
        <Button asChild variant="outline">
          <a href="/portal" target="_blank" rel="noopener" data-testid="center-page-preview">
            {t("centerPage.preview")}
            <ExternalLink aria-hidden="true" />
          </a>
        </Button>
      }
    >
      <PageSettings />
      <Announcements />
    </AdminPage>
  );
}

// --- The page's sections -----------------------------------------------------------------

const optionalClock = z.string().trim();

const daySchema = z
  .object({ weekday: z.number(), open: z.boolean(), opens: optionalClock, closes: optionalClock })
  .superRefine((day, ctx) => {
    if (!day.open) return;
    if (!CLOCK_TIME.test(day.opens))
      ctx.addIssue({ code: "custom", path: ["opens"], message: vmsg("admin:centerPage.timeRule") });
    if (!CLOCK_TIME.test(day.closes))
      ctx.addIssue({ code: "custom", path: ["closes"], message: vmsg("admin:centerPage.timeRule") });
    else if (CLOCK_TIME.test(day.opens) && day.closes <= day.opens) {
      ctx.addIssue({ code: "custom", path: ["closes"], message: vmsg("admin:centerPage.closesAfter") });
    }
  });

const pageSchema = z.object({
  about_ar: z.string().max(600),
  about_en: z.string().max(600),
  hoursSet: z.boolean(),
  hours: z.array(daySchema).length(7),
  whatsapp: z.string().trim().max(30),
  email: z.union([z.literal(""), z.email(vmsg("admin:centerPage.emailRule")).max(120)]),
  directions_ar: z.string().max(400),
  directions_en: z.string().max(400),
  show_about: z.boolean(),
  show_hours: z.boolean(),
  show_departments: z.boolean(),
  show_doctors: z.boolean(),
  show_announcements: z.boolean(),
  show_contact: z.boolean(),
  show_address: z.boolean(),
  hidden_department_ids: z.array(z.number()),
  hidden_doctor_ids: z.array(z.number()),
});
type PageValues = z.infer<typeof pageSchema>;

/** Saturday to Thursday 08:00-16:00 and Friday closed: a starting point, saved only on purpose. */
const DEFAULT_DAY = { opens: "08:00", closes: "16:00" };

function pageValues(page: CenterPageOut): PageValues {
  const byDay = new Map(page.hours.map((h) => [h.weekday, h]));
  return {
    about_ar: page.about_ar,
    about_en: page.about_en,
    hoursSet: page.hours.length > 0,
    hours: Array.from({ length: 7 }, (_, weekday) => {
      const day = byDay.get(weekday);
      if (!day) return { weekday, open: weekday !== 4, ...DEFAULT_DAY };
      return {
        weekday,
        open: !day.closed,
        opens: day.opens ?? DEFAULT_DAY.opens,
        closes: day.closes ?? DEFAULT_DAY.closes,
      };
    }),
    whatsapp: page.whatsapp ? `+${page.whatsapp}` : "",
    email: page.email,
    directions_ar: page.directions_ar,
    directions_en: page.directions_en,
    show_about: page.show_about,
    show_hours: page.show_hours,
    show_departments: page.show_departments,
    show_doctors: page.show_doctors,
    show_announcements: page.show_announcements,
    show_contact: page.show_contact,
    show_address: page.show_address,
    hidden_department_ids: page.hidden_department_ids,
    hidden_doctor_ids: page.hidden_doctor_ids,
  };
}

function PageSettings() {
  const page = useCenterPageSettings();
  return (
    <QueryState loading={page.isPending} error={page.error} onRetry={() => void page.refetch()}>
      {page.data ? <PageForm key={page.data.updated_at ?? "new"} page={page.data} /> : null}
    </QueryState>
  );
}

/** One section of the page: its title, its visibility switch, then its fields. */
function SectionCard({
  title,
  hint,
  toggle,
  children,
  testId,
}: {
  title: string;
  hint?: string;
  toggle?: ReactNode;
  children?: ReactNode;
  testId?: string;
}) {
  const id = `center-page-${testId ?? title}`;
  return (
    <section
      className="card-surface flex min-w-0 flex-col gap-4 p-4 md:p-(--d-card-pad)"
      aria-labelledby={id}
      data-testid={testId}
    >
      <div>
        <h2 id={id} className="font-semibold text-fg">
          {title}
        </h2>
        {hint ? <p className="mt-1 text-sm text-muted">{hint}</p> : null}
      </div>
      {toggle}
      {children}
    </section>
  );
}

function PageForm({ page }: { page: CenterPageOut }) {
  const { t } = useTranslation(["admin", "errors"]);
  const translateError = useTranslateError();
  const save = useUpdateCenterPage();
  const form = useForm<PageValues>({ resolver: zodResolver(pageSchema), defaultValues: pageValues(page) });
  const submit = form.handleSubmit(async ({ hoursSet, hours, ...rest }) => {
    await save.mutateAsync({
      ...rest,
      hours: hoursSet
        ? hours.map((d) =>
            d.open
              ? { weekday: d.weekday, closed: false, opens: d.opens, closes: d.closes }
              : { weekday: d.weekday, closed: true },
          )
        : [],
    });
    toast.success(t("admin:centerPage.saved"));
  });
  const toggle = (name: keyof PageValues & `show_${string}`) => (
    <SwitchField control={form.control} name={name} label={t("admin:centerPage.showSection")} />
  );

  return (
    <Form {...form}>
      <UnsavedChangesGuard when={form.formState.isDirty && !form.formState.isSubmitting} />
      <form onSubmit={(e) => void submit(e)} noValidate className="grid min-w-0 gap-4" data-testid="center-page-form">
        {save.error ? (
          <AlertCard variant="danger" title={t("errors:title")} live>
            {translateError(save.error)}
          </AlertCard>
        ) : null}
        <IdentityNote />
        <SectionCard
          title={t("admin:centerPage.about")}
          hint={t("admin:centerPage.aboutHint")}
          toggle={toggle("show_about")}
          testId="section-about"
        >
          <div className="grid gap-4 md:grid-cols-2">
            <TextareaField
              control={form.control}
              name="about_ar"
              label={t("admin:centerPage.textAr")}
              dir="rtl"
              rows={3}
            />
            <TextareaField
              control={form.control}
              name="about_en"
              label={t("admin:centerPage.textEn")}
              dir="ltr"
              rows={3}
            />
          </div>
        </SectionCard>
        <SectionCard
          title={t("admin:centerPage.hours")}
          hint={t("admin:centerPage.hoursHint")}
          toggle={toggle("show_hours")}
          testId="section-hours"
        >
          <HoursEditor form={form} />
        </SectionCard>
        <SectionCard
          title={t("admin:centerPage.contact")}
          hint={t("admin:centerPage.contactHint")}
          toggle={toggle("show_contact")}
          testId="section-contact"
        >
          <div className="grid gap-4 md:grid-cols-2">
            <TextField
              control={form.control}
              name="whatsapp"
              label={t("admin:centerPage.whatsapp")}
              description={t("admin:centerPage.whatsappHint")}
              type="tel"
              inputMode="tel"
              dir="ltr"
              optional
            />
            <TextField
              control={form.control}
              name="email"
              label={t("admin:centerPage.email")}
              type="email"
              dir="ltr"
              optional
            />
          </div>
        </SectionCard>
        <SectionCard
          title={t("admin:centerPage.address")}
          hint={t("admin:centerPage.addressHint")}
          toggle={toggle("show_address")}
          testId="section-address"
        >
          <div className="grid gap-4 md:grid-cols-2">
            <TextareaField
              control={form.control}
              name="directions_ar"
              label={t("admin:centerPage.directionsAr")}
              dir="rtl"
              rows={2}
            />
            <TextareaField
              control={form.control}
              name="directions_en"
              label={t("admin:centerPage.directionsEn")}
              dir="ltr"
              rows={2}
            />
          </div>
        </SectionCard>
        <SectionCard
          title={t("admin:centerPage.departments")}
          hint={t("admin:centerPage.departmentsHint")}
          toggle={toggle("show_departments")}
          testId="section-departments"
        >
          <DepartmentChoices form={form} />
        </SectionCard>
        <SectionCard
          title={t("admin:centerPage.doctors")}
          hint={t("admin:centerPage.doctorsHint")}
          toggle={toggle("show_doctors")}
          testId="section-doctors"
        >
          <DoctorChoices form={form} />
        </SectionCard>
        <SectionCard
          title={t("admin:centerPage.announcementsSection")}
          hint={t("admin:centerPage.announcementsSectionHint")}
          toggle={toggle("show_announcements")}
          testId="section-announcements"
        />
        <div>
          <Button type="submit" loading={form.formState.isSubmitting} disabled={!form.formState.isDirty}>
            {t("admin:centerPage.save")}
          </Button>
        </div>
      </form>
    </Form>
  );
}

/** What the page takes from the center settings, with a link there to change it. */
function IdentityNote() {
  const { t } = useTranslation("admin");
  const profile = useCenterProfile();
  const language = useLanguage();
  const name = profile.data ? pickName({ ar: profile.data.name_ar, en: profile.data.name_en }, language) : "";
  const address = profile.data?.address ?? "";
  return (
    <SectionCard title={t("centerPage.identity")} hint={t("centerPage.identityHint")} testId="section-identity">
      <dl className="grid gap-2 text-sm sm:grid-cols-[auto_1fr] sm:gap-x-6">
        <dt className="text-muted">{t("centerPage.name")}</dt>
        <dd className="min-w-0 break-words text-fg">{name || "—"}</dd>
        <dt className="text-muted">{t("settings.address")}</dt>
        <dd className="min-w-0 break-words text-fg">{address === "" ? "—" : address}</dd>
        <dt className="text-muted">{t("settings.phone")}</dt>
        <dd className="min-w-0 text-fg">
          {profile.data?.phone ? <span className="num">{profile.data.phone}</span> : "—"}
        </dd>
      </dl>
      <Link
        to="/administration/settings"
        className="w-fit text-sm font-medium text-primary-strong underline-offset-4 hover:underline"
      >
        {t("centerPage.editIdentity")}
      </Link>
    </SectionCard>
  );
}

function HoursEditor({ form }: { form: UseFormReturn<PageValues> }) {
  const { t } = useTranslation("admin");
  const language = useLanguage();
  const hoursSet = useWatch({ control: form.control, name: "hoursSet" });
  const days = useWatch({ control: form.control, name: "hours" });
  if (!hoursSet) {
    return (
      <div className="flex flex-col items-start gap-2">
        <p className="text-sm text-muted">{t("centerPage.noHours")}</p>
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            form.setValue("hoursSet", true, { shouldDirty: true });
          }}
        >
          <Plus aria-hidden="true" />
          {t("centerPage.addHours")}
        </Button>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <ul className="flex flex-col divide-y divide-border" data-testid="hours-editor">
        {WEEK_ORDER.map((weekday) => {
          const open = days[weekday]?.open ?? false;
          return (
            <li
              key={weekday}
              className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-2 py-3 sm:grid-cols-[8rem_auto_1fr]"
            >
              <span className="text-sm font-medium text-fg">{weekdayName(weekday, language)}</span>
              <FormField
                control={form.control}
                name={`hours.${weekday}.open`}
                render={({ field }) => (
                  <FormItem className="flex flex-row items-center gap-2">
                    <FormControl>
                      <Switch checked={field.value} onCheckedChange={field.onChange} ref={field.ref} />
                    </FormControl>
                    <FormLabel className="font-normal">
                      {field.value ? t("centerPage.open") : t("centerPage.closed")}
                    </FormLabel>
                  </FormItem>
                )}
              />
              {open ? (
                <div className="col-span-2 grid grid-cols-2 gap-3 sm:col-span-1">
                  <ClockField form={form} name={`hours.${weekday}.opens`} label={t("centerPage.opens")} />
                  <ClockField form={form} name={`hours.${weekday}.closes`} label={t("centerPage.closes")} />
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
      <Button
        type="button"
        variant="ghost"
        className="w-fit"
        onClick={() => {
          form.setValue("hoursSet", false, { shouldDirty: true });
        }}
      >
        {t("centerPage.removeHours")}
      </Button>
    </div>
  );
}

function ClockField({
  form,
  name,
  label,
}: {
  form: UseFormReturn<PageValues>;
  name: `hours.${number}.opens` | `hours.${number}.closes`;
  label: string;
}) {
  return (
    <FormField
      control={form.control}
      name={name}
      render={({ field }) => (
        <FormItem className="min-w-0">
          <FormLabel className="text-xs">{label}</FormLabel>
          <FormControl>
            {/* 24-hour HH:MM text, as the schedule editor: a native time input follows the browser's AM/PM. */}
            <Input
              {...field}
              onChange={(e) => {
                field.onChange(normalizeClockTime(e.target.value));
              }}
              inputMode="numeric"
              autoComplete="off"
              maxLength={5}
              placeholder="08:00"
              dir="ltr"
              className="min-w-0 tabular"
            />
          </FormControl>
          <FormMessage />
        </FormItem>
      )}
    />
  );
}

/** A list of checkboxes "shown on the page", stored as the ids kept off it. */
function ShownChoices({
  form,
  name,
  items,
}: {
  form: UseFormReturn<PageValues>;
  name: "hidden_department_ids" | "hidden_doctor_ids";
  items: { id: number; label: string; detail?: string }[];
}) {
  const hidden = useWatch({ control: form.control, name });
  if (items.length === 0) return null;
  return (
    <ul className="grid gap-2 sm:grid-cols-2">
      {items.map((item) => {
        const id = `${name}-${String(item.id)}`;
        return (
          <li key={item.id} className="flex items-start gap-3">
            <Checkbox
              id={id}
              checked={!hidden.includes(item.id)}
              className="mt-0.5"
              onCheckedChange={(checked) => {
                const next = checked === true ? hidden.filter((h) => h !== item.id) : [...hidden, item.id];
                form.setValue(name, next, { shouldDirty: true });
              }}
            />
            <label htmlFor={id} className="min-w-0 text-sm leading-snug text-fg">
              {item.label}
              {item.detail ? <span className="block text-xs text-muted">{item.detail}</span> : null}
            </label>
          </li>
        );
      })}
    </ul>
  );
}

function DepartmentChoices({ form }: { form: UseFormReturn<PageValues> }) {
  const { t } = useTranslation("admin");
  const canRead = usePermission("catalog.view");
  const departments = useDepartments();
  const language = useLanguage();
  if (!canRead) return <p className="text-sm text-muted">{t("centerPage.listNotAllowed")}</p>;
  const items = (departments.data ?? [])
    .filter((d) => d.active)
    .map((d) => ({ id: d.id, label: pickName({ ar: d.name_ar, en: d.name_en }, language) }));
  return (
    <QueryState loading={departments.isPending} error={departments.error} rows={2}>
      <ShownChoices form={form} name="hidden_department_ids" items={items} />
    </QueryState>
  );
}

function DoctorChoices({ form }: { form: UseFormReturn<PageValues> }) {
  const { t } = useTranslation("admin");
  const canRead = usePermission("core.manage_departments");
  const doctors = useDoctors();
  const language = useLanguage();
  if (!canRead) return <p className="text-sm text-muted">{t("centerPage.listNotAllowed")}</p>;
  const items = (doctors.data ?? [])
    .filter((d) => d.active)
    .map((d) => ({
      id: d.id,
      label: pickName({ ar: d.full_name_ar, en: d.full_name_en }, language),
      detail: pickName({ ar: d.specialty_ar, en: d.specialty_en }, language),
    }));
  return (
    <QueryState loading={doctors.isPending} error={doctors.error} rows={2}>
      <ShownChoices form={form} name="hidden_doctor_ids" items={items} />
    </QueryState>
  );
}

// --- Notices ------------------------------------------------------------------------------

type NoticeState = "shown" | "scheduled" | "ended" | "hidden";

function noticeState(row: AnnouncementOut): NoticeState {
  if (!row.active) return "hidden";
  if (row.shown_today) return "shown";
  // Active but not shown today (the server's answer): before its start, or after its end.
  return row.starts_on && row.starts_on > centerDate() ? "scheduled" : "ended";
}

function Announcements() {
  const { t } = useTranslation("admin");
  const list = useAnnouncements();
  const language = useLanguage();
  const [editing, setEditing] = useState<AnnouncementOut | "new" | null>(null);
  return (
    <section
      className="card-surface flex min-w-0 flex-col gap-4 p-4 md:p-(--d-card-pad)"
      aria-labelledby="notices-title"
      data-testid="announcements"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="notices-title" className="font-semibold text-fg">
            {t("centerPage.announcements")}
          </h2>
          <p className="mt-1 text-sm text-muted">{t("centerPage.announcementsHint")}</p>
        </div>
        <Button
          variant="outline"
          onClick={() => {
            setEditing("new");
          }}
          data-testid="announcement-add"
        >
          <Plus aria-hidden="true" />
          {t("centerPage.addAnnouncement")}
        </Button>
      </div>
      <QueryState loading={list.isPending} error={list.error} onRetry={() => void list.refetch()} rows={2}>
        {list.data && list.data.length > 0 ? (
          <ul className="flex flex-col divide-y divide-border">
            {list.data.map((row) => {
              const state = noticeState(row);
              return (
                <li key={row.id} className="flex items-start justify-between gap-3 py-3" data-testid="announcement-row">
                  <div className="min-w-0">
                    <p className="text-sm font-medium break-words text-fg">
                      {pickName({ ar: row.title_ar, en: row.title_en }, language)}
                    </p>
                    <p className="mt-0.5 text-xs text-muted">
                      {row.starts_on ? <DateText value={row.starts_on} /> : t("centerPage.fromNow")}
                      {" – "}
                      {row.ends_on ? <DateText value={row.ends_on} /> : t("centerPage.noEnd")}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    <Badge variant={state === "shown" ? "success" : state === "scheduled" ? "pending" : "neutral"}>
                      {t(`centerPage.state.${state}`)}
                    </Badge>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={t("centerPage.editAnnouncement")}
                      onClick={() => {
                        setEditing(row);
                      }}
                    >
                      <Pencil aria-hidden="true" />
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="text-sm text-muted">{t("centerPage.noAnnouncements")}</p>
        )}
      </QueryState>
      {editing !== null ? (
        <AnnouncementDialog
          row={editing === "new" ? null : editing}
          onClose={() => {
            setEditing(null);
          }}
        />
      ) : null}
    </section>
  );
}

const noticeSchema = z
  .object({
    title_ar: z.string().trim().max(120),
    title_en: z.string().trim().max(120),
    body_ar: z.string().max(600),
    body_en: z.string().max(600),
    starts_on: z.string(),
    ends_on: z.string(),
    active: z.boolean(),
  })
  .superRefine((v, ctx) => {
    if (!v.title_ar && !v.title_en) {
      ctx.addIssue({ code: "custom", path: ["title_ar"], message: vmsg("admin:centerPage.titleRule") });
    }
    if (v.starts_on && v.ends_on && v.ends_on < v.starts_on) {
      ctx.addIssue({ code: "custom", path: ["ends_on"], message: vmsg("admin:centerPage.datesRule") });
    }
  });
type NoticeValues = z.infer<typeof noticeSchema>;

function AnnouncementDialog({ row, onClose }: { row: AnnouncementOut | null; onClose: () => void }) {
  const { t } = useTranslation("admin");
  const save = useSaveAnnouncement();
  const defaults = useMemo<NoticeValues>(
    () => ({
      title_ar: row?.title_ar ?? "",
      title_en: row?.title_en ?? "",
      body_ar: row?.body_ar ?? "",
      body_en: row?.body_en ?? "",
      starts_on: row?.starts_on ?? "",
      ends_on: row?.ends_on ?? "",
      active: row?.active ?? true,
    }),
    [row],
  );
  const form = useForm<NoticeValues>({ resolver: zodResolver(noticeSchema), defaultValues: defaults });
  return (
    <FormDialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={row ? t("centerPage.editAnnouncement") : t("centerPage.addAnnouncement")}
      description={t("centerPage.announcementsHint")}
      form={form}
      error={save.error}
      wide
      submitLabel={t("centerPage.saveAnnouncement")}
      onSubmit={async ({ starts_on, ends_on, ...rest }) => {
        const body = { ...rest, starts_on: starts_on || null, ends_on: ends_on || null };
        await save.mutateAsync(row ? { id: row.id, body } : { body });
        toast.success(t("centerPage.announcementSaved"));
        onClose();
      }}
    >
      <div className="grid gap-4 md:grid-cols-2">
        <TextField control={form.control} name="title_ar" label={t("centerPage.titleAr")} dir="rtl" />
        <TextField control={form.control} name="title_en" label={t("centerPage.titleEn")} dir="ltr" />
        <TextareaField control={form.control} name="body_ar" label={t("centerPage.bodyAr")} dir="rtl" rows={3} />
        <TextareaField control={form.control} name="body_en" label={t("centerPage.bodyEn")} dir="ltr" rows={3} />
        <DateField
          control={form.control}
          name="starts_on"
          label={t("centerPage.startsOn")}
          description={t("centerPage.startsOnHint")}
        />
        <DateField
          control={form.control}
          name="ends_on"
          label={t("centerPage.endsOn")}
          description={t("centerPage.endsOnHint")}
        />
      </div>
      <SwitchField
        control={form.control}
        name="active"
        label={t("centerPage.activeLabel")}
        description={t("centerPage.activeHint")}
      />
    </FormDialog>
  );
}
