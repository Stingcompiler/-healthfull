import { useNavigate } from "@tanstack/react-router";

import { usePermission } from "@/lib/auth/hooks";
import { useShortcut } from "@/lib/hooks/use-shortcut";

/** F2 searches (the scan box), F10 opens returns: the same keys as the cashier (Design Reference 2.2 section 9). */
export const SEARCH_SHORTCUT = "f2";
export const RETURNS_SHORTCUT = "f10";

/** F10 opens the dispense returns screen from any pharmacy desk screen. */
export function useReturnsShortcut(): void {
  const navigate = useNavigate();
  const canReturn = usePermission("pharmacy.dispense");
  useShortcut(
    RETURNS_SHORTCUT,
    () => {
      void navigate({ to: "/pharmacy/returns" });
    },
    { enabled: canReturn, allowInInputs: true },
  );
}
