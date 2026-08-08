/// <reference types="node" />

import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

describe("Web document shell", () => {
  it("ships an explicit favicon instead of triggering the browser default 404", () => {
    const html = readFileSync(resolve(process.cwd(), "index.html"), "utf8");
    const favicon = resolve(process.cwd(), "public/favicon.svg");

    expect(html).toMatch(/<link\s+rel="icon"\s+type="image\/svg\+xml"\s+href="\/favicon\.svg"\s*\/>/);
    expect(existsSync(favicon)).toBe(true);
  });
});
