import { CircleCheck, WifiOff } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useConnection } from "@/lib/hooks/connection-context";
import { cn } from "@/lib/utils";

/**
 * The two connection notices of a LAN app (D-0014): "can't reach the server" while it does not
 * answer, and "restored" for a few seconds after it does. Quiet and non-blocking: a bar under the
 * top bar, no dialog, nothing disabled behind it (what the user typed stays on the screen).
 * Says what is true and what it means for the user's work, in the reference's plain wording.
 */
export function ConnectionBanner() {
  const { t } = useTranslation();
  const state = useConnection();
  if (state === "connected") return null;
  const down = state === "unreachable";
  const Icon = down ? WifiOff : CircleCheck;
  return (
    <div
      role={down ? "alert" : "status"}
      data-testid="connection-banner"
      data-state={state}
      className={cn(
        "sticky top-16 z-10 mb-4 flex items-start gap-3 rounded-card border px-4 py-3 text-sm print:hidden",
        down
          ? "border-warning-border bg-warning-bg text-warning-fg"
          : "border-success-border bg-success-bg text-success-fg",
      )}
    >
      <Icon className={cn("mt-0.5 size-4 shrink-0", down ? "text-warning" : "text-success")} aria-hidden="true" />
      <div className="min-w-0">
        <p className="font-semibold">{down ? t("connection.unreachableTitle") : t("connection.restoredTitle")}</p>
        <p>{down ? t("connection.unreachableBody") : t("connection.restoredBody")}</p>
      </div>
    </div>
  );
}
