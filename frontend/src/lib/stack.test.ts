import { describe, expect, it } from "vitest";

import { stackBadgesFrom } from "@/lib/stack";

/**
 * The stack object is stored by the backend as the whole `StackReport`, which
 * carries more than lists of framework names. Rendering one of those extra
 * values as a React child throws and blanks the entire page — which is
 * exactly what happened the first time the screenshots were captured.
 */
describe("stackBadgesFrom", () => {
  const REAL_STACK = {
    frontend: ["React"],
    backend: ["FastAPI"],
    database: ["SQLAlchemy"],
    build: ["TypeScript", "Vite"],
    package_managers: ["npm", "pip"],
    languages: { TypeScript: 8, Python: 6 },
    is_monorepo: false,
    frontend_roots: ["frontend"],
    signals: [
      {
        name: "React",
        layer: "frontend",
        source_file: "frontend/package.json",
        evidence: '"react-dom": "^18.3.1"',
        confidence: 1,
      },
    ],
  };

  it("returns only framework names", () => {
    expect(stackBadgesFrom(REAL_STACK)).toEqual([
      "React",
      "FastAPI",
      "SQLAlchemy",
      "TypeScript",
      "Vite",
      "npm",
      "pip",
    ]);
  });

  it("never returns an object, however the backend shapes the report", () => {
    for (const badge of stackBadgesFrom(REAL_STACK)) {
      expect(typeof badge).toBe("string");
    }
  });

  it("ignores the signal objects that would crash the render", () => {
    const badges = stackBadgesFrom(REAL_STACK);

    expect(badges).not.toContainEqual(expect.objectContaining({ layer: "frontend" }));
    expect(badges.join(" ")).not.toContain("package.json");
  });

  it("ignores a nested object such as the language tally", () => {
    expect(stackBadgesFrom({ languages: { Python: 10 } })).toEqual([]);
  });

  it("drops non-string entries inside a known key", () => {
    expect(stackBadgesFrom({ frontend: ["React", 42, null, { a: 1 }] })).toEqual(["React"]);
  });

  it("handles a missing stack", () => {
    expect(stackBadgesFrom(null)).toEqual([]);
  });

  it("handles an empty stack", () => {
    expect(stackBadgesFrom({})).toEqual([]);
  });
});
