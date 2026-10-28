import { lazy, Suspense } from "react";

// The product page (its code, styles and screenshots) is fetched only where the deployment turns it on.
const MarketingPage = lazy(() =>
  import("@/features/marketing/MarketingPage").then((module) => ({ default: module.MarketingPage })),
);

export function LazyMarketingPage() {
  return (
    <Suspense fallback={null}>
      <MarketingPage />
    </Suspense>
  );
}
