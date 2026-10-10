/**
 * API shapes of the system pages (imports, status, export, audit), straight from the
 * generated OpenAPI schema (`make api`). Nothing here is hand-written.
 */
import type { components } from "@/lib/api/schema";

type S = components["schemas"];

export type ImportJob = S["ImportJobOut"];
export type ImportJobRow = S["ImportJobRowOut"];
export type ImportKind = "patients" | "items" | "prices";
export type ImportRowStatus = ImportJobRow["status"];
export type SystemStatus = S["SystemStatusOut"];
export type OpsRun = S["OpsRunOut"];
export type OpsWarning = SystemStatus["warnings"][number];
export type BackupRequest = S["BackupRequestOut"];
export type UpdateHistory = S["UpdateHistoryOut"];
export type UpdateRun = S["UpdateRunOut"];
export type UpdateLog = S["UpdateLogOut"];
export type AuditEvent = S["AuditEventOut"];
export type AuditModel = S["AuditModelOut"];
export type AuditAction = "insert" | "update" | "delete";
