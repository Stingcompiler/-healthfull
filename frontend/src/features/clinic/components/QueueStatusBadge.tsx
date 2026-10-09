import { CheckCheck, Clock3, Megaphone, Stethoscope, UserX, XCircle, type LucideIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";

import type { QueueEntry } from "../types";

type QueueStatus = QueueEntry["status"];

const STYLE: Record<
  QueueStatus,
  { variant: "neutral" | "info" | "warning" | "success" | "outline" | "danger"; icon: LucideIcon }
> = {
  waiting: { variant: "neutral", icon: Clock3 },
  called: { variant: "info", icon: Megaphone },
  in_progress: { variant: "warning", icon: Stethoscope },
  done: { variant: "success", icon: CheckCheck },
  no_show: { variant: "outline", icon: UserX },
  cancelled: { variant: "danger", icon: XCircle },
};

/** A queue entry's status: icon plus text, never color alone. */
export function QueueStatusBadge({ status }: { status: QueueStatus }) {
  const { t } = useTranslation("clinic");
  const style = STYLE[status];
  const Icon = style.icon;
  return (
    <Badge variant={style.variant} data-queue-status={status}>
      <Icon aria-hidden="true" />
      {t(`queueStatus.${status}`)}
    </Badge>
  );
}
