import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

import "@/i18n";

import { installMatchMedia } from "./match-media";

installMatchMedia();

// jsdom does no layout and has no scrollIntoView; components call it to reveal errors.
if (!("scrollIntoView" in Element.prototype)) {
  Object.defineProperty(Element.prototype, "scrollIntoView", { value: () => undefined, writable: true });
}

afterEach(() => {
  cleanup();
});
