import { Ban, Check, DoorOpen, KeyRound, Link2, Lock, MessageCircle, MoreHorizontal, PhoneOff, X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { ReasonDialog } from "@/components/ReasonDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { AlertCard } from "@/components/AlertCard";
import { PatientPicker } from "@/features/patients/components/PatientPicker";
import { QueryErrorAlert } from "@/features/patients/components/QueryErrorAlert";
import { patientName } from "@/features/patients/lib";
import type { PatientListItem } from "@/features/patients/types";
import { toApiError } from "@/lib/api/errors";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";
import { formatDate } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import {
  useApproveOnlineBooking,
  useCancelOnlineBooking,
  useLinkOnlineBookingPatient,
  useOnlineBookings,
  useReissueGuestPin,
  useRejectOnlineBookingsFromPhone,
  useVisitOptions,
  type OnlineBookingQuery,
} from "../api";
import { CheckInDialog, RejectOnlineBookingDialog } from "../components/AppointmentDialogs";
import { TokenSlipDialog } from "../components/TokenSlipDialog";
import type { OnlineBooking, OnlineBookingStatus } from "../types";

const STATUSES: readonly OnlineBookingStatus[] = [
  "requested",
  "booked",
  "arrived",
  "cancelled",
  "rescheduled",
  "no_show",
  "all",
];

const STATUS_VARIANT = {
  requested: "warning",
  booked: "info",
  arrived: "success",
  cancelled: "outline",
  no_show: "danger",
  rescheduled: "neutral",
} as const;

const ALL_DOCTORS = "all";

/** What the booker is told (`display_status`, plan section 5), in the portal's own words. */
const DISPLAY = [
  "awaiting_approval",
  "confirmed",
  "received",
  "moved",
  "cancelled_by_you",
  "cancelled_by_center",
  "declined",
  "expired",
  "missed",
] as const;
type Display = (typeof DISPLAY)[number];
const isDisplay = (s: string): s is Display => (DISPLAY as readonly string[]).includes(s);

type Action =
  | { kind: "decline"; booking: OnlineBooking }
  | { kind: "cancel"; booking: OnlineBooking }
  | { kind: "declinePhone"; booking: OnlineBooking }
  | { kind: "link"; booking: OnlineBooking }
  | { kind: "pin"; booking: OnlineBooking }
  | { kind: "checkIn"; booking: OnlineBooking };

/**
 * `/visits/online-bookings`: the reception inbox of bookings made on the website by patients
 * and guests (ADR 0029 D, F, G; plan Phase 4). Reception approves or declines requests, cancels
 * on the booker's behalf, declines every open request of one phone, links a booking to a
 * patient file after checking who came, issues a new PIN, answers on WhatsApp (a plain wa.me
 * link, nothing sent by the server) and checks the booker in. Every rule is the server's.
 * Requires `visits.manage_online_bookings`.
 */
export function OnlineBookingsPage() {
  const { t } = useTranslation(["visits", "common"]);
  const language = useLanguage();
  const options = useVisitOptions();
  const [query, setQuery] = useState<OnlineBookingQuery>({ status: "requested", day: null, doctorId: null });
  const list = useOnlineBookings(query);
  const [action, setAction] = useState<Action | null>(null);
  const [newPin, setNewPin] = useState<{ pin: string; booking: OnlineBooking } | null>(null);
  const [tokenEntry, setTokenEntry] = useState<number | null>(null);
  const doctors = options.data?.doctors ?? [];
  const close = (open: boolean) => {
    if (!open) setAction(null);
  };
  const rows = list.data ?? [];

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={t("inbox.title")} description={t("inbox.description")} />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[14rem_minmax(0,16rem)_minmax(0,18rem)] lg:items-start">
        <div className="grid gap-1.5">
          <Label htmlFor="inbox-status">{t("inbox.status")}</Label>
          <Select
            value={query.status}
            onValueChange={(v) => {
              setQuery({ ...query, status: v as OnlineBookingStatus });
            }}
          >
            <SelectTrigger id="inbox-status" data-testid="inbox-status">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {STATUSES.map((s) => (
                <SelectItem key={s} value={s}>
                  {s === "all" ? t("inbox.allStatuses") : t(`appointmentStatus.${s}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="inbox-day">{t("inbox.day")}</Label>
          <div className="flex items-center gap-2">
            <Input
              id="inbox-day"
              type="date"
              dir="ltr"
              className="min-w-0 flex-1"
              value={query.day ?? ""}
              onChange={(e) => {
                setQuery({ ...query, day: e.target.value || null });
              }}
            />
            {query.day ? (
              <Button
                variant="ghost"
                size="icon"
                aria-label={t("inbox.clearDay")}
                onClick={() => {
                  setQuery({ ...query, day: null });
                }}
              >
                <X aria-hidden="true" />
              </Button>
            ) : null}
          </div>
          <p className="text-xs text-muted">
            {query.day ? formatDate(`${query.day}T12:00:00`, language, "long") : t("inbox.fromToday")}
          </p>
        </div>
        <div className="grid gap-1.5 sm:col-span-2 lg:col-span-1">
          <Label htmlFor="inbox-doctor">{t("inbox.doctor")}</Label>
          <Select
            value={query.doctorId === null ? ALL_DOCTORS : String(query.doctorId)}
            onValueChange={(v) => {
              setQuery({ ...query, doctorId: v === ALL_DOCTORS ? null : Number(v) });
            }}
          >
            <SelectTrigger id="inbox-doctor">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_DOCTORS}>{t("inbox.allDoctors")}</SelectItem>
              {doctors.map((d) => (
                <SelectItem key={d.id} value={String(d.id)}>
                  {pickName({ ar: d.name_ar, en: d.name_en }, language)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <section aria-labelledby="inbox-heading" className="flex flex-col gap-3">
        <h2 id="inbox-heading" className="sr-only">
          {t("inbox.listTitle")}
        </h2>
        {list.isError ? (
          <QueryErrorAlert
            title={t("inbox.loadFailed")}
            error={list.error}
            onRetry={() => void list.refetch()}
            retrying={list.isFetching}
          />
        ) : list.isPending ? (
          <div className="grid gap-2">
            <Skeleton className="h-28" />
            <Skeleton className="h-28" />
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            title={query.status === "requested" ? t("inbox.emptyRequests") : t("inbox.empty")}
            description={t("inbox.emptyHint")}
          />
        ) : (
          <ul className="grid gap-3" data-testid="inbox-list">
            {rows.map((b) => (
              <li key={b.id}>
                <InboxRow booking={b} onAction={setAction} />
              </li>
            ))}
          </ul>
        )}
      </section>

      <RejectOnlineBookingDialog
        appointment={action?.kind === "decline" ? action.booking : null}
        onOpenChange={close}
      />
      {action?.kind === "cancel" ? <CancelOnBehalf booking={action.booking} onOpenChange={close} /> : null}
      {action?.kind === "declinePhone" ? <DeclinePhone booking={action.booking} onOpenChange={close} /> : null}
      {action?.kind === "link" ? <LinkPatient booking={action.booking} onOpenChange={close} /> : null}
      {action?.kind === "pin" ? (
        <ReissuePin
          booking={action.booking}
          onOpenChange={close}
          onIssued={(pin, booking) => {
            setNewPin({ pin, booking });
          }}
        />
      ) : null}
      <CheckInDialog
        appointment={action?.kind === "checkIn" ? action.booking : null}
        onOpenChange={close}
        onCheckedIn={(visit) => {
          if (visit.queue_entry) setTokenEntry(visit.queue_entry.id);
        }}
      />
      <NewPinDialog
        value={newPin}
        onOpenChange={(open) => {
          if (!open) setNewPin(null);
        }}
      />
      <TokenSlipDialog
        entryId={tokenEntry}
        onOpenChange={(open) => {
          if (!open) setTokenEntry(null);
        }}
      />
    </div>
  );
}

function bookerName(b: OnlineBooking, language: "ar" | "en"): string {
  return b.patient ? patientName(b.patient, language) : b.contact_name;
}

function InboxRow({ booking: b, onAction }: { booking: OnlineBooking; onAction: (action: Action) => void }) {
  const { t } = useTranslation(["visits", "common", "portal"]);
  const language = useLanguage();
  const translateError = useTranslateError();
  const approve = useApproveOnlineBooking();
  const canCheckIn = usePermission("visits.create");
  const requested = b.status === "requested";
  const open = requested || b.status === "booked";
  const isGuest = b.source === "guest";
  const name = bookerName(b, language);
  const phone = b.patient?.phone ?? b.contact_phone;

  const approveIt = async () => {
    try {
      await approve.mutateAsync(b.id);
      toast.success(t("appointments.approved"));
    } catch (e) {
      toast.error(translateError(toApiError(e)));
    }
  };

  return (
    <article
      className="card-surface flex flex-col gap-3 p-4 md:p-(--d-card-pad)"
      data-testid="inbox-row"
      data-booking={b.id}
      aria-label={name}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 flex-col gap-0.5">
          <p className="font-semibold break-words text-fg">{name}</p>
          <p className="text-sm text-fg">
            <DateText value={b.starts_at} format="long" />
            {" · "}
            <DateText value={b.starts_at} format="time" />
          </p>
          <p className="text-sm text-muted">
            {pickName({ ar: b.doctor.name_ar, en: b.doctor.name_en }, language)}
            {" · "}
            {pickName({ ar: b.department.name_ar, en: b.department.name_en }, language)}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant={STATUS_VARIANT[b.status]} data-testid="inbox-status-badge">
            {t(`appointmentStatus.${b.status}`)}
          </Badge>
          <Badge variant="outline">{t(`inbox.source.${b.source}`)}</Badge>
          {b.guest_locked ? (
            <Badge variant="danger" data-testid="inbox-locked">
              <Lock aria-hidden="true" className="size-3" />
              {t("inbox.locked")}
            </Badge>
          ) : null}
        </div>
      </div>

      <dl className="grid gap-x-4 gap-y-1 text-sm sm:grid-cols-2">
        <div className="flex flex-wrap gap-x-2">
          <dt className="text-muted">{t("inbox.phone")}</dt>
          <dd>
            <bdi className="num text-fg">{phone || "-"}</bdi>
          </dd>
        </div>
        {b.reference ? (
          <div className="flex flex-wrap gap-x-2">
            <dt className="text-muted">{t("inbox.reference")}</dt>
            <dd>
              <bdi className="num text-fg" data-testid="inbox-reference">
                {b.reference}
              </bdi>
            </dd>
          </div>
        ) : null}
        <div className="flex flex-wrap gap-x-2">
          <dt className="text-muted">{t("inbox.bookerSees")}</dt>
          <dd className="text-fg">
            {isDisplay(b.display_status) ? t(`portal:appointments.display.${b.display_status}`) : b.display_status}
          </dd>
        </div>
        <div className="flex flex-wrap gap-x-2">
          <dt className="text-muted">{t("inbox.file")}</dt>
          <dd className="text-fg">
            {b.patient ? <bdi className="num">{b.patient.file_no}</bdi> : t("appointments.noFile")}
          </dd>
        </div>
      </dl>

      {requested && b.expires_at ? (
        <p className="text-xs text-muted">
          {t("appointments.requestExpires", { time: formatDate(b.expires_at, language, "datetime") })}
        </p>
      ) : null}
      {isGuest && b.phone_open_requests > 1 ? (
        <p className="text-xs font-medium text-warning-fg" data-testid="inbox-phone-requests">
          {t("inbox.phoneRequests", { count: b.phone_open_requests })}
        </p>
      ) : null}
      {b.cancel_reason ? (
        <p className="text-xs text-muted">
          {t("appointments.cancelledBecause", {
            note: [pickName({ ar: b.cancel_reason.label_ar, en: b.cancel_reason.label_en }, language), b.cancel_note]
              .filter(Boolean)
              .join(" · "),
          })}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        {requested ? (
          <>
            <Button size="sm" loading={approve.isPending} onClick={() => void approveIt()} data-testid="inbox-approve">
              <Check aria-hidden="true" />
              {t("appointments.approve")}
            </Button>
            <Button
              size="sm"
              variant="destructive-soft"
              onClick={() => {
                onAction({ kind: "decline", booking: b });
              }}
              data-testid="inbox-decline"
            >
              <Ban aria-hidden="true" />
              {t("appointments.decline")}
            </Button>
          </>
        ) : null}
        {b.status === "booked" && canCheckIn ? (
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              onAction({ kind: "checkIn", booking: b });
            }}
            data-testid="inbox-check-in"
          >
            <DoorOpen aria-hidden="true" />
            {t("appointments.checkIn")}
          </Button>
        ) : null}
        {b.whatsapp_url ? (
          <Button asChild size="sm" variant="outline">
            <a href={b.whatsapp_url} target="_blank" rel="noopener noreferrer" data-testid="inbox-whatsapp">
              <MessageCircle aria-hidden="true" />
              {t("inbox.whatsapp")}
            </a>
          </Button>
        ) : null}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              size="icon"
              variant="ghost"
              aria-label={t("appointments.moreFor", { name })}
              data-testid="inbox-more"
            >
              <MoreHorizontal aria-hidden="true" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {open && !b.patient ? (
              <DropdownMenuItem
                onSelect={() => {
                  onAction({ kind: "link", booking: b });
                }}
                data-testid="inbox-link"
              >
                <Link2 aria-hidden="true" />
                {t("inbox.link")}
              </DropdownMenuItem>
            ) : null}
            {b.reference && open ? (
              <DropdownMenuItem
                onSelect={() => {
                  onAction({ kind: "pin", booking: b });
                }}
                data-testid="inbox-pin"
              >
                <KeyRound aria-hidden="true" />
                {t("inbox.reissuePin")}
              </DropdownMenuItem>
            ) : null}
            {open ? (
              <>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  variant="destructive"
                  onSelect={() => {
                    onAction({ kind: "cancel", booking: b });
                  }}
                  data-testid="inbox-cancel"
                >
                  <Ban aria-hidden="true" />
                  {t("inbox.cancel")}
                </DropdownMenuItem>
              </>
            ) : null}
            {isGuest && requested && b.phone_open_requests > 0 ? (
              <DropdownMenuItem
                variant="destructive"
                onSelect={() => {
                  onAction({ kind: "declinePhone", booking: b });
                }}
                data-testid="inbox-decline-phone"
              >
                <PhoneOff aria-hidden="true" />
                {t("inbox.declinePhone")}
              </DropdownMenuItem>
            ) : null}
            {!open && !b.reference ? <DropdownMenuItem disabled>{t("inbox.noActions")}</DropdownMenuItem> : null}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </article>
  );
}

function useCancelReasons(preferred?: string) {
  const language = useLanguage();
  const options = useVisitOptions();
  const all = options.data?.appointment_cancel_reasons ?? [];
  const sorted = preferred
    ? [...all.filter((r) => r.code === preferred), ...all.filter((r) => r.code !== preferred)]
    : all;
  return sorted.map((r) => ({ code: r.code, label: pickName({ ar: r.label_ar, en: r.label_en }, language) }));
}

function describe(b: OnlineBooking, language: "ar" | "en"): string {
  return `${bookerName(b, language)} · ${formatDate(b.starts_at, language, "datetime")}`;
}

function CancelOnBehalf({ booking, onOpenChange }: { booking: OnlineBooking; onOpenChange: (open: boolean) => void }) {
  const { t } = useTranslation(["visits", "common"]);
  const language = useLanguage();
  const cancel = useCancelOnlineBooking();
  const reasons = useCancelReasons();
  return (
    <ReasonDialog
      open
      onOpenChange={onOpenChange}
      title={t("inbox.cancelTitle")}
      description={describe(booking, language)}
      reasons={reasons}
      noteRequired={false}
      destructive
      confirmLabel={t("inbox.cancel")}
      onSubmit={async ({ code, note }) => {
        await cancel.mutateAsync({ id: booking.id, reasonCode: code, note });
        toast.success(t("appointments.cancelled"));
      }}
    />
  );
}

function DeclinePhone({ booking, onOpenChange }: { booking: OnlineBooking; onOpenChange: (open: boolean) => void }) {
  const { t } = useTranslation(["visits", "common"]);
  const reject = useRejectOnlineBookingsFromPhone();
  const reasons = useCancelReasons("ONLINE_REJECTED");
  return (
    <ReasonDialog
      open
      onOpenChange={onOpenChange}
      title={t("inbox.declinePhoneTitle")}
      description={t("inbox.declinePhoneText", {
        count: booking.phone_open_requests,
        phone: booking.contact_phone,
      })}
      reasons={reasons}
      noteRequired={false}
      destructive
      confirmLabel={t("inbox.declinePhoneConfirm")}
      onSubmit={async ({ code, note }) => {
        const result = await reject.mutateAsync({ id: booking.id, reasonCode: code, note });
        toast.success(t("inbox.declinedPhone", { count: result.rejected }));
      }}
    />
  );
}

function LinkPatient({ booking, onOpenChange }: { booking: OnlineBooking; onOpenChange: (open: boolean) => void }) {
  const { t } = useTranslation(["visits", "common", "errors"]);
  const language = useLanguage();
  const translateError = useTranslateError();
  const link = useLinkOnlineBookingPatient();
  const [patient, setPatient] = useState<PatientListItem | null>(null);
  const [error, setError] = useState<string | null>(null);
  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("inbox.linkTitle")}</DialogTitle>
          <DialogDescription>{describe(booking, language)}</DialogDescription>
        </DialogHeader>
        <p className="text-sm text-pretty text-muted">{t("inbox.linkHint")}</p>
        <PatientPicker value={patient} onChange={setPatient} />
        {error ? (
          <AlertCard variant="danger" title={t("errors:title")} live>
            {error}
          </AlertCard>
        ) : null}
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => {
              onOpenChange(false);
            }}
          >
            {t("common:actions.cancel")}
          </Button>
          <Button
            disabled={!patient}
            loading={link.isPending}
            data-testid="inbox-link-confirm"
            onClick={() => {
              if (!patient) return;
              setError(null);
              link
                .mutateAsync({ id: booking.id, patientId: patient.id })
                .then(() => {
                  toast.success(t("inbox.linked"));
                  onOpenChange(false);
                })
                .catch((e: unknown) => {
                  setError(translateError(toApiError(e)));
                });
            }}
          >
            {t("inbox.linkConfirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ReissuePin({
  booking,
  onOpenChange,
  onIssued,
}: {
  booking: OnlineBooking;
  onOpenChange: (open: boolean) => void;
  onIssued: (pin: string, booking: OnlineBooking) => void;
}) {
  const { t } = useTranslation(["visits", "common"]);
  const language = useLanguage();
  const reissue = useReissueGuestPin();
  return (
    <ReasonDialog
      open
      onOpenChange={onOpenChange}
      title={t("inbox.pinTitle")}
      description={`${describe(booking, language)} · ${booking.reference ?? ""}`}
      reasons={[]}
      confirmLabel={t("inbox.pinConfirm")}
      onSubmit={async ({ note }) => {
        const result = await reissue.mutateAsync({ id: booking.id, reason: note });
        onIssued(result.pin, result.booking);
      }}
    >
      <p className="text-sm text-pretty text-muted">{t("inbox.pinHint")}</p>
    </ReasonDialog>
  );
}

/** The new PIN, shown once: reception reads it to the guest. */
function NewPinDialog({
  value,
  onOpenChange,
}: {
  value: { pin: string; booking: OnlineBooking } | null;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation(["visits", "common"]);
  return (
    <Dialog open={value !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t("inbox.newPinTitle")}</DialogTitle>
          <DialogDescription>{t("inbox.newPinText")}</DialogDescription>
        </DialogHeader>
        {value ? (
          <dl className="grid gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1 rounded-control border border-border p-3">
              <dt className="text-sm text-muted">{t("inbox.reference")}</dt>
              <dd className="num text-lg font-bold">{value.booking.reference}</dd>
            </div>
            <div className="flex flex-col gap-1 rounded-control border border-warning-border bg-warning-bg p-3 text-warning-fg">
              <dt className="text-sm">{t("inbox.newPin")}</dt>
              <dd className="num text-2xl font-bold tracking-[0.3em]" data-testid="inbox-new-pin">
                {value.pin}
              </dd>
            </div>
          </dl>
        ) : null}
        <DialogFooter>
          <Button
            onClick={() => {
              onOpenChange(false);
            }}
          >
            {t("inbox.newPinDone")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
