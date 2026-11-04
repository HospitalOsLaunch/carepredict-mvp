import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const conf = readFileSync(resolve(__dirname, "../../nginx.conf"), "utf8");
const directive = (name: string) => new RegExp(`^\\s*${name}\\s+([^;]+);`, "m").exec(conf)?.[1].trim();

describe("nginx compression", () => {
  it("compresses the app and the API answers (JS 542 → ~160 Ko, /api/stays 62 → ~3 Ko)", () => {
    expect(directive("gzip")).toBe("on");
    const types = directive("gzip_types")?.split(/\s+/) ?? [];
    for (const type of ["application/javascript", "text/css", "application/json", "image/svg+xml", "text/csv"]) expect(types).toContain(type);
    // /api/ answers come through proxy_pass: without gzip_proxied they would stay uncompressed.
    expect(directive("gzip_proxied")).toBe("any");
    expect(directive("gzip_vary")).toBe("on");
    expect(Number(directive("gzip_min_length"))).toBeGreaterThanOrEqual(256);
  });

  it("does not spend CPU recompressing images that already are (JPEG frames of the player)", () => {
    const types = directive("gzip_types")?.split(/\s+/) ?? [];
    expect(types.filter((t) => /jpeg|png|webp|woff2/.test(t))).toEqual([]);
  });
});
