/**
 * The public center website at the portal's door (ADR 0023, 0029 H): a signed-out phone visitor
 * sees the center, today's status, the website sections in their fixed order (hero, about,
 * facilities, reasons, services, doctors, hours with "fees are paid at reception", insurers, FAQ,
 * testimonials, accessibility, contact with a plain maps link, policies), never a price, and one
 * repeated action that leads to sign-in. Full, sparse and empty pages pass at 375/768/1280 in
 * three themes and two languages with no horizontal scroll and no axe violation. The
 * administrator edits the page from /administration/center-page and the public page follows.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Browser, type Page } from "@playwright/test";

import { ADMIN_STATE } from "../../fixtures/state";
import {
  apiAs,
  expectNoHorizontalScroll,
  LANGS,
  setPrefs,
  snap,
  THEMES,
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
  departments: {
    id: number;
    name_ar: string;
    name_en: string;
    services: { id: number; name_ar: string; name_en: string }[];
  }[];
  doctors: object[];
  announcements: object[];
  maps_url: string;
  hero_title_ar: string;
  hero_title_en: string;
  hero_text_ar: string;
  hero_text_en: string;
  hero_image: Image | null;
  gallery: Image[];
  facilities: { name_ar: string; name_en: string }[];
  reasons: {
    title_ar: string;
    title_en: string;
    text_ar: string;
    text_en: string;
  }[];
  insurance: { id: number; name_ar: string; name_en: string }[];
  faq: {
    id: number;
    question_ar: string;
    question_en: string;
    answer_ar: string;
    answer_en: string;
  }[];
  testimonials: {
    id: number;
    text_ar: string;
    text_en: string;
    author_ar: string;
    author_en: string;
  }[];
  accessibility_ar: string;
  accessibility_en: string;
  privacy_ar: string;
  privacy_en: string;
  cancellation_policy_ar: string;
  cancellation_policy_en: string;
}

interface Image {
  id: number;
  url: string;
  alt_ar: string;
  alt_en: string;
  width: number;
  height: number;
}

/** A small local PNG served for every website image (the page never loads external images). */
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "base64",
);
const image = (id: number, ar: string, en: string): Image => ({
  id,
  url: `/api/portal/center-media/${String(id)}?v=1`,
  alt_ar: ar,
  alt_en: en,
  width: 1200,
  height: 900,
});

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
  qualifications_ar: id === 1 ? "بكالوريوس الطب، زمالة الباطنية" : "",
  qualifications_en: id === 1 ? "MBBS, Fellowship in internal medicine" : "",
  bio_ar: id === 1 ? "خبرة عشرين عامًا في علاج الأمراض المزمنة." : "",
  bio_en: id === 1 ? "Twenty years caring for chronic illness." : "",
  photo: id === 1 ? image(5, "صورة الطبيبة", "Portrait") : null,
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
    {
      id: 1,
      name_ar: "الباطنية",
      name_en: "Internal medicine",
      services: [
        { id: 11, name_ar: "تخطيط القلب", name_en: "ECG" },
        { id: 12, name_ar: "متابعة السكري", name_en: "Diabetes follow-up" },
      ],
    },
    {
      id: 2,
      name_ar: "الأطفال",
      name_en: "Pediatrics",
      services: [
        { id: 21, name_ar: "تطعيمات الأطفال", name_en: "Child vaccinations" },
      ],
    },
    {
      id: 3,
      name_ar: "النساء والتوليد",
      name_en: "Obstetrics and gynecology",
      services: [
        { id: 31, name_ar: "متابعة الحمل", name_en: "Antenatal care" },
      ],
    },
    { id: 4, name_ar: "الأسنان", name_en: "Dental", services: [] },
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
  maps_url: "https://maps.app.goo.gl/alnoor",
  hero_title_ar: "رعاية قريبة منك، كل أيام الأسبوع",
  hero_title_en: "Care close to home, every day of the week",
  hero_text_ar: "عيادات ومختبر وصيدلية في مبنى واحد.",
  hero_text_en: "Clinics, a laboratory and a pharmacy in one building.",
  hero_image: image(1, "واجهة المركز", "The center's front door"),
  gallery: [
    image(2, "غرفة الانتظار", "Waiting room"),
    image(3, "المختبر", "Laboratory"),
    image(4, "الصيدلية", "Pharmacy"),
  ],
  facilities: [
    { name_ar: "مختبر", name_en: "Laboratory" },
    { name_ar: "صيدلية", name_en: "Pharmacy" },
    { name_ar: "أشعة", name_en: "X-ray" },
    { name_ar: "موقف سيارات", name_en: "Parking" },
  ],
  reasons: [
    {
      title_ar: "نتائج في نفس اليوم",
      title_en: "Same-day results",
      text_ar: "معظم التحاليل جاهزة قبل نهاية الدوام.",
      text_en: "Most tests are ready before closing time.",
    },
    {
      title_ar: "مفتوح حتى المساء",
      title_en: "Open until evening",
      text_ar: "",
      text_en: "",
    },
  ],
  insurance: [
    { id: 1, name_ar: "شركة النيل للتأمين", name_en: "Nile Insurance" },
    { id: 2, name_ar: "الصندوق القومي", name_en: "National Health Fund" },
  ],
  faq: [
    {
      id: 1,
      question_ar: "هل أحتاج إلى موعد؟",
      question_en: "Do I need an appointment?",
      answer_ar: "لا، يمكنك الحضور في ساعات العمل.",
      answer_en: "No, you can come during opening hours.",
    },
    {
      id: 2,
      question_ar: "هل توجد صيدلية؟",
      question_en: "Is there a pharmacy?",
      answer_ar: "نعم، في الطابق الأرضي.",
      answer_en: "Yes, on the ground floor.",
    },
  ],
  testimonials: [
    {
      id: 1,
      text_ar: "استقبال لطيف ونتيجة التحليل في نفس اليوم.",
      text_en: "Friendly reception and my result the same day.",
      author_ar: "مريضة من أم درمان",
      author_en: "A patient from Omdurman",
    },
    {
      id: 2,
      text_ar: "الطبيبة شرحت كل شيء بهدوء.",
      text_en: "The doctor explained everything calmly.",
      author_ar: "مراجع من بحري",
      author_en: "A patient from Bahri",
    },
  ],
  accessibility_ar: "مدخل بلا درج وكرسي متحرك عند الاستقبال.",
  accessibility_en: "Step-free entrance and a wheelchair at reception.",
  privacy_ar: "بياناتك محفوظة في خادم المركز.",
  privacy_en: "Your data stays on the center's server.",
  cancellation_policy_ar: "ألغِ موعدك قبل يوم على الأقل.",
  cancellation_policy_en: "Cancel at least a day before.",
};

