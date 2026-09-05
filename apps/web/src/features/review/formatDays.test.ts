import { describe, expect, it } from "vitest";

import { formatDays } from "./formatDays";

describe("formatDays", () => {
  it("labels the SM-2 preview buckets compactly", () => {
    expect(formatDays(0)).toBe("today");
    expect(formatDays(1)).toBe("1d");
    expect(formatDays(13)).toBe("13d");
    expect(formatDays(14)).toBe("2w");
    expect(formatDays(45)).toBe("6w");
    expect(formatDays(60)).toBe("2mo");
    expect(formatDays(300)).toBe("10mo");
    expect(formatDays(365)).toBe("1y");
  });

  it("is empty when the server sent no preview", () => {
    expect(formatDays(undefined)).toBe("");
  });
});
