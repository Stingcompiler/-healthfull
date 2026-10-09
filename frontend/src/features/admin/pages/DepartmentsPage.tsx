import { zodResolver } from "@hookform/resolvers/zod";
import type { ColumnDef } from "@tanstack/react-table";
import { Building2, CalendarClock, DoorOpen, Pencil, Plus, Stethoscope, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useFieldArray, useForm, useWatch } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { z } from "zod";

import { DataTable } from "@/components/DataTable";
import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
  SelectField,
  SwitchField,
  TextField,
} from "@/components/form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { vmsg } from "@/lib/validation";

import {
  useDepartments,
  useDoctorCandidates,
  useDoctors,
  useRooms,
  useSaveDepartment,
  useSaveDoctor,
  useSaveRoom,
  useServices,
  useSetSchedule,
} from "../api";
import { AdminPage, QueryState } from "../components/AdminPage";
import { ListEmpty } from "../components/ListEmpty";
import { ActiveBadge, Code, FormDialog } from "../components/FormDialog";
import { DepartmentLabel } from "../components/DepartmentLabel";
import { useDepartmentById, useLocalName, usePersonName } from "../hooks";
import { CLOCK_TIME, normalizeClockTime } from "../dates";
import { sortWeekdays, WEEK_ORDER } from "../weekdays";
import type { DepartmentOut, DoctorOut, RoomOut } from "../types";

type Tab = "departments" | "rooms" | "doctors";
const NONE = "__none__";
const code = z
  .string()
  .trim()
  .regex(/^[A-Z][A-Z0-9_-]{0,19}$/, vmsg("admin:common.codeRule"));
const name = z.string().trim().min(1, vmsg("validation.required")).max(150);

export function DepartmentsPage() {
  const { t } = useTranslation("admin");
  const [tab, setTab] = useState<Tab>("departments");
  return (
    <AdminPage
      section="departments"
      title={t("sections.departments.title")}
      description={t("sections.departments.description")}
    >
      <Tabs
        value={tab}
        onValueChange={(v) => {
          setTab(v as Tab);
        }}
      >
        <TabsList aria-label={t("sections.departments.title")}>
          <TabsTrigger value="departments">{t("departments.departmentsTab")}</TabsTrigger>
          <TabsTrigger value="rooms">{t("departments.roomsTab")}</TabsTrigger>
          <TabsTrigger value="doctors">{t("departments.doctorsTab")}</TabsTrigger>
        </TabsList>
        <TabsContent value="departments">
          <DepartmentsTab />
        </TabsContent>
        <TabsContent value="rooms">
          <RoomsTab />
        </TabsContent>
        <TabsContent value="doctors">
          <DoctorsTab />
        </TabsContent>
      </Tabs>
    </AdminPage>
  );
}

function AddButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <div className="flex justify-end">
      <Button onClick={onClick}>
        <Plus />
        {label}
      </Button>
    </div>
  );
}

// --- Departments ------------------------------------------------------------------------------

const deptSchema = z.object({
  code,
  name_ar: name,
  name_en: name,
  sort_order: z.string().regex(/^\d{1,5}$/),
  active: z.boolean(),
});
type DeptValues = z.infer<typeof deptSchema>;

function DepartmentsTab() {
  const { t } = useTranslation("admin");
  const localName = useLocalName();
  const departments = useDepartments();
  const [editing, setEditing] = useState<DepartmentOut | "new" | null>(null);
  const columns = useMemo<ColumnDef<DepartmentOut>[]>(
    () => [
      {
        id: "name",
        accessorFn: (d) => localName(d),
        header: t("common.name"),
        meta: { label: t("common.name") },
        cell: ({ row }) => (
          <div className="min-w-0">
            <div className="truncate font-medium text-fg">{localName(row.original)}</div>
            <Code>{row.original.code}</Code>
          </div>
        ),
      },
      {
        accessorKey: "room_count",
        header: t("departments.rooms"),
        meta: { label: t("departments.rooms"), align: "end" },
      },
      {
        accessorKey: "doctor_count",
        header: t("departments.doctors"),
        meta: { label: t("departments.doctors"), align: "end" },
      },
      {
        accessorKey: "active",
        header: t("common.status"),
        meta: { label: t("common.status") },
        cell: ({ row }) => <ActiveBadge active={row.original.active} />,
      },
    ],
    [t, localName],
  );
  return (
    <div className="flex flex-col gap-3">
      <AddButton
        label={t("departments.addDepartment")}
        onClick={() => {
          setEditing("new");
        }}
      />
      <QueryState loading={departments.isPending} error={departments.error}>
        <DataTable
          caption={t("departments.departmentsTab")}
          columns={columns}
          data={departments.data ?? []}
          getRowId={(d) => String(d.id)}
          emptyState={
            <ListEmpty
              icon={<Building2 />}
              title={t("empty.departments.title")}
              description={t("empty.departments.description")}
              actionLabel={t("departments.addDepartment")}
              onAction={() => {
                setEditing("new");
              }}
            />
          }
          onRowClick={setEditing}
          rowLabel={(d) => t("common.editNamed", { name: localName(d) })}
        />
      </QueryState>
      {editing ? (
        <DepartmentDialog
          department={editing === "new" ? null : editing}
          onClose={() => {
            setEditing(null);
          }}
        />
      ) : null}
    </div>
  );
}

