import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const read = (name: string) => readFileSync(resolve(__dirname, "../..", name), "utf8");
const SNIPPET = "/etc/nginx/snippets/security_headers.conf";

/** The Content-Security-Policy of the security headers snippet, as directive → sources. */
function policy(): Record<string, string[]> {
  const header = /add_header\s+Content-Security-Policy\s+"([^"]+)"/.exec(read("security_headers.conf"));
  expect(header, "security_headers.conf sends a Content-Security-Policy").not.toBeNull();
  return Object.fromEntries(
    header![1]
      .split(";")
      .map((d) => d.trim().split(/\s+/))
      .filter((parts) => parts[0])
      .map(([name, ...sources]) => [name, sources])
  );
}

/** Each `location … { … }` block of nginx.conf (no nested blocks in this file). */
function locations(conf: string): Array<{ path: string; body: string }> {
  return [...conf.matchAll(/location\s+(\S+)\s*\{([^}]*)\}/g)].map((m) => ({ path: m[1], body: m[2] }));
}

describe("nginx security headers", () => {
  it("reach every response: an add_header in a location drops the server's, so each one includes them", () => {
    // nginx inherits add_header « if and only if there are no add_header directives defined on
    // the current level »: with Cache-Control added in / and /assets/, the page itself was served
    // without CSP, X-Frame-Options nor nosniff.
    const conf = read("nginx.conf");
    const server = conf.replace(/location\s+\S+\s*\{[^}]*\}/g, "");
    expect(server).toContain(`include ${SNIPPET};`);
    expect(server).not.toMatch(/add_header/); // only in the snippet, never half-declared here
    for (const { path, body } of locations(conf)) {
      if (/add_header/.test(body)) expect(body, `location ${path}`).toContain(`include ${SNIPPET};`);
    }
    expect(read("Dockerfile")).toContain(`security_headers.conf ${SNIPPET}`);
  });

  it("let the player show its frames, fetched with the token and shown as blob: URLs", () => {
    // Applied to the page, the former img-src 'self' data: blocks every frame (seen in Chromium:
    // « violates the following Content Security Policy directive: img-src 'self' data: »).
    expect(policy()["img-src"]).toContain("blob:");
  });

  it("stay strict everywhere else: no remote origin, no evaluated script", () => {
    const csp = policy();
    expect(csp["default-src"]).toEqual(["'self'"]);
    expect(csp["img-src"]).toEqual(["'self'", "data:", "blob:"]);
    expect(csp["script-src"]).toBeUndefined(); // falls back to default-src 'self'
    for (const sources of Object.values(csp)) {
      expect(sources.filter((s) => /^https?:|^\*$|unsafe-eval/.test(s))).toEqual([]);
    }
    const snippet = read("security_headers.conf");
    for (const header of ["X-Content-Type-Options nosniff", "X-Frame-Options DENY", "Referrer-Policy no-referrer"])
      expect(snippet).toContain(`add_header ${header} always;`);
  });
});
