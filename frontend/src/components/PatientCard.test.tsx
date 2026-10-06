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
