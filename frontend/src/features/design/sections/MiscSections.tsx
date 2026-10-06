import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Can } from "@/components/Can";
import { DateText } from "@/components/DateText";
import { ArrowBack, ArrowNext, ChevronNext, ChevronPrev } from "@/components/icons";
import { KbdCombo } from "@/components/Kbd";
import { MoneyText } from "@/components/MoneyText";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { comboLabels, useShortcut } from "@/lib/hooks/use-shortcut";
import { useLanguage } from "@/lib/i18n-hooks";
import { initials, pickName } from "@/lib/names";
import { THEMES } from "@/lib/preferences";
import { usePreferences } from "@/lib/use-preferences";

import { SAMPLE_PATIENTS } from "../sample-data";
import { Demo, Section } from "../Section";

export function FeedbackSection() {
  const { t } = useTranslation(["design", "errors"]);
  return (
    <Section id="feedback" title={t("sections.feedback")} description={t("descriptions.feedback")}>
      <Demo label={t("sections.feedback")} className="flex flex-wrap gap-2">
        <Button variant="outline" onClick={() => toast.success(t("feedback.successMessage"))}>
          {t("feedback.toastSuccess")}
        </Button>
        <Button variant="outline" onClick={() => toast.info(t("feedback.infoMessage"))}>
          {t("feedback.toastInfo")}
        </Button>
        <Button variant="outline" onClick={() => toast.warning(t("feedback.warningMessage"))}>
          {t("feedback.toastWarning")}
        </Button>
        <Button variant="outline" onClick={() => toast.error(t("errors:NETWORK_ERROR"))}>
          {t("feedback.toastError")}
        </Button>
      </Demo>
      <Demo label={t("feedback.skeleton")}>
        <Card className="max-w-md">
          <div className="flex items-center gap-3">
            <Skeleton className="size-12 rounded-full" />
            <div className="flex flex-1 flex-col gap-2">
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-3 w-1/2" />
            </div>
          </div>
          <Skeleton className="h-20 w-full" />
        </Card>
      </Demo>
    </Section>
  );
}

export function ControlsSection() {
  const { t } = useTranslation("design");
  const language = useLanguage();
  const [notify, setNotify] = useState(true);
  return (
    <Section id="controls" title={t("sections.controls")} description={t("descriptions.controls")}>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Demo label={t("sections.controls")}>
          <Tabs defaultValue="overview">
            <TabsList>
              <TabsTrigger value="overview">{t("controls.tabOverview")}</TabsTrigger>
              <TabsTrigger value="orders">{t("controls.tabOrders")}</TabsTrigger>
              <TabsTrigger value="invoices">{t("controls.tabInvoices")}</TabsTrigger>
            </TabsList>
            <TabsContent value="overview" className="text-sm text-muted">
              {t("controls.tabOverviewBody")}
            </TabsContent>
            <TabsContent value="orders" className="text-sm text-muted">
              {t("controls.tabOrdersBody")}
            </TabsContent>
            <TabsContent value="invoices" className="text-sm text-muted">
              {t("controls.tabInvoicesBody")}
            </TabsContent>
          </Tabs>
        </Demo>

        <Demo label={t("controls.printLabel")}>
          <Card className="gap-4">
            <div className="flex items-center justify-between gap-4">
              <div>
                <Label htmlFor="ds-notify">{t("controls.notifications")}</Label>
                <p className="mt-1 text-xs text-muted">{t("controls.notificationsHint")}</p>
              </div>
              <Switch id="ds-notify" checked={notify} onCheckedChange={setNotify} />
            </div>
            <Separator />
            <RadioGroup defaultValue="thermal" aria-label={t("controls.printLabel")} className="flex flex-wrap gap-5">
              <div className="flex items-center gap-2">
                <RadioGroupItem value="thermal" id="ds-print-thermal" />
                <Label htmlFor="ds-print-thermal" className="font-normal">
                  {t("controls.printThermal")}
                </Label>
              </div>
              <div className="flex items-center gap-2">
                <RadioGroupItem value="a4" id="ds-print-a4" />
                <Label htmlFor="ds-print-a4" className="font-normal">
                  {t("controls.printA4")}
                </Label>
              </div>
            </RadioGroup>
            <Separator />
            <div className="flex flex-wrap gap-5">
              <div className="flex items-center gap-2">
                <Checkbox id="ds-copy" defaultChecked />
                <Label htmlFor="ds-copy" className="font-normal">
                  {t("controls.checkboxLabel")}
                </Label>
              </div>
              <div className="flex items-center gap-2">
                <Checkbox id="ds-partial" checked="indeterminate" />
                <Label htmlFor="ds-partial" className="font-normal">
                  {t("controls.indeterminate")}
                </Label>
              </div>
            </div>
          </Card>
        </Demo>

        <Demo label={t("controls.avatars")} className="flex items-center gap-2">
          {SAMPLE_PATIENTS.map((p, i) => (
            <Avatar key={p.fileNo} className={i === 0 ? "size-11" : i === 1 ? "size-9" : "size-8"}>
              <AvatarFallback className={i === 2 ? "text-xs" : undefined}>
                {initials(pickName({ ar: p.nameAr, en: p.nameEn }, language))}
              </AvatarFallback>
            </Avatar>
          ))}
        </Demo>

        <Demo label={t("controls.scrollArea")}>
          <ScrollArea className="h-40 rounded-card border border-border bg-surface">
            <ul className="divide-y divide-border">
              {Array.from({ length: 12 }, (_, i) => (
                <li key={i} className="px-4 py-2.5 text-sm text-fg">
                  {t("controls.scrollItem", { n: i + 1 })}
                </li>
              ))}
            </ul>
          </ScrollArea>
        </Demo>
      </div>
    </Section>
  );
}

