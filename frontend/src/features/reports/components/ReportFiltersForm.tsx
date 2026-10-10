import { RotateCcw, SlidersHorizontal } from "lucide-react";
import { useState, type SyntheticEvent } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import type { ReportSearch } from "../lib/search";
import type { Report } from "../types";

const ALL = "all";

/**
 * The filters a report takes (dates, an "as of" day, department, user, expiry window), filled
 * with what the server applied. "Show" puts them in the address; the server checks them.
 */
export function ReportFiltersForm({
  report,
  onApply,
  onReset,
}: {
  report: Report;
  onApply: (search: ReportSearch) => void;
  onReset: () => void;
}) {
  const { t } = useTranslation("reports");
  const language = useLanguage();
  const available = new Set(report.filters_available);
  const applied = report.filters;
  const [from, setFrom] = useState(applied.date_from);
  const [to, setTo] = useState(applied.date_to);
  const [department, setDepartment] = useState(applied.department_id ? String(applied.department_id) : ALL);
  const [user, setUser] = useState(applied.user_id ? String(applied.user_id) : ALL);
  const [days, setDays] = useState(applied.days !== null ? String(applied.days) : "");

  if (available.size === 0) return null;

  const submit = (event: SyntheticEvent) => {
    event.preventDefault();
    const daysNumber = Number(days);
    onApply({
      ...(available.has("dates") && from ? { from } : {}),
      ...((available.has("dates") || available.has("as_of")) && to ? { to } : {}),
      ...(available.has("department") && department !== ALL ? { department: Number(department) } : {}),
      ...(available.has("user") && user !== ALL ? { user: Number(user) } : {}),
      ...(available.has("days") && days !== "" && Number.isInteger(daysNumber) && daysNumber >= 0
        ? { days: daysNumber }
        : {}),
    });
  };

  return (
    <form
      onSubmit={submit}
      aria-label={t("filters.title")}
      data-testid="report-filters"
      className="card-surface grid grid-cols-1 gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4 lg:items-end"
    >
      {available.has("dates") ? (
        <>
          <div className="flex min-w-0 flex-col gap-1.5">
            <Label htmlFor="report-from">{t("filters.dateFrom")}</Label>
            <Input
              id="report-from"
              type="date"
              value={from}
              max={to}
              onChange={(e) => {
                setFrom(e.target.value);
              }}
            />
          </div>
          <div className="flex min-w-0 flex-col gap-1.5">
            <Label htmlFor="report-to">{t("filters.dateTo")}</Label>
            <Input
              id="report-to"
              type="date"
              value={to}
              min={from}
              onChange={(e) => {
                setTo(e.target.value);
              }}
            />
          </div>
        </>
      ) : null}
      {available.has("as_of") ? (
        <div className="flex min-w-0 flex-col gap-1.5">
          <Label htmlFor="report-as-of">{t("filters.asOf")}</Label>
          <Input
            id="report-as-of"
            type="date"
            value={to}
            onChange={(e) => {
              setTo(e.target.value);
            }}
          />
        </div>
      ) : null}
      {available.has("department") ? (
        <div className="flex min-w-0 flex-col gap-1.5">
          <Label htmlFor="report-department">{t("filters.department")}</Label>
          <Select value={department} onValueChange={setDepartment}>
            <SelectTrigger id="report-department" className="h-11 w-full md:h-10">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>{t("filters.allDepartments")}</SelectItem>
              {report.departments.map((d) => (
                <SelectItem key={d.id} value={String(d.id)}>
                  {pickName(d.name, language)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      ) : null}
      {available.has("user") ? (
        <div className="flex min-w-0 flex-col gap-1.5">
          <Label htmlFor="report-user">{t("filters.user")}</Label>
          <Select value={user} onValueChange={setUser}>
            <SelectTrigger id="report-user" className="h-11 w-full md:h-10">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>{t("filters.allUsers")}</SelectItem>
              {report.users.map((u) => (
                <SelectItem key={u.id} value={String(u.id)}>
                  {pickName(u.name, language)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      ) : null}
      {available.has("days") ? (
        <div className="flex min-w-0 flex-col gap-1.5">
          <Label htmlFor="report-days">{t("filters.days")}</Label>
          <Input
            id="report-days"
            type="number"
            inputMode="numeric"
            min={0}
            max={3650}
            value={days}
            onChange={(e) => {
              setDays(e.target.value);
            }}
          />
        </div>
      ) : null}
      <div className="flex flex-wrap gap-2 sm:col-span-2 lg:col-span-1 lg:justify-end">
        <Button type="submit" className="flex-1 lg:flex-none" data-testid="report-apply">
          <SlidersHorizontal aria-hidden="true" />
          {t("filters.apply")}
        </Button>
        <Button type="button" variant="outline" className="flex-1 lg:flex-none" onClick={onReset}>
          <RotateCcw aria-hidden="true" />
          {t("filters.reset")}
        </Button>
      </div>
    </form>
  );
}