/** Every website section of ADR 0029 H left empty (the page as it was before Phase 2). */
const NO_CONTENT = {
  maps_url: "",
  hero_title_ar: "",
  hero_title_en: "",
  hero_text_ar: "",
  hero_text_en: "",
  hero_image: null,
  gallery: [],
  facilities: [],
  reasons: [],
  insurance: [],
  faq: [],
  testimonials: [],
  accessibility_ar: "",
  accessibility_en: "",
  privacy_ar: "",
  privacy_en: "",
  cancellation_policy_ar: "",
  cancellation_policy_en: "",
} satisfies Partial<Payload>;

/** The production shape that looked unfinished: one doctor, one department, nothing else. */
const SPARSE: Payload = {
  ...FULL,
  ...NO_CONTENT,
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
  departments: FULL.departments.slice(3, 4),
  doctors: FULL.doctors.slice(1, 2),
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
  await page.route("**/api/portal/center-media/**", (route) =>
    route.fulfill({ body: PNG, contentType: "image/png" }),
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

  test("a large screen shows two columns: content beside hours, fees and the sign-in guide", async ({
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
      const main = page.getByTestId("center-about");
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
      await expect(side.getByTestId("center-fees")).toBeVisible();
      await expect(side.getByTestId("center-how")).toBeVisible();
      // Contact comes after the content in the page's order, at full width (D-0021).
      await expect(page.getByTestId("center-contact")).toBeVisible();
      await expect(side.getByTestId("center-contact")).toHaveCount(0);
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
        maps_url: "",
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

  test("the full website reads in its fixed order, with no price and fees at reception", async ({
    browser,
  }) => {
    const page = await openCenter(
      browser,
      { width: 375, height: 812 },
      "light",
      "en",
      FULL,
    );
    const order = [
      "center-hero",
      "center-announcements",
      "center-about",
      "center-facilities",
      "center-reasons",
      "center-departments",
      "center-doctors",
      "center-hours",
      "center-fees",
      "center-insurance",
      "center-faq",
      "center-testimonials",
      "center-accessibility",
      "center-contact",
      "center-policies",
    ];
    const tops: number[] = [];
    for (const id of order) {
      const box = await page.getByTestId(id).boundingBox();
      if (!box) throw new Error(`${id} is laid out`);
      tops.push(box.y);
    }
    expect(tops, order.join(" > ")).toEqual([...tops].sort((a, b) => a - b));
    await expect(page.getByTestId("center-hero-title")).toHaveText(
      FULL.hero_title_en,
    );
    await expect(page.getByTestId("center-gallery").locator("img")).toHaveCount(
      3,
    );
    await expect(page.getByTestId("center-services").first()).toContainText(
      "ECG",
    );
    await expect(
      page.getByTestId("center-doctor-qualifications").first(),
    ).toContainText("MBBS");
    await expect(page.getByTestId("center-fees")).toContainText(
      t("portal:center.fees.text"),
    );
    await expect(page.getByTestId("center-fees")).toContainText(
      FULL.cancellation_policy_en,
    );
    await expect(page.getByTestId("center-faq-item")).toHaveCount(2);
    await page
      .getByTestId("center-faq-item")
      .first()
      .locator("summary")
      .click();
    await expect(page.getByTestId("center-faq-item").first()).toContainText(
      "opening hours",
    );
    // A plain link the phone opens, like wa.me; images come only from the center's server.
    await expect(page.getByTestId("center-maps")).toHaveAttribute(
      "href",
      FULL.maps_url,
    );
    const sources = await page
      .locator("#main img")
      .evaluateAll((imgs) => imgs.map((i) => (i as HTMLImageElement).src));
    expect(sources.length).toBeGreaterThan(0);
    for (const src of sources) {
      expect(new URL(src).pathname).toMatch(
        /^\/api\/portal\/center-media\/\d+$/,
      );
    }
    // No price or currency anywhere on the page.
    await expect(page.locator("#main")).not.toContainText(/SDG|ج\.س|جنيه/);
    await expectNoHorizontalScroll(page);
    await page.context().close();
  });

  test("hidden or empty sections render nothing", async ({ browser }) => {
    const page = await openCenter(
      browser,
      { width: 375, height: 812 },
      "light",
      "en",
      SPARSE,
    );
    for (const id of [
      "center-about",
      "center-facilities",
      "center-reasons",
      "center-insurance",
      "center-faq",
      "center-testimonials",
      "center-accessibility",
      "center-policies",
      "center-maps",
      "center-gallery",
    ]) {
      await expect(page.getByTestId(id), id).toHaveCount(0);
    }
    await page.context().close();
  });

  test.describe("screens", () => {
    // Every shape x 3 viewports x 3 themes x 2 languages: no horizontal scroll and no axe
    // violation; pictures for (ar, light), (en, dark) and (ar, warm) (ARCHITECTURE 6).
    const SHAPES = [
      ["center-full", FULL],
      ["center-sparse", SPARSE],
      ["center-empty", EMPTY],
    ] as const;
    const SNAPPED = new Set(["light-ar", "dark-en", "warm-ar"]);
    for (const [name, payload] of SHAPES) {
      for (const size of [
        { width: 375, height: 812 },
        { width: 768, height: 1024 },
        { width: 1280, height: 800 },
      ]) {
        for (const theme of THEMES) {
          for (const lang of LANGS) {
            test(`${name} ${String(size.width)} ${theme} ${lang}`, async ({
              browser,
            }) => {
              const page = await openCenter(
                browser,
                size,
                theme,
                lang,
                payload,
              );
              await expectNoHorizontalScroll(page);
              const axe = await new AxeBuilder({ page })
                .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
                .analyze();
              expect(
                axe.violations.map(
                  (v) =>
                    `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`,
                ),
              ).toEqual([]);
              if (SNAPPED.has(`${theme}-${lang}`)) await snap(page, name);
              await page.context().close();
            });
          }
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

    test("a question and an approved testimonial reach the public page", async ({
      page,
      browser,
    }) => {
      const admin = await apiAs("admin");
      const stamp = String(Date.now());
      const question = `Is there parking ${stamp}?`;
      const words = `Kind staff ${stamp}`;
      try {
        await setPrefs(page, { theme: "light", lang: LANG });
        await page.goto("/administration/center-page");
        await expect(page.getByTestId("center-page-form")).toBeVisible();

        await page.getByTestId("faq-add").click();
        let dialog = page.getByRole("dialog");
        await dialog
          .getByLabel(tr(LANG, "admin:centerPage.faq.questionEn"))
          .fill(question);
        await dialog
          .getByLabel(tr(LANG, "admin:centerPage.faq.answerEn"))
          .fill("Yes, behind the building.");
        await dialog
          .getByRole("button", { name: tr(LANG, "admin:centerPage.faq.save") })
          .click();
        await expect(dialog).toBeHidden();

        await page.getByTestId("testimonial-add").click();
        dialog = page.getByRole("dialog");
        await dialog
          .getByLabel(tr(LANG, "admin:centerPage.testimonials.textEn"))
          .fill(words);
        await dialog
          .getByRole("button", {
            name: tr(LANG, "admin:centerPage.testimonials.save"),
          })
          .click();
        await expect(dialog).toBeHidden();
        const row = page
          .getByTestId("testimonial-row")
          .filter({ hasText: words });
        await expect(row).toContainText(
          tr(LANG, "admin:centerPage.testimonials.state.waiting"),
        );

        // Not approved yet: the public page does not show it.
        const visitor = await phonePage(browser);
        const before = (await (
          await visitor.context().request.get("/api/portal/center-page")
        ).json()) as Payload;
        expect(before.faq.map((f) => f.question_en)).toContain(question);
        expect(before.testimonials.map((x) => x.text_en)).not.toContain(words);

        await row.getByTestId("testimonial-approve").click();
        await expect(row).toContainText(
          tr(LANG, "admin:centerPage.testimonials.state.approved"),
        );
        await visitor.goto("/portal");
        await expect(visitor.getByTestId("center-faq")).toContainText(question);
        await expect(visitor.getByTestId("center-testimonials")).toContainText(
          words,
        );
        await expectNoHorizontalScroll(page);
        await visitor.context().close();
      } finally {
        const faq = await admin.get<{ id: number; question_en: string }[]>(
          "/api/core/center-faq",
        );
        for (const r of faq.filter((f) => f.question_en === question)) {
          await admin.delete(`/api/core/center-faq/${String(r.id)}`);
        }
        const list = await admin.get<{ id: number; text_en: string }[]>(
          "/api/core/testimonials",
        );
        for (const r of list.filter((x) => x.text_en === words)) {
          await admin.delete(`/api/core/testimonials/${String(r.id)}`);
        }
      }
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
