import { MoreHorizontal, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { DecisionList, DecisionRow } from "@/components/DecisionList";
import { KpiCard, KpiGroup } from "@/components/KpiCard";
import { MoneyText } from "@/components/MoneyText";
import { PatientCard } from "@/components/PatientCard";
import { ServiceLineCard } from "@/components/ServiceLineCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatNumber } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import { InvoiceLines } from "@/features/cashier/components/InvoiceLines";

import { SAMPLE_NAMES, SAMPLE_PATIENTS } from "../sample-data";
import { Demo, Section } from "../Section";

const now = Date.now();
const minutesAgo = (m: number) => new Date(now - m * 60_000).toISOString();

export function CardsSection() {
  const { t } = useTranslation("design");
  const { t: tc } = useTranslation("cashier");
  const language = useLanguage();
  const n = (v: number) => formatNumber(v, language);
  const services = Object.fromEntries(
    Object.entries(SAMPLE_NAMES).map(([key, name]) => [key, pickName(name, language)]),
  ) as Record<keyof typeof SAMPLE_NAMES, string>;

  return (
    <Section id="cards" title={t("sections.cards")} description={t("descriptions.cards")}>
      <Demo label={t("cards.kpi")} className="flex flex-col gap-4">
        <KpiGroup className="md:grid-cols-3 xl:grid-cols-[minmax(0,1.6fr)_repeat(3,minmax(0,1fr))]">
          <KpiCard
            bare
            hero
            headingLevel="h4"
            className="col-span-2 md:col-span-3 xl:col-span-1"
            label={t("cards.kpiCollected")}
            value={<MoneyText value="2450000.00" currency={false} />}
            trend={{ direction: "up", value: "12%" }}
          />
          <KpiCard
            bare
            headingLevel="h4"
            label={t("cards.kpiPending")}
            value={<MoneyText value="447555.00" currency={false} />}
            tone="warning"
            hint={t("cards.kpiOlderThan", { count: 2 })}
          />
          <KpiCard bare headingLevel="h4" label={t("cards.kpiVisits")} value={n(148)} />
          <KpiCard
            bare
            headingLevel="h4"
            className="col-span-2 md:col-span-1"
            label={t("cards.kpiWait")}
            value={t("cards.kpiWaitValue", { count: 18 })}
            trend={{ direction: "down", value: "4%", upIsGood: false }}
          />
        </KpiGroup>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <KpiCard headingLevel="h4" label={t("cards.kpiVisits")} value={n(148)} trend={{ direction: "flat" }} />
          <KpiCard headingLevel="h4" label={t("cards.kpiLoading")} value={null} loading />
        </div>
      </Demo>

      <Demo label={t("cards.decisions")}>
        <DecisionList>
          <DecisionRow
            tone="danger"
            count={n(1)}
            title={t("cards.decisionDanger")}
            detail={<MoneyText value="-500.00" />}
            action={
              <Button size="sm" variant="outline">
                {t("cards.open")}
              </Button>
            }
          />
          <DecisionRow
            tone="warning"
            count={n(11)}
            title={t("cards.decisionWarning")}
            action={
              <Button size="sm" variant="outline">
                {t("cards.open")}
              </Button>
            }
          />
          <DecisionRow tone="info" count={n(57)} title={t("cards.decisionInfo")} />
        </DecisionList>
      </Demo>

      <Demo label={t("cards.invoiceLines")}>
        <div className="card-surface overflow-hidden">
          <InvoiceLines
            caption={t("cards.invoiceLines")}
            lines={[
              {
                id: 1,
                name: services.consult,
                meta: <Badge variant="info">{t("cards.payerSample")}</Badge>,
                quantity: 1,
                gross: "15000.00",
                discount: "0.00",
                payerShare: "10500.00",
                patientShare: "4500.00",
                status: "invoiced",
                actions: <Button size="sm">{t("cards.collect")}</Button>,
              },
              {
                id: 2,
                name: services.cbc,
                meta: (
                  <>
                    <Badge variant="info">{t("cards.payerSample")}</Badge>
                    <Badge variant="warning">{tc("invoice.needsPreapproval")}</Badge>
                  </>
                ),
                quantity: 1,
                gross: "8500.00",
                discount: "0.00",
                payerShare: "0.00",
                patientShare: "8500.00",
                status: "requested",
                needsDecision: true,
              },
              {
                id: 3,
                name: services.ecg,
                quantity: 1,
                gross: "12000.00",
                discount: "0.00",
                payerShare: "0.00",
                patientShare: "12000.00",
                status: "cancelled",
              },
            ]}
          />
        </div>
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
