import { describe, expect, it } from "vitest";

import { ApiError } from "./api";

describe("ApiError", () => {
  it("carries status and message", () => {
    const e = new ApiError(401, "Not authenticated");
    expect(e.status).toBe(401);
    expect(e.message).toBe("Not authenticated");
    expect(e).toBeInstanceOf(Error);
  });
});
