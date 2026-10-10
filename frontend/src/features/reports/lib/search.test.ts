import { describe, expect, it } from "vitest";

import { parseReportSearch, reportQuery, reportQueryString } from "./search";

describe("report search params", () => {
  it("keeps well-formed filters", () => {
    expect(parseReportSearch({ from: "2026-10-01", to: "2026-10-10", department: "3", user: 7, days: "30" })).toEqual({
      from: "2026-10-01",
      to: "2026-10-10",
      department: 3,
      user: 7,
      days: 30,
    });
  });

  it("drops malformed values", () => {
    expect(
      parseReportSearch({ from: "10/01/2026", to: "2026-13-45", department: "x", user: -1, days: "9999" }),
    ).toEqual({});
    expect(parseReportSearch({ days: "0" })).toEqual({ days: 0 });
  });

  it("maps to the API query and a download query string", () => {
    const search = { from: "2026-10-01", to: "2026-10-02", department: 4 };
    expect(reportQuery(search)).toEqual({ date_from: "2026-10-01", date_to: "2026-10-02", department_id: 4 });
    expect(reportQueryString(search, { language: "ar" })).toBe(
      "date_from=2026-10-01&date_to=2026-10-02&department_id=4&language=ar",
    );
  });
});