export function FormattingSection() {
  const { t } = useTranslation("design");
  const now = new Date();
  const earlier = new Date(now.getTime() - 3 * 3600_000);
  const rows = [
    { label: t("formatting.positive"), node: <MoneyText value="15000.00" /> },
    { label: t("formatting.negative"), node: <MoneyText value="-2500.00" toneNegative /> },
    { label: t("formatting.signed"), node: <MoneyText value="350.00" signed /> },
    { label: t("formatting.noCurrency"), node: <MoneyText value="4750.50" currency={false} /> },
    { label: t("formatting.large"), node: <MoneyText value="123456789.99" /> },
  ];
  const dates = [
    { label: t("formatting.date"), node: <DateText value={now} /> },
    { label: t("formatting.datetime"), node: <DateText value={now} format="datetime" /> },
    { label: t("formatting.time"), node: <DateText value={now} format="time" /> },
    { label: t("formatting.long"), node: <DateText value={now} format="long" /> },
    { label: t("formatting.relative"), node: <DateText value={earlier} format="relative" /> },
  ];
  return (
    <Section id="formatting" title={t("sections.formatting")} description={t("descriptions.formatting")}>
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        {[
          { title: t("formatting.money"), items: rows },
          { title: t("formatting.dates"), items: dates },
        ].map((group) => (
          <Demo key={group.title} label={group.title}>
            <Card className="gap-0 p-0 md:p-0">
              <dl className="divide-y divide-border">
                {group.items.map((item) => (
                  <div key={item.label} className="flex items-center justify-between gap-4 px-4 py-3 text-sm">
                    <dt className="text-muted">{item.label}</dt>
                    <dd className="text-end text-fg">{item.node}</dd>
                  </div>
                ))}
              </dl>
            </Card>
          </Demo>
        ))}
      </div>
    </Section>
  );
}

const CYCLE_THEME = "alt+t";

export function ShortcutsSection() {
  const { t } = useTranslation("design");
  const { theme, setTheme } = usePreferences();
  const [last, setLast] = useState<string | null>(null);

  useShortcut(CYCLE_THEME, () => {
    const next = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length] ?? "light";
    setTheme(next);
    setLast(comboLabels(CYCLE_THEME).join(" "));
  });

  return (
    <Section id="shortcuts" title={t("sections.shortcuts")} description={t("descriptions.shortcuts")}>
      <Card className="max-w-xl gap-0 p-0 md:p-0">
        <dl className="divide-y divide-border">
          <div className="flex items-center justify-between gap-4 px-4 py-3 text-sm">
            <dt className="text-fg">{t("shortcuts.quickSearch")}</dt>
            <dd>
              <KbdCombo combo="mod+k" />
            </dd>
          </div>
          <div className="flex items-center justify-between gap-4 px-4 py-3 text-sm">
            <dt className="text-fg">{t("shortcuts.cycleTheme")}</dt>
            <dd>
              <KbdCombo combo={CYCLE_THEME} />
            </dd>
          </div>
        </dl>
      </Card>
      <p className="text-sm text-muted" aria-live="polite">
        {last ? t("shortcuts.pressed", { keys: last }) : t("shortcuts.nonePressed")}
      </p>
    </Section>
  );
}

export function AccessSection() {
  const { t } = useTranslation("design");
  return (
    <Section id="access" title={t("sections.access")} description={t("descriptions.access")}>
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <Demo label={t("access.canTitle")} className="flex flex-col items-start gap-3">
          <Can permission="billing.approve_invoice" fallback={<Badge variant="neutral">{t("access.canDenied")}</Badge>}>
            <Button>{t("access.approveInvoice")}</Button>
            <p className="text-xs text-muted">{t("access.canGranted")}</p>
          </Can>
        </Demo>
        <Demo label={t("access.directionTitle")} className="flex flex-wrap gap-2">
          <Button variant="outline">
            <ChevronPrev />
            {t("access.previous")}
          </Button>
          <Button variant="outline">
            {t("access.next")}
            <ChevronNext />
          </Button>
          <Button variant="ghost">
            <ArrowBack />
            {t("access.back")}
          </Button>
          <Button>
            {t("access.forward")}
            <ArrowNext />
          </Button>
        </Demo>
      </div>
    </Section>
  );
}