function DepartmentDialog({ department, onClose }: { department: DepartmentOut | null; onClose: () => void }) {
  const { t } = useTranslation("admin");
  const save = useSaveDepartment();
  const form = useForm<DeptValues>({
    resolver: zodResolver(deptSchema),
    defaultValues: {
      code: department?.code ?? "",
      name_ar: department?.name_ar ?? "",
      name_en: department?.name_en ?? "",
      sort_order: String(department?.sort_order ?? 0),
      active: department?.active ?? true,
    },
  });
  return (
    <FormDialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={department ? t("departments.editDepartment") : t("departments.addDepartment")}
      form={form}
      error={save.error}
      onSubmit={async ({ code: c, sort_order, ...rest }) => {
        const body = { ...rest, sort_order: Number(sort_order) };
        await save.mutateAsync(department ? { id: department.id, body } : { body: { ...body, code: c } });
        toast.success(t("common.saved"));
        onClose();
      }}
    >
      <TextField
        control={form.control}
        name="code"
        label={t("common.code")}
        dir="ltr"
        disabled={department !== null}
        required
      />
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField control={form.control} name="name_ar" label={t("common.nameAr")} dir="rtl" required />
        <TextField control={form.control} name="name_en" label={t("common.nameEn")} dir="ltr" required />
      </div>
      <TextField control={form.control} name="sort_order" label={t("common.sortOrder")} inputMode="numeric" dir="ltr" />
      <SwitchField control={form.control} name="active" label={t("common.active")} />
    </FormDialog>
  );
}

// --- Rooms ------------------------------------------------------------------------------------

const roomSchema = z.object({ code, name_ar: name, name_en: name, department: z.string(), active: z.boolean() });
type RoomValues = z.infer<typeof roomSchema>;

function useDepartmentOptions(includeNone: boolean) {
  const { t } = useTranslation("admin");
  const localName = useLocalName();
  const departments = useDepartments();
  const options = (departments.data ?? [])
    .filter((d) => d.active)
    .map((d) => ({ value: String(d.id), label: `${localName(d)} (${d.code})` }));
  return includeNone ? [{ value: NONE, label: t("common.none") }, ...options] : options;
}

function RoomsTab() {
  const { t } = useTranslation("admin");
  const localName = useLocalName();
  const rooms = useRooms();
  const departmentById = useDepartmentById();
  const [editing, setEditing] = useState<RoomOut | "new" | null>(null);
  const columns = useMemo<ColumnDef<RoomOut>[]>(
    () => [
      {
        id: "name",
        accessorFn: (r) => localName(r),
        header: t("common.name"),
        meta: { label: t("common.name") },
        cell: ({ row }) => (
          <div className="min-w-0">
            <div className="truncate font-medium text-fg">{localName(row.original)}</div>
            <Code>{row.original.code}</Code>
          </div>
        ),
      },
      {
        id: "department",
        accessorFn: (r) => {
          const department = departmentById(r.department_id);
          return department ? localName(department) : (r.department_code ?? "");
        },
        header: t("departments.department"),
        meta: { label: t("departments.department") },
        cell: ({ row }) => <DepartmentLabel id={row.original.department_id} code={row.original.department_code} />,
      },
      {
        accessorKey: "active",
        header: t("common.status"),
        meta: { label: t("common.status") },
        cell: ({ row }) => <ActiveBadge active={row.original.active} />,
      },
    ],
    [t, localName, departmentById],
  );
  return (
    <div className="flex flex-col gap-3">
      <AddButton
        label={t("departments.addRoom")}
        onClick={() => {
          setEditing("new");
        }}
      />
      <QueryState loading={rooms.isPending} error={rooms.error}>
        <DataTable
          caption={t("departments.roomsTab")}
          columns={columns}
          data={rooms.data ?? []}
          getRowId={(r) => String(r.id)}
          emptyState={
            <ListEmpty
              icon={<DoorOpen />}
              title={t("empty.rooms.title")}
              description={t("empty.rooms.description")}
              actionLabel={t("departments.addRoom")}
              onAction={() => {
                setEditing("new");
              }}
            />
          }
          onRowClick={setEditing}
          rowLabel={(r) => t("common.editNamed", { name: localName(r) })}
        />
      </QueryState>
      {editing ? (
        <RoomDialog
          room={editing === "new" ? null : editing}
          onClose={() => {
            setEditing(null);
          }}
        />
      ) : null}
    </div>
  );
}

