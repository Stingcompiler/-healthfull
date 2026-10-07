import { QueryClient } from "@tanstack/react-query";
import { render, type RenderOptions } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";

import { Providers } from "@/app/providers";
import i18n from "@/i18n";
import type { Language } from "@/lib/preferences";

export function createTestQueryClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
}

/** Renders inside the real app providers (query, preferences, direction, tooltips). */
export async function renderWithProviders(
  ui: ReactElement,
  {
    language = "en",
    queryClient = createTestQueryClient(),
    ...options
  }: RenderOptions & {
    language?: Language;
    queryClient?: QueryClient;
  } = {},
) {
  await i18n.changeLanguage(language);
  // No session in unit tests: the current user is "logged out".
  queryClient.setQueryData(["auth", "me"], null);
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <Providers queryClient={queryClient}>{children}</Providers>
  );
  return { queryClient, ...render(ui, { wrapper: Wrapper, ...options }) };
}
