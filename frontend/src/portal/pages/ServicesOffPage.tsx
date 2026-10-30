import { Link } from "@tanstack/react-router";
import { CalendarPlus } from "lucide-react";
import { useTranslation } from "react-i18next";

import { CenterIdentity } from "@/components/CenterIdentity";
import { EmptyState } from "@/components/EmptyState";
import { Button } from "@/components/ui/button";
import { useDocumentTitle } from "@/lib/hooks/use-document-title";
import { getSiteConfig } from "@/lib/site";

/**
 * `/portal` while the center website and patient sign-in are both switched off (ADR 0029, plan
 * D4): one line and the center's name and logo (`center-identity`). The portal footer keeps
 * the staff sign-in link. Guest booking on (ADR 0029 D) still offers "Book online".
 */
export function ServicesOffPage() {
  const { t } = useTranslation("portal");
  useDocumentTitle(t("off.title"));
  return (
    <div className="grid gap-6" data-testid="portal-services-off">
      <div className="flex justify-center">
        <CenterIdentity size="lg" />
      </div>
      <EmptyState
        title={t("off.title")}
        description={t("off.body")}
        action={
          getSiteConfig().guestBooking ? (
            <Button asChild size="lg">
              <Link to="/portal/book" data-testid="off-book">
                <CalendarPlus aria-hidden="true" />
                {t("center.bookOnline")}
              </Link>
            </Button>
          ) : undefined
        }
      />
    </div>
  );
}