function RoomDialog({ room, onClose }: { room: RoomOut | null; onClose: () => void }) {
  const { t } = useTranslation("admin");
  const save = useSaveRoom();
  const departmentOptions = useDepartmentOptions(true);
  const form = useForm<RoomValues>({
    resolver: zodResolver(roomSchema),
    defaultValues: {
      code: room?.code ?? "",
      name_ar: room?.name_ar ?? "",
      name_en: room?.name_en ?? "",
      department: room?.department_id ? String(room.department_id) : NONE,
      active: room?.active ?? true,
    },
  });
  return (
    <FormDialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={room ? t("departments.editRoom") : t("departments.addRoom")}
      form={form}
      error={save.error}
      onSubmit={async ({ code: c, department, ...rest }) => {
        const body = { ...rest, department_id: department === NONE ? null : Number(department) };
        await save.mutateAsync(room ? { id: room.id, body } : { body: { ...body, code: c } });
        toast.success(t("common.saved"));
        onClose();
      }}
    >
      <TextField
        control={form.control}
        name="code"
        label={t("common.code")}
        dir="ltr"
        disabled={room !== null}
        required
      />
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField control={form.control} name="name_ar" label={t("common.nameAr")} dir="rtl" required />
        <TextField control={form.control} name="name_en" label={t("common.nameEn")} dir="ltr" required />
      </div>
      <SelectField
        control={form.control}
        name="department"
        label={t("departments.department")}
        options={departmentOptions}
      />
      <SwitchField control={form.control} name="active" label={t("common.active")} />
    </FormDialog>
  );
}

// --- Doctors and schedules --------------------------------------------------------------------

function useWeekdayName() {
  const { t } = useTranslation("admin");
  return (day: number) => t(`departments.weekdays.${String(day) as "0"}`);
}

function hhmm(value: string): string {
  return value.slice(0, 5);
}

