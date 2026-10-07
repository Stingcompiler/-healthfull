import { RouterProvider } from "@tanstack/react-router";

import { Providers } from "./providers";
import { queryClient, router } from "./router";

export function App() {
  return (
    <Providers queryClient={queryClient}>
      <RouterProvider router={router} />
    </Providers>
  );
}
