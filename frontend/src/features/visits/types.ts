/** API shapes of /api/visits, named after the generated OpenAPI schemas (`make api`). */
import type { components } from "@/lib/api/schema";

type S = components["schemas"];

export type VisitOptions = S["VisitOptionsOut"];
export type Department = S["DepartmentOut"];
export type Doctor = S["DoctorOut"];
export type Visit = S["VisitOut"];
export type VisitDetail = S["VisitDetailOut"];
export type VisitInput = S["VisitIn"];
export type VisitCancelInput = S["VisitCancelIn"];
export type VisitLine = S["LineOut"];
export type TimelineEvent = S["TimelineOut"];
export type QueueRow = S["QueueRowOut"];
export type QueueAction = S["QueueMoveIn"]["action"];
export type QueueStatus = QueueRow["status"];
export type WaitingRoom = S["WaitingRoomOut"];
export type DisplayEntry = S["DisplayEntryOut"];
export type TokenSlip = S["TokenSlipOut"];
export type Appointment = S["AppointmentOut"];
export type AppointmentInput = S["AppointmentIn"];
export type AppointmentPatch = S["AppointmentPatch"];
export type AgendaItem = S["AgendaItemOut"];
export type DayAgenda = S["DayAgendaOut"];
export type CheckInInput = S["CheckInIn"];
export type VisitPage = S["Page_VisitOut_"];
