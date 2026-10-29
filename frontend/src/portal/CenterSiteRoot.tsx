import { PortalLayout } from "./PortalLayout";
import { CenterPage } from "./pages/CenterPage";

/**
 * The center website at the site root `/` for a visitor without a staff session, once the
 * administrator switches it on (ADR 0028 decision 4): the same page and shell as `/portal`.
 */
export function CenterSiteRoot() {
  return (
    <PortalLayout>
      <CenterPage />
    </PortalLayout>
  );
}
