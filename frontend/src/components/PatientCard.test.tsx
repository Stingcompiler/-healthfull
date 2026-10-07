import { render, screen } from "@testing-library/react";
import { afterAll, describe, expect, it } from "vitest";

import i18n from "@/i18n";

import { PatientCard, type PatientCardPatient } from "./PatientCard";

const base: PatientCardPatient = {
  nameAr: "فاطمة عثمان",
  nameEn: "Fatima Osman",
  fileNo: "2026-00412",
  sex: "female",
  ageYears: 38,
  allergies: ["Penicillin"],
  coverage: null,
};

describe("PatientCard", () => {
  afterAll(async () => {
    await i18n.changeLanguage("ar");
  });

  it("shows allergies as prominent danger chips", async () => {
    await i18n.changeLanguage("en");
    render(<PatientCard patient={base} />);
    const group = screen.getByRole("group", { name: "Allergy alert" });
    expect(group).toHaveTextContent("Penicillin");
    expect(group.querySelector("span")).toHaveClass("bg-danger", "text-danger-contrast");
  });

  it("distinguishes no known allergies from not recorded", async () => {
    await i18n.changeLanguage("en");
    const { rerender } = render(<PatientCard patient={{ ...base, allergies: [] }} />);
    expect(screen.getByText("No known allergies")).toBeInTheDocument();
    rerender(<PatientCard patient={{ ...base, allergies: null }} />);
    expect(screen.getByText("Allergies not recorded")).toBeInTheDocument();
  });

  it("picks the name for the language and shows the other below", async () => {
    await i18n.changeLanguage("ar");
    render(<PatientCard patient={base} />);
    expect(screen.getByRole("heading", { name: "فاطمة عثمان" })).toBeInTheDocument();
    expect(screen.getByText("Fatima Osman")).toBeInTheDocument();
  });

  it("gives each name line its own direction and never truncates it", async () => {
    await i18n.changeLanguage("ar");
    const { rerender } = render(<PatientCard patient={base} />);
    // Arabic UI: the Arabic name follows the UI, the English one is LTR aligned to the UI's start (its end).
    expect(screen.getByRole("heading", { name: "فاطمة عثمان" })).toHaveAttribute("dir", "rtl");
    expect(screen.getByRole("heading", { name: "فاطمة عثمان" })).toHaveClass("break-words", "text-start");
    expect(screen.getByRole("heading", { name: "فاطمة عثمان" })).not.toHaveClass("truncate");
    expect(screen.getByText("Fatima Osman")).toHaveAttribute("dir", "ltr");
    expect(screen.getByText("Fatima Osman")).toHaveClass("break-words", "text-end");
    expect(screen.getByText("Fatima Osman")).not.toHaveClass("truncate");

    await i18n.changeLanguage("en");
    rerender(<PatientCard patient={base} />);
    expect(screen.getByRole("heading", { name: "Fatima Osman" })).toHaveAttribute("dir", "ltr");
    expect(screen.getByRole("heading", { name: "Fatima Osman" })).toHaveClass("text-start");
    expect(screen.getByText("فاطمة عثمان")).toHaveAttribute("dir", "rtl");
    expect(screen.getByText("فاطمة عثمان")).toHaveClass("text-end");

    // Only an Arabic name on file (emergency registration): the English UI shows it RTL, aligned to its start.
    rerender(<PatientCard patient={{ ...base, nameAr: "مولود — طوارئ", nameEn: null }} />);
    const heading = screen.getByRole("heading", { name: "مولود — طوارئ" });
    expect(heading).toHaveAttribute("dir", "rtl");
    expect(heading).toHaveClass("text-end");
  });

  it("shows a four-part name in full", async () => {
    await i18n.changeLanguage("ar");
    const fourPart = "فاطمة عثمان محمد الحسن";
    render(<PatientCard patient={{ ...base, nameAr: fourPart, nameEn: "Fatima Osman Mohamed Alhassan" }} />);
    const heading = screen.getByRole("heading", { name: fourPart });
    expect(heading).toHaveTextContent(fourPart);
    expect(heading.className).not.toMatch(/truncate|line-clamp|text-ellipsis/);
    expect(screen.getByText("Fatima Osman Mohamed Alhassan").className).not.toMatch(/truncate|line-clamp/);
  });

  it("uses Arabic plural forms for age", async () => {
    await i18n.changeLanguage("ar");
    const { rerender } = render(<PatientCard patient={{ ...base, ageYears: 2 }} />);
    expect(screen.getByText("سنتان")).toBeInTheDocument();
    rerender(<PatientCard patient={{ ...base, ageYears: 5 }} />);
    expect(screen.getByText("5 سنوات")).toBeInTheDocument();
    rerender(<PatientCard patient={{ ...base, ageYears: 38 }} />);
    expect(screen.getByText("38 سنة")).toBeInTheDocument();
  });

  it("shows coverage or self-pay", async () => {
    await i18n.changeLanguage("en");
    const { rerender } = render(<PatientCard patient={base} />);
    expect(screen.getByText("Self-pay")).toBeInTheDocument();
    rerender(<PatientCard patient={{ ...base, coverage: { nameAr: "شيكان", nameEn: "Shiekan" } }} />);
    expect(screen.getByText("Shiekan")).toBeInTheDocument();
  });
});
