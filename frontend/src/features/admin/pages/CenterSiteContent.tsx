/**
 * The website content kept outside the center page form (ADR 0029 H): images, doctors' website
 * profiles, questions and answers, testimonials, and the insurer and service names shown on the
 * page. Each saves on its own; every call needs `core.manage_public_site`, and approving a
 * testimonial needs `core.approve_testimonial` (the button is hidden without it; the server
 * refuses it either way). Prices never appear here or on the page.
 */
import { zodResolver } from "@hookform/resolvers/zod";
import { Check, Eye, EyeOff, ImagePlus, Pencil, Plus, Trash2 } from "lucide-react";
import { useMemo, useRef, useState, type ReactNode } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { z } from "zod";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { SelectField, SwitchField, TextareaField, TextField } from "@/components/form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";
import { vmsg } from "@/lib/validation";

import {
  useApproveTestimonial,
  useCenterFaq,
  useCenterMedia,
  useDeleteCenterFaq,
  useDeleteCenterMedia,
  useDeleteTestimonial,
  useDoctorSiteProfiles,
  useSaveCenterFaq,
  useSaveTestimonial,
  useSetPayerOnSite,
  useSetServiceOnSite,
  useSitePayers,
  useSiteServices,
  useTestimonials,
  useUpdateCenterMedia,
  useUpdateDoctorSiteProfile,
  useUploadCenterMedia,
} from "../api";
import { QueryState } from "../components/AdminPage";
import { FormDialog } from "../components/FormDialog";
import type { CenterFaqOut, DoctorSiteProfileOut, MediaKind, TestimonialOut } from "../types";

const KINDS: MediaKind[] = ["hero", "gallery", "doctor"];
/** Service kinds a visitor looks for by name; drugs, consumables and beds stay off the list. */
const SITE_SERVICE_KINDS = new Set(["consultation", "lab", "procedure"]);

