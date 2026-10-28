/**
 * The public center page at the portal's door: a signed-out phone visitor sees the center,
 * today's status, hours, doctors with clinic days, active notices and plain contact links, and
 * one repeated action that leads to sign-in. The administrator edits the page from
 * /administration/center-page (a notice, a hidden doctor) and the public page follows.
 */
import { expect, test, type Browser, type Page } from "@playwright/test";

import { ADMIN_STATE } from "../../fixtures/state";
import {
  apiAs,
  expectNoHorizontalScroll,
  setPrefs,
  snap,
  tr,
  type Lang,
  type Theme,
} from "../../helpers";
import { LANG, phonePage, portalPatient, signInPortal, t } from "./kit";

interface CenterPageSettings {
  hidden_doctor_ids: number[];
  [key: string]: unknown;
}

interface PublicPage {
  name_en: string;
  doctors: { id: number; name_en: string }[];
  announcements: { title_en: string }[];
}

interface Payload {
  name_ar: string;
  name_en: string;
  about_ar: string;
  about_en: string;
  address: string;
  directions_ar: string;
  directions_en: string;
  phone: string;
  phone_uri: string;
  whatsapp: string;
  email: string;
  logo_url: string | null;
  today: {
    weekday: number;
    state: string;
    opens: string | null;
    closes: string | null;
  } | null;
  hours: {
    weekday: number;
    closed: boolean;
    opens: string | null;
    closes: string | null;
  }[];
  departments: { id: number; name_ar: string; name_en: string }[];
  doctors: object[];
  announcements: object[];
}

const DAYS = [0, 1, 2, 3, 4, 5, 6];
const doctor = (
  id: number,
  ar: string,
  en: string,
  spec: [string, string],
  dept: [string, string],
  days: [number[], string, string][],
) => ({
  id,
  name_ar: ar,
  name_en: en,
  specialty_ar: spec[0],
  specialty_en: spec[1],
  department_id: id,
  department_ar: dept[0],
  department_en: dept[1],
  clinic_days: days.flatMap(([weekdays, starts, ends]) =>
    weekdays.map((weekday) => ({ weekday, starts, ends })),
  ),
});

/** A fully filled center page (Wednesday, open now); the API answer is replaced in the browser. */
const FULL: Payload = {
  name_ar: "مركز النور الطبي",
  name_en: "Al Noor Medical Center",
  about_ar: "رعاية طبية متكاملة لأسرتك في قلب المدينة.",
  about_en: "Complete family care in the heart of the city.",
  address: "Street 15, Al Amarat, Khartoum",
  directions_ar: "بجوار صيدلية الأمل، الدور الأرضي",
  directions_en: "Next to Al Amal Pharmacy, ground floor",
  phone: "+249 91 123 4567",
  phone_uri: "tel:+249911234567",
  whatsapp: "249911234567",
  email: "info@alnoor.example",
  logo_url: null,
  today: { weekday: 2, state: "open", opens: "08:00", closes: "20:00" },
  hours: DAYS.map((weekday) => ({
    weekday,
    closed: weekday === 4,
    opens: weekday === 4 ? null : "08:00",
    closes: weekday === 4 ? null : weekday === 5 ? "14:00" : "20:00",
  })),
  departments: [
    { id: 1, name_ar: "الباطنية", name_en: "Internal medicine" },
    { id: 2, name_ar: "الأطفال", name_en: "Pediatrics" },
    { id: 3, name_ar: "النساء والتوليد", name_en: "Obstetrics and gynecology" },
    { id: 4, name_ar: "الأسنان", name_en: "Dental" },
  ],
  doctors: [
    doctor(
      1,
      "د. أمل حسن",
      "Dr. Amal Hassan",
      ["باطنية", "Internist"],
      ["الباطنية", "Internal medicine"],
      [
        [[5, 0, 2], "08:00", "14:00"],
        [[1], "16:00", "20:00"],
      ],
    ),
    doctor(
      2,
      "د. خالد عمر",
      "Dr. Khaled Omer",
      ["أطفال", "Pediatrician"],
      ["الأطفال", "Pediatrics"],
      [[[6, 1, 3], "09:00", "13:00"]],
    ),
    doctor(
      3,
      "د. سلمى إبراهيم",
      "Dr. Salma Ibrahim",
      ["نساء وتوليد", "Gynecologist"],
      ["النساء والتوليد", "Obstetrics and gynecology"],
      [[[0, 3], "10:00", "15:00"]],
    ),
    doctor(
      4,
      "د. محمد الطيب",
      "Dr. Mohamed Eltayeb",
      ["أسنان", "Dentist"],
      ["الأسنان", "Dental"],
      [[[5, 6, 0, 1, 2, 3], "16:00", "20:00"]],
    ),
  ],
  announcements: [
    {
      id: 1,
      title_ar: "مواعيد العيد",
      title_en: "Holiday hours",
      body_ar: "يعمل المركز بنصف دوام خلال أيام العيد.",
      body_en: "The center works half days during the holiday.",
      starts_on: "2026-10-01",
      ends_on: "2026-11-30",
    },
  ],
};

