import { Layers, Star, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import { useDeleteFavorite, useOrderSets } from "../api";
import type { OrderSet } from "../types";
import { QueryError } from "./QueryError";

/** Shared order sets and the doctor's favorites (FEATURES 3.6): one click adds every item. */
export function OrderSetPicker({ onPick }: { onPick: (set: OrderSet) => void }) {
  const { t } = useTranslation("clinic");
  const language = useLanguage();
  const sets = useOrderSets();
  const remove = useDeleteFavorite();
  const translateError = useTranslateError();

  const shared = (sets.data ?? []).filter((s) => !s.personal);
  const favorites = (sets.data ?? []).filter((s) => s.personal);

  return (
    <div className="flex min-w-0 flex-col gap-3" data-testid="order-sets">
      {sets.isError ? (
        <QueryError
          title={t("orderSets.loadError")}
          error={sets.error}
          onRetry={() => void sets.refetch()}
          retrying={sets.isFetching}
        />
      ) : !sets.data ? (
        <Skeleton className="h-20" />
      ) : (
        <>
          <Group title={t("orderSets.favorites")} icon={<Star />} empty={t("orderSets.noFavorites")}>
            {favorites.map((set) => (
              <li key={set.id} className="flex items-center">
                <Button size="sm" variant="outline" className="rounded-e-none" onClick={() => onPick(set)}>
                  {pickName({ ar: set.name_ar, en: set.name_en }, language)}
                  <span className="tabular text-xs text-muted">({set.items.length})</span>
                </Button>
                <Button
                  size="icon-sm"
                  variant="outline"
                  className="-ms-px rounded-s-none"
                  aria-label={t("orderSets.remove", { name: pickName({ ar: set.name_ar, en: set.name_en }, language) })}
                  onClick={() =>
                    remove.mutate(set.id, {
                      onSuccess: () => toast.success(t("orderSets.removedToast")),
                      onError: (e) => toast.error(translateError(e)),
                    })
                  }
                >
                  <X aria-hidden="true" />
                </Button>
              </li>
            ))}
          </Group>
          <Group title={t("orderSets.shared")} icon={<Layers />} empty={t("orderSets.noShared")}>
            {shared.map((set) => (
              <li key={set.id}>
                <Button size="sm" variant="outline" onClick={() => onPick(set)}>
                  {pickName({ ar: set.name_ar, en: set.name_en }, language)}
                  <span className="tabular text-xs text-muted">({set.items.length})</span>
                </Button>
              </li>
            ))}
          </Group>
        </>
      )}
    </div>
  );
}

function Group({
  title,
  icon,
  empty,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  empty: string;
  children: React.ReactNode[];
}) {
  return (
    <div className="flex flex-col gap-2">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold text-fg">
        <span className="text-muted [&_svg]:size-4" aria-hidden="true">
          {icon}
        </span>
        {title}
      </h3>
      {children.length === 0 ? (
        <p className="text-xs text-muted">{empty}</p>
      ) : (
        <ul className="flex flex-wrap gap-2">{children}</ul>
      )}
    </div>
  );
}
