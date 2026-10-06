import { Archive, Copy, Eye, FilePlus2, MoreHorizontal, Printer, Trash2, Wallet } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { KbdCombo } from "@/components/Kbd";
import { ReasonDialog, type ReasonOption } from "@/components/ReasonDialog";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from "@/components/ui/command";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ApiError } from "@/lib/api/errors";

import { Demo, Section } from "../Section";

const REASON_CODES = ["patientRefused", "doctorChanged", "duplicate", "sampleRejected"] as const;

export function OverlaysSection() {
  const { t } = useTranslation(["design", "common"]);
  const [reasonOpen, setReasonOpen] = useState(false);
  const [recorded, setRecorded] = useState<string | null>(null);

  const reasons: ReasonOption[] = REASON_CODES.map((code) => ({ code, label: t(`overlays.reasons.${code}`) }));

  return (
    <Section id="overlays" title={t("sections.overlays")} description={t("descriptions.overlays")}>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Demo label={t("overlays.dialog")} className="flex flex-wrap gap-2">
          <Dialog>
            <DialogTrigger asChild>
              <Button variant="outline">{t("overlays.dialog")}</Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>{t("overlays.dialogTitle")}</DialogTitle>
                <DialogDescription>{t("overlays.dialogBody")}</DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <DialogClose asChild>
                  <Button variant="outline">{t("common:actions.close")}</Button>
                </DialogClose>
                <Button>
                  <Printer />
                  {t("common:actions.print")}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>

          <Sheet>
            <SheetTrigger asChild>
              <Button variant="outline">{t("overlays.sheetEnd")}</Button>
            </SheetTrigger>
            <SheetContent side="end">
              <SheetHeader>
                <SheetTitle>{t("overlays.sheetTitle")}</SheetTitle>
                <SheetDescription>{t("overlays.sheetBody")}</SheetDescription>
              </SheetHeader>
              <SheetBody />
              <SheetFooter>
                <Button>{t("common:actions.save")}</Button>
              </SheetFooter>
            </SheetContent>
          </Sheet>

          <Sheet>
            <SheetTrigger asChild>
              <Button variant="outline">{t("overlays.sheetBottom")}</Button>
            </SheetTrigger>
            <SheetContent side="bottom">
              <SheetHeader>
                <SheetTitle>{t("overlays.sheetTitle")}</SheetTitle>
                <SheetDescription>{t("overlays.sheetBody")}</SheetDescription>
              </SheetHeader>
              <SheetFooter>
                <Button className="w-full">{t("common:actions.continue")}</Button>
              </SheetFooter>
            </SheetContent>
          </Sheet>
        </Demo>

        <Demo label={t("overlays.reason")} className="flex flex-col items-start gap-2">
          <Button
            variant="destructive-soft"
            onClick={() => {
              setReasonOpen(true);
            }}
          >
            {t("overlays.reasonTitle")}
          </Button>
          <ReasonDialog
            open={reasonOpen}
            onOpenChange={setReasonOpen}
            title={t("overlays.reasonTitle")}
            description={t("overlays.reasonDescription")}
            reasons={reasons}
            destructive
            onSubmit={({ code, note }) => {
              const label = reasons.find((r) => r.code === code)?.label ?? code;
              setRecorded(t("overlays.reasonResult", { code: label, note }));
            }}
          />
          {recorded ? (
            <p className="text-sm text-muted" aria-live="polite">
              {recorded}
            </p>
          ) : null}
        </Demo>

        <Demo label={t("overlays.confirm")} className="flex flex-wrap gap-2">
          <ConfirmDialog
            trigger={<Button>{t("overlays.confirmAction")}</Button>}
            title={t("overlays.confirmTitle")}
            description={t("overlays.confirmDescription")}
            confirmLabel={t("overlays.confirmAction")}
            onConfirm={async () => {
              await new Promise((resolve) => setTimeout(resolve, 600));
              toast.success(t("overlays.confirmed"));
            }}
          />
          <ConfirmDialog
            trigger={<Button variant="destructive">{t("overlays.confirmDestructive")}</Button>}
            title={t("overlays.destructiveTitle")}
            description={t("overlays.destructiveDescription")}
            confirmLabel={t("overlays.destructiveAction")}
            destructive
            onConfirm={() => {
              toast.success(t("overlays.confirmed"));
            }}
          />
          <ConfirmDialog
            trigger={<Button variant="outline">{t("overlays.failingConfirm")}</Button>}
            title={t("overlays.confirmTitle")}
            description={t("overlays.confirmDescription")}
            onConfirm={() => {
              throw new ApiError(409, { code: "INVOICE_FROZEN", message: "", details: {} });
            }}
          />
        </Demo>

        <Demo label={t("overlays.dropdown")} className="flex flex-wrap items-center gap-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="icon" aria-label={t("overlays.menuLabel")}>
                <MoreHorizontal />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-52">
              <DropdownMenuLabel>{t("overlays.menuLabel")}</DropdownMenuLabel>
              <DropdownMenuItem>
                <Eye />
                {t("overlays.menuView")}
              </DropdownMenuItem>
              <DropdownMenuItem>
                <Copy />
                {t("overlays.menuDuplicate")}
                <DropdownMenuShortcut>
                  <KbdCombo combo="mod+d" />
                </DropdownMenuShortcut>
              </DropdownMenuItem>
              <DropdownMenuItem disabled>
                <Archive />
                {t("overlays.menuArchive")}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="destructive">
                <Trash2 />
                {t("overlays.menuDelete")}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

          <Popover>
            <PopoverTrigger asChild>
              <Button variant="outline">{t("overlays.popover")}</Button>
            </PopoverTrigger>
            <PopoverContent>
              <p className="text-sm font-semibold text-fg">{t("overlays.popoverTitle")}</p>
              <p className="mt-1 text-sm text-muted">{t("overlays.popoverBody")}</p>
            </PopoverContent>
          </Popover>

          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="outline">{t("overlays.tooltip")}</Button>
            </TooltipTrigger>
            <TooltipContent>{t("overlays.tooltipBody")}</TooltipContent>
          </Tooltip>
        </Demo>

        <Demo label={t("overlays.command")}>
          <Command className="card-surface max-w-md">
            <CommandInput placeholder={t("overlays.commandPlaceholder")} />
            <CommandList>
              <CommandEmpty>{t("common:search.noResults")}</CommandEmpty>
              <CommandGroup>
                <CommandItem>
                  <FilePlus2 />
                  {t("overlays.commandNewVisit")}
                  <CommandShortcut>
                    <KbdCombo combo="f2" />
                  </CommandShortcut>
                </CommandItem>
                <CommandItem>
                  <Wallet />
                  {t("overlays.commandOpenShift")}
                </CommandItem>
                <CommandItem>
                  <Printer />
                  {t("overlays.commandPrintReceipt")}
                  <CommandShortcut>
                    <KbdCombo combo="mod+p" />
                  </CommandShortcut>
                </CommandItem>
              </CommandGroup>
            </CommandList>
          </Command>
        </Demo>
      </div>
    </Section>
  );
}
