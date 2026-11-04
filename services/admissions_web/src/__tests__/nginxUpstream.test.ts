import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const conf = readFileSync(resolve(__dirname, "../../nginx.conf"), "utf8");
const block = (head: string) => {
  const start = conf.indexOf(head);
  return start < 0 ? "" : conf.slice(start, conf.indexOf("}", start) + 1);
};
const directive = (text: string, name: string) => new RegExp(`^\\s*${name}\\s+([^;]+);`, "m").exec(text)?.[1].trim();

describe("nginx in front of several API processes (règle 28)", () => {
  const upstream = block("upstream hospitalos_api {");
  const api = block("location /api/ {");

  it("spreads the calls over every API address and sets aside one that fails", () => {
    expect(directive(upstream, "server")).toBe("api:8010 max_fails=3 fail_timeout=10s");
    expect(Number(directive(upstream, "keepalive"))).toBeGreaterThan(0);
    expect(directive(api, "proxy_pass")).toBe("http://hospitalos_api");
  });

  it("keeps connections to the API open", () => {
    // keepalive needs HTTP/1.1 and an empty Connection header towards the API.
    expect(directive(api, "proxy_http_version")).toBe("1.1");
    expect(directive(api, "proxy_set_header Connection")).toBe('""');
  });

  it("retries a read on another process once, never a write", () => {
    const retry = directive(api, "proxy_next_upstream")?.split(/\s+/) ?? [];
    expect(retry).toEqual(expect.arrayContaining(["error", "timeout", "http_502", "http_503"]));
    expect(retry).not.toContain("non_idempotent");
    expect(directive(api, "proxy_next_upstream_tries")).toBe("2");
  });
});
