import { Activity, Banknote, Clock3, MoreHorizontal, Users, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { KpiCard } from "@/components/KpiCard";
import { MoneyText } from "@/components/MoneyText";
import { PatientCard } from "@/components/PatientCard";
import { ServiceLineCard } from "@/components/ServiceLineCard";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatNumber } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import { SAMPLE_NAMES, SAMPLE_PATIENTS } from "../sample-data";
import { Demo, Section } from "../Section";

const now = Date.now();
const minutesAgo = (m: number) => new Date(now - m * 60_000).toISOString();

export function CardsSection() {
  const { t } = useTranslation("design");
  const language = useLanguage();
  const n = (v: number) => formatNumber(v, language);
  const services = Object.fromEntries(
    Object.entries(SAMPLE_NAMES).map(([key, name]) => [key, pickName(name, language)]),
  ) as Record<keyof typeof SAMPLE_NAMES, string>;

  return (
    <Section id="cards" title={t("sections.cards")} description={t("descriptions.cards")}>
      <Demo label={t("cards.kpi")} className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          headingLevel="h4"
          label={t("cards.kpiVisits")}
          value={n(148)}
          icon={<Users />}
          trend={{ direction: "up", value: "12%" }}
        />
        <KpiCard
          headingLevel="h4"
          label={t("cards.kpiCollected")}
          value={<MoneyText value="2450000.00" />}
          icon={<Banknote />}
          tone="success"
          trend={{ direction: "flat" }}
        />
        <KpiCard
          headingLevel="h4"
          label={t("cards.kpiPending")}
          value={n(7)}
          icon={<Activity />}
          tone="warning"
          trend={{ direction: "up", value: n(3), upIsGood: false }}
          hint={t("cards.kpiOlderThan", { count: 2 })}
        />
        <KpiCard
          headingLevel="h4"
          label={t("cards.kpiWait")}
          value={t("cards.kpiWaitValue", { count: 18 })}
          icon={<Clock3 />}
          tone="info"
          trend={{ direction: "down", value: "4%", upIsGood: false }}
        />
        <KpiCard headingLevel="h4" label={t("cards.kpiLoading")} value={null} icon={<Users />} loading />
      </Demo>

      <Demo label={t("cards.patient")} className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {SAMPLE_PATIENTS.map((patient, i) => (
          <PatientCard
            key={patient.fileNo}
            patient={patient}
            compact={i === 2}
            actions={
              i === 0 ? (
                <Button size="sm" variant="outline">
                  {t("cards.open")}
                </Button>
              ) : (
                <Button size="icon-sm" variant="ghost" aria-label={t("cards.open")}>
                  <MoreHorizontal />
                </Button>
              )
            }
          />
        ))}
      </Demo>

      <Demo label={t("cards.serviceLine")} className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        <ServiceLineCard
          name={services.consult}
          quantity={1}
          unitPrice="15000.00"
          total="15000.00"
          status="requested"
          orderedBy={services.doctor}
          orderedAt={minutesAgo(12)}
        />
        <ServiceLineCard
          name={services.cbc}
          meta={t("cards.labDept")}
          quantity={1}
          unitPrice="8500.00"
          total="8500.00"
          status="invoiced"
          actions={<Button size="sm">{t("cards.collect")}</Button>}
        />
        <ServiceLineCard
          name={services.amox}
          meta={t("cards.dose")}
          quantity={15}
          unitPrice="316.70"
          total="4750.50"
          status="paid"
          actions={
            <Button size="sm" variant="destructive-soft">
              <X />
              {t("cards.cancel")}
            </Button>
          }
        />
        <ServiceLineCard
          name={services.dressing}
          meta={t("cards.procedureDept")}
          quantity={1}
          unitPrice="6000.00"
          total="6000.00"
          status="performed"
          authorized
        />
        <ServiceLineCard name={services.ecg} quantity={1} unitPrice="12000.00" total="12000.00" status="cancelled" />
        <Demo label={t("cards.doctorView")}>
          <ServiceLineCard
            name={services.cbc}
            meta={t("cards.labDept")}
            quantity={1}
            status="paid"
            actions={<Button size="sm">{t("cards.markDone")}</Button>}
          />
        </Demo>
      </Demo>

      <Demo label={t("cards.basic")} className="max-w-md">
        <Card>
          <CardHeader>
            <CardTitle>{t("cards.basic")}</CardTitle>
            <CardDescription>{t("cards.basicDescription")}</CardDescription>
          </CardHeader>
          <CardContent className="text-sm text-fg">{t("cards.basicBody")}</CardContent>
        </Card>
      </Demo>
    </Section>
  );
}
