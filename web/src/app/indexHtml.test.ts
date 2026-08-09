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

  it("uses smooth same-document anchor scrolling while honoring reduced motion", () => {
    const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");

    expect(css).toMatch(/html\s*\{[^}]*scroll-behavior:\s*smooth;/);
    expect(css).toMatch(
      /@media\s*\(prefers-reduced-motion:\s*reduce\)[\s\S]*scroll-behavior:\s*auto\s*!important/,
    );
  });

  it("uses one wireframe treatment and a top-left offset for all audience icons", () => {
    const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");
    const iconRule = css.match(/\.showcase-audience__icon\s*\{([^}]*)\}/)?.[1] ?? "";

    expect(iconRule).toMatch(/top:\s*-0\.5rem;/);
    expect(iconRule).toMatch(/left:\s*-0\.5rem;/);
    expect(iconRule).toMatch(/border:\s*1px solid rgba\(21,\s*24,\s*21,\s*0\.34\);/);
    expect(iconRule).toMatch(/background:\s*transparent;/);
    expect(iconRule).toMatch(/color:\s*var\(--showcase-ink\);/);
    expect(css).not.toContain("--audience-icon-background");
    expect(css).not.toContain("--audience-icon-color");
  });

  it("animates demo answers character by character and disables the effect for reduced motion", () => {
    const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");

    expect(css).toMatch(
      /\.demo-typewriter__char\s*\{[^}]*animation:[^;}]*demo-character-in[^;}]*forwards;/,
    );
    expect(css).toMatch(
      /@media\s*\(prefers-reduced-motion:\s*reduce\)[\s\S]*\.demo-typewriter__char\s*\{[^}]*animation:\s*none\s*!important;/,
    );
  });

  it("keeps the interactive hero covers layered and styles their mobile captions", () => {
    const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");

    expect(css).toMatch(
      /\.instrument-cover\.is-front\s*\{[^}]*--cover-z:\s*3rem;[^}]*z-index:\s*4;/,
    );
    expect(css).toContain(".instrument-cover__caption { grid-template-columns:");
    expect(css).not.toContain(".instrument-cover figcaption");
  });

  it("skins native library selects with the shared paper-and-ink control treatment", () => {
    const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");

    expect(css).toMatch(/\.select-field\s*\{[^}]*position:\s*relative;[^}]*min-width:\s*0;/);
    expect(css).toMatch(/\.select-field::after\s*\{[^}]*pointer-events:\s*none;/);
    expect(css).toMatch(/\.select-field select\s*\{[^}]*appearance:\s*none;/);
    expect(css).toMatch(
      /\.select-field select\s*\{[^}]*border-radius:\s*0\.9rem 0\.9rem 0\.9rem 0\.28rem;/,
    );
    expect(css).toMatch(/\.select-field select:focus-visible\s*\{[^}]*outline:\s*3px solid/);
    expect(css).toMatch(/\.select-field select:disabled\s*\{[^}]*cursor:\s*not-allowed;/);
  });
});