function ContentCard({
  title,
  hint,
  action,
  testId,
  children,
}: {
  title: string;
  hint: string;
  action?: ReactNode;
  testId: string;
  children: ReactNode;
}) {
  const id = `${testId}-title`;
  return (
    <section
      className="card-surface flex min-w-0 flex-col gap-4 p-4 md:p-(--d-card-pad)"
      aria-labelledby={id}
      data-testid={testId}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id={id} className="font-semibold text-fg">
            {title}
          </h2>
          <p className="mt-1 text-sm text-muted">{hint}</p>
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

// --- Images -------------------------------------------------------------------------------

export function CenterImages() {
  const { t } = useTranslation("admin");
  const list = useCenterMedia();
  const update = useUpdateCenterMedia();
  const remove = useDeleteCenterMedia();
  const translateError = useTranslateError();
  const language = useLanguage();
  const [uploading, setUploading] = useState(false);
  const [removing, setRemoving] = useState<number | null>(null);
  return (
    <ContentCard
      title={t("centerPage.media.title")}
      hint={t("centerPage.media.hint")}
      testId="center-images"
      action={
        <Button
          variant="outline"
          onClick={() => {
            setUploading(true);
          }}
          data-testid="media-add"
        >
          <ImagePlus aria-hidden="true" />
          {t("centerPage.media.upload")}
        </Button>
      }
    >
      <QueryState loading={list.isPending} error={list.error} onRetry={() => void list.refetch()} rows={2}>
        {list.data && list.data.length > 0 ? (
          <ul className="grid gap-3 sm:grid-cols-2" data-testid="media-list">
            {list.data.map((row) => (
              <li
                key={row.id}
                className="flex min-w-0 gap-3 rounded-control border border-border p-2"
                data-testid="media-row"
              >
                <img
                  src={row.url}
                  alt={pickName({ ar: row.alt_ar, en: row.alt_en }, language)}
                  width={row.width}
                  height={row.height}
                  loading="lazy"
                  className="size-20 shrink-0 rounded-control bg-subtle object-cover"
                />
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                  <div className="flex flex-wrap items-center gap-1">
                    <Badge variant="soft">{t(`centerPage.media.kind.${row.kind}`)}</Badge>
                    {row.active ? null : <Badge variant="neutral">{t("centerPage.media.hidden")}</Badge>}
                  </div>
                  <p className="truncate text-sm text-fg">
                    {pickName({ ar: row.alt_ar, en: row.alt_en }, language) || "—"}
                  </p>
                  <p className="tabular text-xs text-muted">
                    {t("centerPage.media.size", { width: row.width, height: row.height })}
                  </p>
                  <div className="flex flex-wrap gap-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      loading={update.isPending && update.variables.id === row.id}
                      onClick={() => {
                        update.mutate(
                          { id: row.id, body: { active: !row.active } },
                          {
                            onSuccess: () => toast.success(t("centerPage.media.saved")),
                            onError: (err) => toast.error(translateError(err)),
                          },
                        );
                      }}
                    >
                      {row.active ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}
                      {row.active ? t("centerPage.media.hide") : t("centerPage.media.show")}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setRemoving(row.id);
                      }}
                    >
                      <Trash2 aria-hidden="true" />
                      {t("centerPage.media.remove")}
                    </Button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">{t("centerPage.media.none")}</p>
        )}
      </QueryState>
      {uploading ? (
        <UploadDialog
          onClose={() => {
            setUploading(false);
          }}
        />
      ) : null}
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => {
          if (!open) setRemoving(null);
        }}
        title={t("centerPage.media.remove")}
        description={t("centerPage.media.removeConfirm")}
        confirmLabel={t("centerPage.media.remove")}
        destructive
        onConfirm={async () => {
          if (removing === null) return;
          await remove.mutateAsync(removing);
          toast.success(t("centerPage.media.removed"));
          setRemoving(null);
        }}
      />
    </ContentCard>
  );
}

const uploadSchema = z.object({
  kind: z.enum(["hero", "gallery", "doctor"]),
  alt_ar: z.string().trim().max(200),
  alt_en: z.string().trim().max(200),
});
type UploadValues = z.infer<typeof uploadSchema>;

/** 2 MB: the server refuses more (MEDIA_TOO_LARGE); checked here too so nothing large is sent. */
const MAX_BYTES = 2 * 1024 * 1024;

function UploadDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation(["admin", "errors"]);
  const upload = useUploadCenterMedia();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const form = useForm<UploadValues>({
    resolver: zodResolver(uploadSchema),
    defaultValues: { kind: "gallery", alt_ar: "", alt_en: "" },
  });
  return (
    <FormDialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={t("admin:centerPage.media.upload")}
      description={t("admin:centerPage.media.hint")}
      form={form}
      error={upload.error}
      submitLabel={t("admin:centerPage.media.upload")}
      onSubmit={async (values) => {
        if (!file) {
          setFileError(t("errors:MEDIA_INVALID_IMAGE"));
          return;
        }
        if (file.size > MAX_BYTES) {
          setFileError(t("errors:MEDIA_TOO_LARGE"));
          return;
        }
        await upload.mutateAsync({ file, ...values });
        toast.success(t("admin:centerPage.media.uploaded"));
        onClose();
      }}
    >
      <div className="flex flex-col gap-2">
        <Label htmlFor="center-media-file">{t("admin:centerPage.media.file")}</Label>
        <input
          ref={input}
          id="center-media-file"
          type="file"
          accept="image/png,image/jpeg,image/webp"
          data-testid="media-input"
          aria-invalid={fileError ? true : undefined}
          aria-describedby={fileError ? "center-media-file-error" : undefined}
          className="block w-full min-w-0 text-sm text-fg file:me-3 file:rounded-control file:border file:border-border file:bg-surface file:px-3 file:py-2 file:text-sm file:font-medium file:text-fg"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            setFileError(null);
          }}
        />
        {fileError ? (
          <p id="center-media-file-error" className="text-sm text-danger-fg" role="alert">
            {fileError}
          </p>
        ) : null}
      </div>
      <SelectField
        control={form.control}
        name="kind"
        label={t("admin:centerPage.media.kindLabel")}
        options={KINDS.map((k) => ({ value: k, label: t(`admin:centerPage.media.kind.${k}`) }))}
      />
      <div className="grid gap-4 md:grid-cols-2">
        <TextField
          control={form.control}
          name="alt_ar"
          label={t("admin:centerPage.media.altAr")}
          description={t("admin:centerPage.media.altHint")}
          dir="rtl"
          optional
        />
        <TextField control={form.control} name="alt_en" label={t("admin:centerPage.media.altEn")} dir="ltr" optional />
      </div>
    </FormDialog>
  );
}

