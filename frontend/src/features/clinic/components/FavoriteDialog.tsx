import { Star } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { AlertCard } from "@/components/AlertCard";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useTranslateError } from "@/lib/api/translate-error";
import { useLanguage } from "@/lib/i18n-hooks";

import { useCreateFavorite } from "../api";
import { toFavorite, type DraftItem } from "../draft";

/** Save the order being written as one of the doctor's favorites (FEATURES 3.6). */
export function FavoriteDialog({
  open,
  onOpenChange,
  items,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  items: readonly DraftItem[];
}) {
  const { t } = useTranslation("clinic");
  const { t: tc } = useTranslation();
  const language = useLanguage();
  const create = useCreateFavorite();
  const translateError = useTranslateError();
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const save = () => {
    setError(null);
    create.mutate(toFavorite(name.trim(), items, language), {
      onSuccess: () => {
        toast.success(t("orderSets.savedToast"));
        setName("");
        onOpenChange(false);
      },
      onError: (e) => {
        setError(translateError(e));
      },
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Star className="size-5 text-muted" aria-hidden="true" />
            {t("orderSets.saveTitle")}
          </DialogTitle>
          <DialogDescription>{t("orderSets.saveDescription", { count: items.length })}</DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim()) save();
          }}
        >
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="favorite-name">{t("orderSets.name")}</Label>
            <Input
              id="favorite-name"
              value={name}
              maxLength={150}
              onChange={(e) => setName(e.target.value)}
              autoFocus
            />
          </div>
          {error ? (
            <AlertCard variant="danger" live title={t("orderSets.saveError")}>
              {error}
            </AlertCard>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {tc("actions.cancel")}
            </Button>
            <Button type="submit" loading={create.isPending} disabled={!name.trim()}>
              {t("orderSets.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