/** The production shape that looked unfinished: one doctor, one department, nothing else. */
const SPARSE: Payload = {
  ...FULL,
  about_ar: "",
  about_en: "",
  address: "",
  directions_ar: "",
  directions_en: "",
  phone: "",
  phone_uri: "",
  whatsapp: "",
  email: "",
  today: null,
  hours: [],
  departments: FULL.departments.slice(0, 1),
  doctors: FULL.doctors.slice(0, 1),
  announcements: [],
};

/** Name only. */
const EMPTY: Payload = { ...SPARSE, departments: [], doctors: [] };

/** Opens /portal signed out with the API answer replaced by `payload`, at a size, theme and language. */
async function openCenter(
  browser: Browser,
  size: { width: number; height: number },
  theme: Theme,
  lang: Lang,
  payload: Payload,
): Promise<Page> {
  const context = await browser.newContext({ viewport: size });
  const page = await context.newPage();
  await setPrefs(page, { theme, lang });
  await page.route("**/api/portal/center-page", (route) =>
    route.fulfill({ json: payload }),
  );
  await page.goto("/portal");
  await expect(page.getByTestId("center-hero")).toBeVisible();
  await expect(
    page.locator("#main").getByRole("heading", { level: 1 }),
  ).toHaveText(lang === "ar" ? payload.name_ar : payload.name_en);
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  await page.waitForLoadState("networkidle");
  return page;
}

