import { render, screen } from "@testing-library/react";
import { useForm } from "react-hook-form";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import i18n from "@/i18n";

import { TextField } from "./fields";
import { Form } from "./form";

function Demo({ required, optional }: { required?: boolean; optional?: boolean }) {
  const form = useForm<{ notes: string }>({ defaultValues: { notes: "" } });
  return (
    <Form {...form}>
      <TextField control={form.control} name="notes" label="Notes" required={required} optional={optional} />
    </Form>
  );
}

describe("FormLabel optional marker (Design Reference 2.2 section 15.2)", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });
  afterEach(async () => {
    await i18n.changeLanguage("ar");
  });

  it("shows '(Optional)' as visible text, not a star", () => {
    render(<Demo optional />);
    expect(screen.getByText("(Optional)")).toBeVisible();
  });

  it("a required field keeps the star and the screen-reader text, never both markers", () => {
    render(<Demo required optional />);
    expect(screen.queryByText("(Optional)")).toBeNull();
    expect(screen.getByText("(Required)")).toBeInTheDocument();
  });

  it("no marker by default", () => {
    render(<Demo />);
    expect(screen.queryByText("(Optional)")).toBeNull();
  });
});
