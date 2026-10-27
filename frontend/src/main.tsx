import "@/design/fonts";
import "@/design/index.css";
import "@/i18n";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "@/app/App";
import { loadSiteConfig } from "@/lib/site";

const container = document.getElementById("root");
if (!container) throw new Error("#root element missing from index.html");

// One short request before the first render, so every redirect to the sign-in page already knows
// whether /login is the product page (ADR 0027). It never blocks for long and never fails.
void loadSiteConfig().then(() => {
  createRoot(container).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
});