function DoctorsTab() {
  const { t, i18n } = useTranslation("admin");
  const doctors = useDoctors();
  const weekday = useWeekdayName();
  const doctorName = usePersonName();
  const localName = useLocalName();
  const departmentById = useDepartmentById();
  const [editing, setEditing] = useState<DoctorOut | "new" | null>(null);
  const [scheduling, setScheduling] = useState<DoctorOut | null>(null);
  const columns = useMemo<ColumnDef<DoctorOut>[]>(
    () => [
      {
        id: "name",
        accessorFn: (d) => doctorName(d),
        header: t("common.name"),
        meta: { label: t("common.name") },
        cell: ({ row }) => (
          <div className="min-w-0">
            <div className="truncate font-medium text-fg">{doctorName(row.original)}</div>
            <div className="truncate text-xs text-muted">
              {(i18n.language === "ar" ? row.original.specialty_ar : row.original.specialty_en) ||
                row.original.specialty_en ||
                row.original.specialty_ar}
            </div>
          </div>
        ),
      },
      {
        id: "department",
        accessorFn: (d) => {
          const department = departmentById(d.department_id);
          return department ? localName(department) : d.department_code;
        },
        header: t("departments.department"),
        meta: { label: t("departments.department") },
        cell: ({ row }) => <DepartmentLabel id={row.original.department_id} code={row.original.department_code} />,
      },
      {
        id: "schedule",
        accessorFn: (d) => d.schedule.length,
        header: t("departments.schedule"),
        meta: { label: t("departments.schedule") },
        enableSorting: false,
        cell: ({ row }) =>
          row.original.schedule.length === 0 ? (
            <span className="text-muted">{t("departments.noSchedule")}</span>
          ) : (
            <div className="flex flex-wrap justify-end gap-1 md:justify-start">
              {sortWeekdays(row.original.schedule.map((s) => s.weekday)).map((day) => (
                <Badge key={day} variant="neutral">
                  {weekday(day)}
                </Badge>
              ))}
            </div>
          ),
      },
      {
        accessorKey: "active",
        header: t("common.status"),
        meta: { label: t("common.status") },
        cell: ({ row }) => <ActiveBadge active={row.original.active} />,
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps -- weekday and localName only depend on t and the language
    [t, i18n.language, doctorName, departmentById],
  );
  return (
    <div className="flex flex-col gap-3">
      <AddButton
        label={t("departments.addDoctor")}
        onClick={() => {
          setEditing("new");
        }}
      />
      <QueryState loading={doctors.isPending} error={doctors.error}>
        <DataTable
          caption={t("departments.doctorsTab")}
          columns={columns}
          data={doctors.data ?? []}
          getRowId={(d) => String(d.id)}
          emptyState={
            <ListEmpty
              icon={<Stethoscope />}
              title={t("empty.doctors.title")}
              description={t("empty.doctors.description")}
              actionLabel={t("departments.addDoctor")}
              onAction={() => {
                setEditing("new");
              }}
            />
          }
          onRowClick={setEditing}
          rowLabel={(d) => t("common.editNamed", { name: doctorName(d) })}
          rowActions={(d) => [
            {
              label: t("departments.editDoctor"),
              icon: <Pencil />,
              onSelect: () => {
                setEditing(d);
              },
            },
            {
              label: t("departments.editSchedule"),
              icon: <CalendarClock />,
              onSelect: () => {
                setScheduling(d);
              },
            },
          ]}
        />
      </QueryState>
      {editing ? (
        <DoctorDialog
          doctor={editing === "new" ? null : editing}
          onClose={() => {
            setEditing(null);
          }}
        />
      ) : null}
      {scheduling ? (
        <ScheduleDialog
          doctor={scheduling}
          onClose={() => {
            setScheduling(null);
          }}
        />
      ) : null}
    </div>
  );
}

const doctorSchema = z.object({
  user: z.string().min(1, vmsg("validation.selectOption")),
  department: z.string().min(1, vmsg("validation.selectOption")),
  specialty_ar: z.string().max(150),
  specialty_en: z.string().max(150),
  service: z.string(),
  active: z.boolean(),
});
type DoctorValues = z.infer<typeof doctorSchema>;

function DoctorDialog({ doctor, onClose }: { doctor: DoctorOut | null; onClose: () => void }) {
  const { t } = useTranslation("admin");
  const localName = useLocalName();
  const personName = usePersonName();
  const save = useSaveDoctor();
  const departmentOptions = useDepartmentOptions(false);
  const candidates = useDoctorCandidates();
  const services = useServices({ kind: "consultation", active: true });
  // Editing shows the doctor's own account (it has a profile, so it is no candidate).
  const people = doctor
    ? [
        {
          id: doctor.user_id,
          username: doctor.username,
          full_name_ar: doctor.full_name_ar,
          full_name_en: doctor.full_name_en,
        },
      ]
    : (candidates.data ?? []);
  const userOptions = people.map((u) => ({ value: String(u.id), label: `${personName(u)} (${u.username})` }));
  const serviceOptions = [
    { value: NONE, label: t("common.none") },
    ...(services.data?.items ?? []).map((s) => ({ value: String(s.id), label: `${localName(s)} (${s.code})` })),
  ];
  const form = useForm<DoctorValues>({
    resolver: zodResolver(doctorSchema),
    defaultValues: {
      user: doctor ? String(doctor.user_id) : "",
      department: doctor ? String(doctor.department_id) : "",
      specialty_ar: doctor?.specialty_ar ?? "",
      specialty_en: doctor?.specialty_en ?? "",
      service: doctor?.consultation_service_id ? String(doctor.consultation_service_id) : NONE,
      active: doctor?.active ?? true,
    },
  });
  return (
    <FormDialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={doctor ? t("departments.editDoctor") : t("departments.addDoctor")}
      description={doctor ? undefined : t("departments.doctorHint")}
      form={form}
      error={save.error}
      onSubmit={async (values) => {
        const body = {
          department_id: Number(values.department),
          specialty_ar: values.specialty_ar,
          specialty_en: values.specialty_en,
          consultation_service_id: values.service === NONE ? null : Number(values.service),
          active: values.active,
        };
        await save.mutateAsync(doctor ? { id: doctor.id, body } : { body: { ...body, user_id: Number(values.user) } });
        toast.success(t("common.saved"));
        onClose();
      }}
    >
      <SelectField
        control={form.control}
        name="user"
        label={t("departments.user")}
        options={userOptions}
        disabled={doctor !== null}
        required
      />
      <SelectField
        control={form.control}
        name="department"
        label={t("departments.department")}
        options={departmentOptions}
        required
      />
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField control={form.control} name="specialty_ar" label={t("departments.specialtyAr")} dir="rtl" />
        <TextField control={form.control} name="specialty_en" label={t("departments.specialtyEn")} dir="ltr" />
      </div>
      <SelectField
        control={form.control}
        name="service"
        label={t("departments.consultationService")}
        description={t("departments.consultationServiceHint")}
        options={serviceOptions}
      />
      <SwitchField control={form.control} name="active" label={t("common.active")} />
    </FormDialog>
  );
}

const sessionSchema = z
  .object({
    weekday: z.string(),
    start_time: z.string().regex(CLOCK_TIME, vmsg("admin:departments.timeRule")),
    end_time: z.string().regex(CLOCK_TIME, vmsg("admin:departments.timeRule")),
    slot_minutes: z.string().regex(/^\d{1,3}$/, vmsg("validation.number")),
    room: z.string(),
  })
  .refine((s) => s.end_time > s.start_time, { path: ["end_time"], message: vmsg("admin:departments.endAfterStart") });
const scheduleSchema = z.object({ sessions: z.array(sessionSchema).max(50) });
type ScheduleValues = z.infer<typeof scheduleSchema>;

function ScheduleDialog({ doctor, onClose }: { doctor: DoctorOut; onClose: () => void }) {
  const { t } = useTranslation("admin");
  const personName = usePersonName();
  const save = useSetSchedule();
  const rooms = useRooms();
  const weekday = useWeekdayName();
  const roomOptions = [
    { value: NONE, label: t("common.none") },
    ...(rooms.data ?? []).filter((r) => r.active).map((r) => ({ value: String(r.id), label: r.code })),
  ];
  const form = useForm<ScheduleValues>({
    resolver: zodResolver(scheduleSchema),
    defaultValues: {
      sessions: doctor.schedule.map((s) => ({
        weekday: String(s.weekday),
        start_time: hhmm(s.start_time),
        end_time: hhmm(s.end_time),
        slot_minutes: String(s.slot_minutes),
        room: s.room_id ? String(s.room_id) : NONE,
      })),
    },
  });
  const sessions = useFieldArray({ control: form.control, name: "sessions" });
  const watched = useWatch({ control: form.control, name: "sessions" });
  // Each session is named for screen readers ("Session 2: Tuesday 08:00 to 14:00").
  const sessionName = (index: number) => {
    const s = watched[index];
    return {
      n: index + 1,
      day: s ? weekday(Number(s.weekday)) : "",
      from: s?.start_time ?? "",
      to: s?.end_time ?? "",
    };
  };
  // After an add or a remove, focus goes somewhere sensible instead of the dialog body.
  const list = useRef<HTMLUListElement>(null);
  const addButton = useRef<HTMLButtonElement>(null);
  const focusNext = useRef<{ index: number; target: "day" | "remove" } | null>(null);
  const setFocusNext = (next: { index: number; target: "day" | "remove" }) => {
    focusNext.current = next;
  };
  useEffect(() => {
    const next = focusNext.current;
    if (!next) return;
    focusNext.current = null;
    const attribute = next.target === "day" ? "data-session-day" : "data-session-remove";
    const node =
      list.current?.querySelector<HTMLElement>(`[data-session="${String(next.index)}"] [${attribute}]`) ??
      addButton.current;
    node?.focus();
  }, [sessions.fields.length]);
  return (
    <FormDialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={t("departments.scheduleTitle", { name: personName(doctor) })}
      description={t("departments.scheduleHint")}
      form={form}
      error={save.error}
      wide
      onSubmit={async (values) => {
        await save.mutateAsync({
          id: doctor.id,
          sessions: values.sessions.map((s) => ({
            weekday: Number(s.weekday),
            start_time: s.start_time,
            end_time: s.end_time,
            slot_minutes: Number(s.slot_minutes),
            room_id: s.room === NONE ? null : Number(s.room),
          })),
        });
        toast.success(t("common.saved"));
        onClose();
      }}
    >
      {sessions.fields.length === 0 ? <p className="text-sm text-muted">{t("departments.noSchedule")}</p> : null}
      <ul ref={list} className="flex flex-col gap-3">
        {sessions.fields.map((field, index) => (
          <li
            key={field.id}
            role="group"
            aria-label={t("departments.sessionLabel", sessionName(index))}
            className="flex min-w-0 flex-col gap-3 rounded-control border border-border p-3"
            data-testid={`session-${String(index)}`}
            data-session={index}
          >
            {/* Two rows with flexible tracks: day and room, then times and slot. Fixed rem
                tracks squeezed the selects and cut the AM/PM marker off the time inputs. */}
            <div className="flex min-w-0 items-end gap-2">
              <div className="grid min-w-0 flex-1 grid-cols-1 gap-3 sm:grid-cols-2">
                <FormField
                  control={form.control}
                  name={`sessions.${index}.weekday`}
                  render={({ field: f }) => (
                    <FormItem className="min-w-0">
                      <FormLabel>{t("departments.weekday")}</FormLabel>
                      <Select value={f.value} onValueChange={f.onChange}>
                        <FormControl>
                          <SelectTrigger data-session-day="">
                            <SelectValue />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          {WEEK_ORDER.map((d) => (
                            <SelectItem key={d} value={String(d)}>
                              {weekday(d)}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </FormItem>
                  )}
                />
                <SelectField
                  control={form.control}
                  name={`sessions.${index}.room`}
                  label={t("departments.room")}
                  options={roomOptions}
                  className="min-w-0"
                />
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={t("departments.removeSessionNamed", sessionName(index))}
                data-session-remove=""
                onClick={() => {
                  sessions.remove(index);
                  // The session that took its place, else the one before it, else "Add session".
                  const left = sessions.fields.length - 1;
                  setFocusNext({ index: index < left ? index : index - 1, target: "remove" });
                }}
                className="shrink-0 self-start"
              >
                <Trash2 />
              </Button>
            </div>
            <div className="grid min-w-0 grid-cols-2 gap-3 sm:grid-cols-3">
              <TimeInput form={form} name={`sessions.${index}.start_time`} label={t("departments.start")} />
              <TimeInput form={form} name={`sessions.${index}.end_time`} label={t("departments.end")} />
              <FormField
                control={form.control}
                name={`sessions.${index}.slot_minutes`}
                render={({ field: f }) => (
                  <FormItem className="col-span-2 min-w-0 sm:col-span-1">
                    <FormLabel>{t("departments.slot")}</FormLabel>
                    <FormControl>
                      <Input {...f} inputMode="numeric" dir="ltr" />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>
          </li>
        ))}
      </ul>
      <div>
        <Button
          ref={addButton}
          type="button"
          variant="outline"
          onClick={() => {
            sessions.append(
              { weekday: "5", start_time: "08:00", end_time: "14:00", slot_minutes: "15", room: NONE },
              { shouldFocus: false },
            );
            setFocusNext({ index: sessions.fields.length, target: "day" });
          }}
        >
          <Plus />
          {t("departments.addSession")}
        </Button>
      </div>
    </FormDialog>
  );
}

function TimeInput({
  form,
  name: fieldName,
  label,
}: {
  form: ReturnType<typeof useForm<ScheduleValues>>;
  name: `sessions.${number}.start_time` | `sessions.${number}.end_time`;
  label: string;
}) {
  return (
    <FormField
      control={form.control}
      name={fieldName}
      render={({ field }) => (
        <FormItem className="min-w-0">
          <FormLabel>{label}</FormLabel>
          <FormControl>
            {/* 24-hour HH:MM text, not type="time": that follows the browser locale (AM/PM)
                instead of the app language. */}
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