// --- Doctors on the website ---------------------------------------------------------------

export function CenterDoctorProfiles() {
  const { t } = useTranslation("admin");
  const doctors = useDoctorSiteProfiles();
  const language = useLanguage();
  const [editing, setEditing] = useState<DoctorSiteProfileOut | null>(null);
  return (
    <ContentCard
      title={t("centerPage.doctorProfiles.title")}
      hint={t("centerPage.doctorProfiles.hint")}
      testId="doctor-profiles"
    >
      <QueryState loading={doctors.isPending} error={doctors.error} onRetry={() => void doctors.refetch()} rows={2}>
        {doctors.data && doctors.data.length > 0 ? (
          <ul className="flex flex-col divide-y divide-border">
            {doctors.data
              .filter((d) => d.active)
              .map((d) => {
                const filled = Boolean(
                  d.qualifications_ar || d.qualifications_en || d.bio_ar || d.bio_en || d.photo_id,
                );
                return (
                  <li
                    key={d.id}
                    className="flex items-center justify-between gap-3 py-3"
                    data-testid="doctor-profile-row"
                  >
                    <div className="min-w-0">
                      <p className="text-sm font-medium break-words text-fg">
                        {pickName({ ar: d.name_ar, en: d.name_en }, language)}
                      </p>
                      <p className="text-xs text-muted">
                        {pickName({ ar: d.specialty_ar, en: d.specialty_en }, language) ||
                          pickName({ ar: d.department_ar, en: d.department_en }, language)}
                      </p>
                    </div>
                    <div className="flex shrink-0 flex-wrap items-center justify-end gap-1">
                      {d.online_bookable ? (
                        <Badge variant="info" data-testid="doctor-online-bookable">
                          {t("centerPage.doctorProfiles.bookableBadge")}
                        </Badge>
                      ) : null}
                      <Badge variant={filled ? "success" : "neutral"}>
                        {filled ? t("centerPage.doctorProfiles.complete") : t("centerPage.doctorProfiles.incomplete")}
                      </Badge>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label={`${t("centerPage.doctorProfiles.edit")}: ${pickName({ ar: d.name_ar, en: d.name_en }, language)}`}
                        onClick={() => {
                          setEditing(d);
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
          <p className="text-sm text-muted">{t("centerPage.doctorProfiles.none")}</p>
        )}
      </QueryState>
      {editing ? (
        <DoctorProfileDialog
          doctor={editing}
          onClose={() => {
            setEditing(null);
          }}
        />
      ) : null}
    </ContentCard>
  );
}

const doctorSchema = z.object({
  qualifications_ar: z.string().trim().max(200),
  qualifications_en: z.string().trim().max(200),
  bio_ar: z.string().trim().max(400),
  bio_en: z.string().trim().max(400),
  photo: z.string(),
  online_bookable: z.boolean(),
});
type DoctorValues = z.infer<typeof doctorSchema>;

function DoctorProfileDialog({ doctor, onClose }: { doctor: DoctorSiteProfileOut; onClose: () => void }) {
  const { t } = useTranslation("admin");
  const save = useUpdateDoctorSiteProfile();
  const media = useCenterMedia();
  const language = useLanguage();
  const photos = (media.data ?? []).filter((m) => m.kind === "doctor");
  const form = useForm<DoctorValues>({
    resolver: zodResolver(doctorSchema),
    defaultValues: {
      qualifications_ar: doctor.qualifications_ar,
      qualifications_en: doctor.qualifications_en,
      bio_ar: doctor.bio_ar,
      bio_en: doctor.bio_en,
      photo: doctor.photo_id === null ? "none" : String(doctor.photo_id),
      online_bookable: doctor.online_bookable,
    },
  });
  return (
    <FormDialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={pickName({ ar: doctor.name_ar, en: doctor.name_en }, language)}
      description={t("centerPage.doctorProfiles.hint")}
      form={form}
      error={save.error}
      wide
      submitLabel={t("centerPage.doctorProfiles.save")}
      onSubmit={async ({ photo, ...rest }) => {
        await save.mutateAsync({
          id: doctor.id,
          body: { ...rest, photo_id: photo === "none" ? null : Number(photo) },
        });
        toast.success(t("centerPage.doctorProfiles.saved"));
        onClose();
      }}
    >
      <div className="grid gap-4 md:grid-cols-2">
        <TextField
          control={form.control}
          name="qualifications_ar"
          label={t("centerPage.doctorProfiles.qualificationsAr")}
          dir="rtl"
          optional
        />
        <TextField
          control={form.control}
          name="qualifications_en"
          label={t("centerPage.doctorProfiles.qualificationsEn")}
          dir="ltr"
          optional
        />
        <TextareaField
          control={form.control}
          name="bio_ar"
          label={t("centerPage.doctorProfiles.bioAr")}
          dir="rtl"
          rows={3}
        />
        <TextareaField
          control={form.control}
          name="bio_en"
          label={t("centerPage.doctorProfiles.bioEn")}
          dir="ltr"
          rows={3}
        />
      </div>
      <SelectField
        control={form.control}
        name="photo"
        label={t("centerPage.doctorProfiles.photo")}
        description={photos.length === 0 ? t("centerPage.doctorProfiles.noPhotos") : undefined}
        options={[
          { value: "none", label: t("centerPage.doctorProfiles.noPhoto") },
          ...photos.map((m) => ({
            value: String(m.id),
            label: pickName({ ar: m.alt_ar, en: m.alt_en }, language) || `#${String(m.id)}`,
          })),
        ]}
      />
      <SwitchField
        control={form.control}
        name="online_bookable"
        label={t("centerPage.doctorProfiles.bookable")}
        description={
          doctor.has_schedule
            ? t("centerPage.doctorProfiles.bookableHint")
            : t("centerPage.doctorProfiles.bookableNoSchedule")
        }
      />
    </FormDialog>
  );
}

// --- Questions and answers ----------------------------------------------------------------

export function CenterFaqList() {
  const { t } = useTranslation("admin");
  const list = useCenterFaq();
  const remove = useDeleteCenterFaq();
  const language = useLanguage();
  const [editing, setEditing] = useState<CenterFaqOut | "new" | null>(null);
  const [removing, setRemoving] = useState<number | null>(null);
  return (
    <ContentCard
      title={t("centerPage.faq.title")}
      hint={t("centerPage.faq.hint")}
      testId="center-faq-admin"
      action={
        <Button
          variant="outline"
          onClick={() => {
            setEditing("new");
          }}
          data-testid="faq-add"
        >
          <Plus aria-hidden="true" />
          {t("centerPage.faq.add")}
        </Button>
      }
    >
      <QueryState loading={list.isPending} error={list.error} onRetry={() => void list.refetch()} rows={2}>
        {list.data && list.data.length > 0 ? (
          <ul className="flex flex-col divide-y divide-border">
            {list.data.map((row) => (
              <li key={row.id} className="flex items-start justify-between gap-3 py-3" data-testid="faq-row">
                <p className="min-w-0 text-sm font-medium break-words text-fg">
                  {pickName({ ar: row.question_ar, en: row.question_en }, language)}
                </p>
                <div className="flex shrink-0 items-center gap-1">
                  {row.active ? null : <Badge variant="neutral">{t("centerPage.state.hidden")}</Badge>}
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={t("centerPage.faq.edit")}
                    onClick={() => {
                      setEditing(row);
                    }}
                  >
                    <Pencil aria-hidden="true" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={t("centerPage.faq.remove")}
                    onClick={() => {
                      setRemoving(row.id);
                    }}
                  >
                    <Trash2 aria-hidden="true" />
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">{t("centerPage.faq.none")}</p>
        )}
      </QueryState>
      {editing !== null ? (
        <FaqDialog
          row={editing === "new" ? null : editing}
          next={list.data?.length ?? 0}
          onClose={() => {
            setEditing(null);
          }}
        />
      ) : null}
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => {
          if (!open) setRemoving(null);
        }}
        title={t("centerPage.faq.remove")}
        description={t("centerPage.faq.removeConfirm")}
        confirmLabel={t("centerPage.faq.remove")}
        destructive
        onConfirm={async () => {
          if (removing === null) return;
          await remove.mutateAsync(removing);
          toast.success(t("centerPage.faq.removed"));
          setRemoving(null);
        }}
      />
    </ContentCard>
  );
}

const faqSchema = z
  .object({
    question_ar: z.string().trim().max(200),
    question_en: z.string().trim().max(200),
    answer_ar: z.string().trim().max(1000),
    answer_en: z.string().trim().max(1000),
    active: z.boolean(),
  })
  .superRefine((v, ctx) => {
    if (!v.question_ar && !v.question_en)
      ctx.addIssue({ code: "custom", path: ["question_ar"], message: vmsg("admin:centerPage.faq.questionRule") });
    if (!v.answer_ar && !v.answer_en)
      ctx.addIssue({ code: "custom", path: ["answer_ar"], message: vmsg("admin:centerPage.faq.answerRule") });
  });
type FaqValues = z.infer<typeof faqSchema>;

function FaqDialog({ row, next, onClose }: { row: CenterFaqOut | null; next: number; onClose: () => void }) {
  const { t } = useTranslation("admin");
  const save = useSaveCenterFaq();
  const defaults = useMemo<FaqValues>(
    () => ({
      question_ar: row?.question_ar ?? "",
      question_en: row?.question_en ?? "",
      answer_ar: row?.answer_ar ?? "",
      answer_en: row?.answer_en ?? "",
      active: row?.active ?? true,
    }),
    [row],
  );
  const form = useForm<FaqValues>({ resolver: zodResolver(faqSchema), defaultValues: defaults });
  return (
    <FormDialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={row ? t("centerPage.faq.edit") : t("centerPage.faq.add")}
      description={t("centerPage.faq.hint")}
      form={form}
      error={save.error}
      wide
      submitLabel={t("centerPage.faq.save")}
      onSubmit={async (values) => {
        await save.mutateAsync(row ? { id: row.id, body: values } : { body: { ...values, sort_order: next } });
        toast.success(t("centerPage.faq.saved"));
        onClose();
      }}
    >
      <div className="grid gap-4 md:grid-cols-2">
        <TextField control={form.control} name="question_ar" label={t("centerPage.faq.questionAr")} dir="rtl" />
        <TextField control={form.control} name="question_en" label={t("centerPage.faq.questionEn")} dir="ltr" />
        <TextareaField
          control={form.control}
          name="answer_ar"
          label={t("centerPage.faq.answerAr")}
          dir="rtl"
          rows={3}
        />
        <TextareaField
          control={form.control}
          name="answer_en"
          label={t("centerPage.faq.answerEn")}
          dir="ltr"
          rows={3}
        />
      </div>
      <SwitchField
        control={form.control}
        name="active"
        label={t("centerPage.activeLabel")}
        description={t("centerPage.faq.activeHint")}
      />
    </FormDialog>
  );
}

// --- Testimonials -------------------------------------------------------------------------

function testimonialState(row: TestimonialOut): "approved" | "waiting" | "hidden" {
  if (!row.active) return "hidden";
  return row.approved ? "approved" : "waiting";
}

export function TestimonialsList() {
  const { t } = useTranslation("admin");
  const list = useTestimonials();
  const approve = useApproveTestimonial();
  const remove = useDeleteTestimonial();
  const translateError = useTranslateError();
  const canApprove = usePermission("core.approve_testimonial");
  const language = useLanguage();
  const [editing, setEditing] = useState<TestimonialOut | "new" | null>(null);
  const [removing, setRemoving] = useState<number | null>(null);
  return (
    <ContentCard
      title={t("centerPage.testimonials.title")}
      hint={t("centerPage.testimonials.hint")}
      testId="testimonials-admin"
      action={
        <Button
          variant="outline"
          onClick={() => {
            setEditing("new");
          }}
          data-testid="testimonial-add"
        >
          <Plus aria-hidden="true" />
          {t("centerPage.testimonials.add")}
        </Button>
      }
    >
      <QueryState loading={list.isPending} error={list.error} onRetry={() => void list.refetch()} rows={2}>
        {list.data && list.data.length > 0 ? (
          <ul className="flex flex-col divide-y divide-border">
            {list.data.map((row) => {
              const state = testimonialState(row);
              return (
                <li
                  key={row.id}
                  className="flex flex-col gap-2 py-3 sm:flex-row sm:items-start sm:justify-between"
                  data-testid="testimonial-row"
                >
                  <div className="min-w-0">
                    <p className="text-sm break-words text-fg">
                      {pickName({ ar: row.text_ar, en: row.text_en }, language)}
                    </p>
                    <p className="mt-0.5 text-xs text-muted">
                      {pickName({ ar: row.author_ar, en: row.author_en }, language)}
                      {row.approved_by_name ? (
                        <span className="block">
                          {t("centerPage.testimonials.approvedBy", { name: row.approved_by_name })}
                        </span>
                      ) : null}
                    </p>
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center gap-1">
                    <Badge variant={state === "approved" ? "success" : state === "waiting" ? "warning" : "neutral"}>
                      {t(`centerPage.testimonials.state.${state}`)}
                    </Badge>
                    {canApprove && !row.approved ? (
                      <Button
                        variant="outline"
                        size="sm"
                        loading={approve.isPending && approve.variables === row.id}
                        data-testid="testimonial-approve"
                        onClick={() => {
                          approve.mutate(row.id, {
                            onSuccess: () => toast.success(t("centerPage.testimonials.approved")),
                            onError: (err) => toast.error(translateError(err)),
                          });
                        }}
                      >
                        <Check aria-hidden="true" />
                        {t("centerPage.testimonials.approve")}
                      </Button>
                    ) : null}
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={t("centerPage.testimonials.edit")}
                      onClick={() => {
                        setEditing(row);
                      }}
                    >
                      <Pencil aria-hidden="true" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={t("centerPage.testimonials.remove")}
                      onClick={() => {
                        setRemoving(row.id);
                      }}
                    >
                      <Trash2 aria-hidden="true" />
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="text-sm text-muted">{t("centerPage.testimonials.none")}</p>
        )}
      </QueryState>
      {editing !== null ? (
        <TestimonialDialog
          row={editing === "new" ? null : editing}
          next={list.data?.length ?? 0}
          onClose={() => {
            setEditing(null);
          }}
        />
      ) : null}
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => {
          if (!open) setRemoving(null);
        }}
        title={t("centerPage.testimonials.remove")}
        description={t("centerPage.testimonials.removeConfirm")}
        confirmLabel={t("centerPage.testimonials.remove")}
        destructive
        onConfirm={async () => {
          if (removing === null) return;
          await remove.mutateAsync(removing);
          toast.success(t("centerPage.testimonials.removed"));
          setRemoving(null);
        }}
      />
    </ContentCard>
  );
}

const testimonialSchema = z
  .object({
    text_ar: z.string().trim().max(400),
    text_en: z.string().trim().max(400),
    author_ar: z.string().trim().max(80),
    author_en: z.string().trim().max(80),
    active: z.boolean(),
  })
  .refine((v) => v.text_ar || v.text_en, {
    path: ["text_ar"],
    message: vmsg("admin:centerPage.testimonials.textRule"),
  });
type TestimonialValues = z.infer<typeof testimonialSchema>;

function TestimonialDialog({ row, next, onClose }: { row: TestimonialOut | null; next: number; onClose: () => void }) {
  const { t } = useTranslation("admin");
  const save = useSaveTestimonial();
  const defaults = useMemo<TestimonialValues>(
    () => ({
      text_ar: row?.text_ar ?? "",
      text_en: row?.text_en ?? "",
      author_ar: row?.author_ar ?? "",
      author_en: row?.author_en ?? "",
      active: row?.active ?? true,
    }),
    [row],
  );
  const form = useForm<TestimonialValues>({ resolver: zodResolver(testimonialSchema), defaultValues: defaults });
  return (
    <FormDialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={row ? t("centerPage.testimonials.edit") : t("centerPage.testimonials.add")}
      description={t("centerPage.testimonials.hint")}
      form={form}
      error={save.error}
      wide
      submitLabel={t("centerPage.testimonials.save")}
      onSubmit={async (values) => {
        await save.mutateAsync(row ? { id: row.id, body: values } : { body: { ...values, sort_order: next } });
        toast.success(t("centerPage.testimonials.saved"));
        onClose();
      }}
    >
      <div className="grid gap-4 md:grid-cols-2">
        <TextareaField
          control={form.control}
          name="text_ar"
          label={t("centerPage.testimonials.textAr")}
          dir="rtl"
          rows={3}
        />
        <TextareaField
          control={form.control}
          name="text_en"
          label={t("centerPage.testimonials.textEn")}
          dir="ltr"
          rows={3}
        />
        <TextField
          control={form.control}
          name="author_ar"
          label={t("centerPage.testimonials.authorAr")}
          description={t("centerPage.testimonials.authorHint")}
          dir="rtl"
          optional
        />
        <TextField
          control={form.control}
          name="author_en"
          label={t("centerPage.testimonials.authorEn")}
          dir="ltr"
          optional
        />
      </div>
      <SwitchField control={form.control} name="active" label={t("centerPage.activeLabel")} />
    </FormDialog>
  );
}

// --- Insurer and service names ------------------------------------------------------------

function OnSiteList({
  items,
  pendingId,
  onToggle,
  name,
}: {
  items: { id: number; label: string; detail?: string; shown: boolean }[];
  pendingId: number | undefined;
  onToggle: (id: number, show: boolean) => void;
  name: string;
}) {
  const { t } = useTranslation("admin");
  if (items.length === 0) return <p className="text-sm text-muted">{t("centerPage.siteList.none")}</p>;
  return (
    <ul className="grid gap-2 sm:grid-cols-2">
      {items.map((item) => {
        const id = `${name}-${String(item.id)}`;
        return (
          <li key={item.id} className="flex items-start gap-3">
            <Checkbox
              id={id}
              checked={item.shown}
              disabled={pendingId === item.id}
              className="mt-0.5"
              onCheckedChange={(checked) => {
                onToggle(item.id, checked === true);
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

export function SitePayersChoices() {
  const payers = useSitePayers();
  const set = useSetPayerOnSite();
  const translateError = useTranslateError();
  const language = useLanguage();
  const items = (payers.data ?? [])
    .filter((p) => p.active)
    .map((p) => ({ id: p.id, label: pickName({ ar: p.name_ar, en: p.name_en }, language), shown: p.show_on_site }));
  return (
    <QueryState loading={payers.isPending} error={payers.error} rows={2}>
      <div data-testid="site-payers">
        <OnSiteList
          name="site-payer"
          items={items}
          pendingId={set.isPending ? set.variables.id : undefined}
          onToggle={(id, show) => {
            set.mutate({ id, show }, { onError: (err) => toast.error(translateError(err)) });
          }}
        />
      </div>
    </QueryState>
  );
}

export function SiteServicesChoices() {
  const { t } = useTranslation("admin");
  const services = useSiteServices();
  const set = useSetServiceOnSite();
  const translateError = useTranslateError();
  const language = useLanguage();
  const items = (services.data ?? [])
    .filter((s) => s.active && SITE_SERVICE_KINDS.has(s.kind))
    .map((s) => ({
      id: s.id,
      label: pickName({ ar: s.name_ar, en: s.name_en }, language),
      detail:
        s.department_id === null
          ? t("centerPage.siteList.noDepartment")
          : pickName({ ar: s.department_ar, en: s.department_en }, language),
      shown: s.show_on_site,
    }));
  return (
    <QueryState loading={services.isPending} error={services.error} rows={2}>
      <div data-testid="site-services" className="max-h-96 overflow-y-auto">
        <OnSiteList
          name="site-service"
          items={items}
          pendingId={set.isPending ? set.variables.id : undefined}
          onToggle={(id, show) => {
            set.mutate({ id, show }, { onError: (err) => toast.error(translateError(err)) });
          }}
        />
      </div>
    </QueryState>
  );
}
