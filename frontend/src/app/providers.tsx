import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { Direction } from "radix-ui";
import type { ReactNode } from "react";

import { TooltipProvider } from "@/components/ui/tooltip";
import { useDirection } from "@/lib/i18n-hooks";
import { PreferencesProvider } from "@/lib/use-preferences";

function DirectionBoundary({ children }: { children: ReactNode }) {
  const dir = useDirection();
  return <Direction.Provider dir={dir}>{children}</Direction.Provider>;
}

/** App-wide providers, shared by the real app and component tests. */
export function Providers({ queryClient, children }: { queryClient: QueryClient; children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <PreferencesProvider>
        <DirectionBoundary>
          <TooltipProvider>{children}</TooltipProvider>
        </DirectionBoundary>
      </PreferencesProvider>
    </QueryClientProvider>
  );
}
