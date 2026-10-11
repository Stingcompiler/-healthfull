import { createRoute, type AnyRoute } from "@tanstack/react-router";

import { AdjustmentsPage } from "./pages/AdjustmentsPage";
import { CountPage } from "./pages/CountPage";
import { CountsPage } from "./pages/CountsPage";
import { ExpiryPage } from "./pages/ExpiryPage";
import { ItemPage } from "./pages/ItemPage";
import { ItemsPage } from "./pages/ItemsPage";
import { LowStockPage } from "./pages/LowStockPage";
import { PharmacyPage } from "./pages/PharmacyPage";
import { ReceiptsPage } from "./pages/ReceiptsPage";
import { ReturnsPage } from "./pages/ReturnsPage";
import { SalePage } from "./pages/SalePage";
import { TransfersPage } from "./pages/TransfersPage";

/** pharmacy module routes, mounted under the authenticated app layout. */
export function routes<TParent extends AnyRoute>(parent: TParent) {
  const index = createRoute({ getParentRoute: () => parent, path: "/pharmacy", component: PharmacyPage });
  const sale = createRoute({ getParentRoute: () => parent, path: "/pharmacy/sale", component: SalePage });
  const items = createRoute({ getParentRoute: () => parent, path: "/pharmacy/items", component: ItemsPage });
  const item = createRoute({ getParentRoute: () => parent, path: "/pharmacy/items/$itemId", component: ItemPage });
  const receipts = createRoute({ getParentRoute: () => parent, path: "/pharmacy/receipts", component: ReceiptsPage });
  const adjustments = createRoute({
    getParentRoute: () => parent,
    path: "/pharmacy/adjustments",
    component: AdjustmentsPage,
  });
  const counts = createRoute({ getParentRoute: () => parent, path: "/pharmacy/counts", component: CountsPage });
  const count = createRoute({ getParentRoute: () => parent, path: "/pharmacy/counts/$countId", component: CountPage });
  const transfers = createRoute({
    getParentRoute: () => parent,
    path: "/pharmacy/transfers",
    component: TransfersPage,
  });
  const expiry = createRoute({ getParentRoute: () => parent, path: "/pharmacy/expiry", component: ExpiryPage });
  const lowStock = createRoute({ getParentRoute: () => parent, path: "/pharmacy/low-stock", component: LowStockPage });
  const returns = createRoute({ getParentRoute: () => parent, path: "/pharmacy/returns", component: ReturnsPage });
  return [
    index,
    sale,
    items,
    item,
    receipts,
    adjustments,
    counts,
    count,
    transfers,
    expiry,
    lowStock,
    returns,
  ] as const;
}
