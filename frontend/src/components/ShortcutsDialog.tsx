import { Keyboard } from "lucide-react";
import { useState } from "react";

import { KbdCombo } from "@/components/Kbd";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useShortcut } from "@/lib/hooks/use-shortcut";

/** `?` opens the list on every screen that documents its shortcuts. */
export const HELP_SHORTCUT = "shift+/";

export interface ShortcutRow {
  combo: string;
  label: string;
}

/**
 * The documented keyboard shortcuts of a high-volume desk (Design Reference 2.2 section 9: the
 * shortcut set is fixed per product and listed where users can find it). The button is hidden on
 * phones, where there is no keyboard. Strings come from the caller's i18n namespace.
 */
export function ShortcutsDialog({
  rows,
  buttonLabel,
  title,
  description,
}: {
  rows: readonly ShortcutRow[];
  buttonLabel: string;
  title: string;
  description: string;
}) {
  const [open, setOpen] = useState(false);
  useShortcut(HELP_SHORTCUT, () => {
    setOpen(true);
  });
  return (
    <>
      <Button
        variant="outline"
        size="sm"
        onClick={() => {
          setOpen(true);
        }}
        className="hidden md:inline-flex"
      >
        <Keyboard aria-hidden="true" />
        {buttonLabel}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>{description}</DialogDescription>
          </DialogHeader>
          <dl className="grid gap-2 text-sm">
            {rows.map((row) => (
              <div key={row.combo} className="flex items-center justify-between gap-4">
                <dt>{row.label}</dt>
                <dd>
                  <KbdCombo combo={row.combo} />
                </dd>
              </div>
            ))}
          </dl>
        </DialogContent>
      </Dialog>
    </>
  );
}