test.describe("@portal center page", () => {
  test.describe.configure({ timeout: 120_000 });

  test("a signed-out visitor sees the center and one way in", async ({
    browser,
  }) => {
    const page = await phonePage(browser);
    const publicPage = (await (
      await page.context().request.get("/api/portal/center-page")
    ).json()) as PublicPage;
    await page.goto("/portal");
    const main = page.locator("#main");
    await expect(main.getByRole("heading", { level: 1 })).toHaveText(
      publicPage.name_en || t("appShortName"),
    );
    await expect(page.getByTestId("center-today")).toBeVisible();
    await expect(page.getByTestId("center-hours")).toBeVisible();
    await expect(page.getByTestId("center-doctor").first()).toBeVisible();
    await expect(page.getByTestId("center-announcement").first()).toBeVisible();
    // Contact links are plain links: a call and a WhatsApp chat, nothing fetched from outside.
    await expect(page.getByTestId("center-whatsapp")).toHaveAttribute(
      "href",
      /^https:\/\/wa\.me\/\d{8,15}$/,
    );
    // The one action, in the hero and at the end, plus the phone's sticky bottom bar. The header
    // copy is for tablets and up: a phone has the bar instead.
    const actions = page.getByTestId("center-sign-in");
    await expect(actions).toHaveCount(2);
    await expect(actions.first()).toHaveText(t("portal:center.signIn"));
    await expect(page.getByTestId("center-sticky-cta")).toBeVisible();
    await expect(page.getByTestId("portal-header-sign-in")).toBeHidden();
    await expectNoHorizontalScroll(page);
    await actions.first().click();
    await expect(page).toHaveURL(/\/portal\/sign-in$/);
    await expect(page.getByTestId("portal-login")).toBeVisible();
    await expect(page.getByTestId("portal-header-sign-in")).toHaveCount(0);
  });

  test("the identity appears once, with one header brand and labelled controls", async ({
    browser,
  }) => {
    const page = await openCenter(
      browser,
      { width: 1280, height: 800 },
      "light",
      "en",
      FULL,
    );
    // The name is the hero's h1 only: the header keeps the compact portal brand.
    await expect(
      page.locator("#main").getByRole("heading", { level: 1 }),
    ).toHaveText(FULL.name_en);
    await expect(page.getByTestId("portal-brand")).not.toContainText(
      FULL.name_en,
    );
    await expect(page.getByTestId("portal-brand")).toContainText(
      t("portal:brand"),
    );
    await expect(page.getByText(FULL.name_en)).toHaveCount(1);
    // Header controls say what they do (visible text on desktop, name and tooltip everywhere).
    const header = page.locator("header");
    await expect(
      header.getByRole("button", {
        name: tr(LANG, "common:language.switchTo", {
          language: tr(LANG, "common:language.ar"),
        }),
      }),
    ).toBeVisible();
    await expect(
      header.getByRole("button", { name: tr(LANG, "common:theme.change") }),
    ).toContainText(tr(LANG, "common:theme.light"));
    await expect(page.getByTestId("portal-header-sign-in")).toBeVisible();
    await page.context().close();
  });

  test("a large screen shows two columns: content beside hours, contact and the sign-in guide", async ({
    browser,
  }) => {
    for (const lang of ["en", "ar"] as const) {
      const page = await openCenter(
        browser,
        { width: 1280, height: 800 },
        "light",
        lang,
        FULL,
      );
      const main = page.getByTestId("center-doctors");
      const side = page.getByTestId("center-side");
      await expect(main).toBeVisible();
      await expect(side).toBeVisible();
      const [m, s] = await Promise.all([
        main.boundingBox(),
        side.boundingBox(),
      ]);
      if (!m || !s) throw new Error("columns are laid out");
      // Same row, side column at the inline end: right in English, left in Arabic (RTL).
      expect(
        Math.abs(m.y - s.y) < 400,
        "columns start near the same height",
      ).toBe(true);
      if (lang === "en") expect(s.x).toBeGreaterThan(m.x + m.width - 1);
      else expect(s.x + s.width).toBeLessThan(m.x + 1);
      await expect(side.getByTestId("center-hours-today")).toBeVisible();
      await expect(side.getByTestId("center-contact")).toBeVisible();
      await expect(side.getByTestId("center-how")).toBeVisible();
      // Phone-only blocks are gone; the page is wider than a phone column but centered at max width.
      await expect(page.getByTestId("center-quick-actions")).toBeHidden();
      await expect(page.getByTestId("center-sticky-bar")).toBeHidden();
      const hero = await page.getByTestId("center-hero").boundingBox();
      expect(hero?.width ?? 0).toBeGreaterThan(900);
      expect(hero?.width ?? 9999).toBeLessThanOrEqual(1200);
      await expectNoHorizontalScroll(page);
      await page.context().close();
    }
  });

  test("a phone gets quick actions and a sticky bar that never covers the page end", async ({
    browser,
  }) => {
    const page = await openCenter(
      browser,
      { width: 375, height: 812 },
      "light",
      "en",
      FULL,
    );
    const quick = page.getByTestId("center-quick-actions");
    await expect(quick).toBeVisible();
    for (const id of [
      "quick-call",
      "quick-whatsapp",
      "quick-directions",
      "quick-book",
    ]) {
      await expect(quick.getByTestId(id)).toBeVisible();
    }
    // Primary content is not a horizontal scroller.
    await expect(page.getByTestId("center-doctor").first()).toBeVisible();
    await expectNoHorizontalScroll(page);
    // Scrolled to the very end, the privacy line sits above the fixed bar.
    await page.evaluate(() => {
      window.scrollTo(0, document.documentElement.scrollHeight);
    });
    const bar = page.getByTestId("center-sticky-bar");
    await expect(bar).toBeVisible();
    const footerText = page.locator("footer p").first();
    const [barBox, textBox] = await Promise.all([
      bar.boundingBox(),
      footerText.boundingBox(),
    ]);
    if (!barBox || !textBox) throw new Error("bar and footer are laid out");
    expect(textBox.y + textBox.height).toBeLessThanOrEqual(barBox.y + 1);
    await page.context().close();
  });

  test("only the quick actions that have data are offered", async ({
    browser,
  }) => {
    const page = await openCenter(
      browser,
      { width: 375, height: 812 },
      "light",
      "en",
      {
        ...FULL,
        whatsapp: "",
        email: "",
        address: "",
        directions_en: "",
        directions_ar: "",
      },
    );
    const quick = page.getByTestId("center-quick-actions");
    await expect(quick.getByTestId("quick-call")).toBeVisible();
    await expect(quick.getByTestId("quick-whatsapp")).toHaveCount(0);
    await expect(quick.getByTestId("quick-directions")).toHaveCount(0);
    await page.context().close();
  });

  test("a nearly empty page still reads as intentional", async ({
    browser,
  }) => {
    for (const payload of [SPARSE, EMPTY]) {
      const page = await openCenter(
        browser,
        { width: 1280, height: 800 },
        "light",
        "en",
        payload,
      );
      await expect(page.getByTestId("center-hero")).toBeVisible();
      await expect(page.getByTestId("center-how")).toBeVisible();
      await expect(page.getByTestId("center-hours")).toHaveCount(0);
      await expect(page.getByTestId("center-contact")).toHaveCount(0);
      await expect(page.getByTestId("center-announcements")).toHaveCount(0);
      for (const id of ["quick-call", "quick-whatsapp", "quick-directions"]) {
        await expect(page.getByTestId(id)).toHaveCount(0);
      }
      await expect(page.locator("#main")).not.toContainText(
        /no data|none yet/i,
      );
      await expect(page.getByTestId("center-sign-in")).toHaveCount(2);
      await expectNoHorizontalScroll(page);
      await page.context().close();
    }
  });

  test.describe("screens", () => {
    // Pictures of the three data shapes: ar light and en dark, phone and desktop.
    const SHAPES = [
      ["center-full", FULL],
      ["center-sparse", SPARSE],
      ["center-empty", EMPTY],
    ] as const;
    for (const [name, payload] of SHAPES) {
      for (const size of [
        { width: 375, height: 812 },
        { width: 1280, height: 800 },
      ]) {
        for (const [theme, lang] of [
          ["light", "ar"],
          ["dark", "en"],
        ] as const) {
          test(`${name} ${String(size.width)} ${theme} ${lang}`, async ({
            browser,
          }) => {
            const page = await openCenter(browser, size, theme, lang, payload);
            await expectNoHorizontalScroll(page);
            await snap(page, name);
            await page.context().close();
          });
        }
      }
    }
  });

  test("a signed-in patient is offered their file instead", async ({
    browser,
  }) => {
    const who = await portalPatient();
    const page = await phonePage(browser);
    await signInPortal(page, who);
    await page.goto("/portal");
    const action = page.getByTestId("center-sign-in").first();
    await expect(action).toHaveText(t("portal:center.openFile"));
    await action.click();
    await expect(page).toHaveURL(/\/portal\/home$/);
  });

  test.describe("administration", () => {
    test.use({
      storageState: ADMIN_STATE,
      viewport: { width: 1280, height: 800 },
    });

    test("a notice and a hidden doctor reach the public page", async ({
      page,
      browser,
    }) => {
      const admin = await apiAs("admin");
      const before = await admin.get<CenterPageSettings>(
        "/api/core/center-page",
      );
      const title = `Notice ${String(Date.now())}`;
      try {
        await setPrefs(page, { theme: "light", lang: LANG });
        await page.goto("/administration/center-page");
        await expect(page.getByTestId("center-page-form")).toBeVisible();
        await page.getByTestId("announcement-add").click();
        const dialog = page.getByRole("dialog");
        await dialog
          .getByLabel(tr(LANG, "admin:centerPage.titleEn"))
          .fill(title);
        await dialog
          .getByRole("button", {
            name: tr(LANG, "admin:centerPage.saveAnnouncement"),
          })
          .click();
        await expect(dialog).toBeHidden();
        await expect(
          page.getByTestId("announcement-row").filter({ hasText: title }),
        ).toContainText(tr(LANG, "admin:centerPage.state.shown"));

        // Untick the first doctor and save the page.
        const visitor = await phonePage(browser);
        const shown = (await (
          await visitor.context().request.get("/api/portal/center-page")
        ).json()) as PublicPage;
        const doctor = shown.doctors[0];
        if (!doctor) throw new Error("the seed has doctors with clinic hours");
        const doctors = page.getByTestId("section-doctors");
        await doctors.getByRole("checkbox", { name: doctor.name_en }).uncheck();
        await page
          .getByRole("button", { name: tr(LANG, "admin:centerPage.save") })
          .click();
        await expect(
          page.getByText(tr(LANG, "admin:centerPage.saved")),
        ).toBeVisible();

        await visitor.goto("/portal");
        await expect(
          visitor.getByTestId("center-announcement").filter({ hasText: title }),
        ).toBeVisible();
        await expect(
          visitor.getByTestId("center-doctor").first(),
        ).toBeVisible();
        await expect(visitor.getByTestId("center-doctors")).not.toContainText(
          doctor.name_en,
        );
        await visitor.context().close();
      } finally {
        await admin.put("/api/core/center-page", before);
        const rows = await admin.get<{ id: number; title_en: string }[]>(
          "/api/core/announcements",
        );
        for (const row of rows.filter((r) => r.title_en === title)) {
          await admin.patch(`/api/core/announcements/${String(row.id)}`, {
            active: false,
          });
        }
      }
    });
  });
});
