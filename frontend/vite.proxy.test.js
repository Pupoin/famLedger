import { afterAll, beforeAll, describe, expect, it } from "vitest";
import http from "node:http";
import { rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

describe("API proxy browser origin", () => {
  let backend;
  let frontend;
  let port;
  const cacheDir = fileURLToPath(new URL(`../.cache/vite-proxy-test-${process.pid}/`, import.meta.url));
  const previousTarget = process.env.FAMLEDGER_BACKEND_URL;

  beforeAll(async () => {
    backend = http.createServer((request, response) => {
      let body = "";
      request.on("data", (chunk) => { body += chunk; });
      request.on("end", () => {
        response.writeHead(200, { "Content-Type": "application/json" });
        response.end(JSON.stringify({ headers: request.headers, method: request.method, body }));
      });
    });
    await new Promise((resolve) => backend.listen(0, "127.0.0.1", resolve));
    process.env.FAMLEDGER_BACKEND_URL = `http://127.0.0.1:${backend.address().port}`;
    frontend = await createServer({
      configFile: fileURLToPath(new URL("./vite.config.js", import.meta.url)),
      // The test's proxy target and optimizer config differ from the running
      // dev server. Sharing its cache invalidates browser dependency URLs.
      cacheDir,
      server: { host: "127.0.0.1", port: 0 },
      optimizeDeps: { noDiscovery: true, include: [] },
      logLevel: "silent",
    });
    await frontend.listen();
    port = frontend.httpServer.address().port;
  });

  afterAll(async () => {
    await frontend?.close();
    if (backend) await new Promise((resolve) => backend.close(resolve));
    if (previousTarget === undefined) delete process.env.FAMLEDGER_BACKEND_URL;
    else process.env.FAMLEDGER_BACKEND_URL = previousTarget;
    await rm(cacheDir, { recursive: true, force: true });
  });

  function post(hostname, origin) {
    return new Promise((resolve, reject) => {
      const request = http.request({
        hostname: "127.0.0.1", port, path: "/api/auth/login", method: "POST",
        headers: {
          Host: `${hostname}:${port}`, Origin: origin,
          Cookie: "famledger_session=stale-browser-cookie",
          "Content-Type": "application/json", "X-FamLedger-CSRF": "1",
        },
      }, (response) => {
        let body = "";
        response.on("data", (chunk) => { body += chunk; });
        response.on("end", () => {
          try { resolve(JSON.parse(body)); } catch (error) { reject(error); }
        });
      });
      request.on("error", reject);
      request.end(JSON.stringify({ username: "test", password: "test-only" }));
    });
  }

  it.each(["localhost", "127.0.0.1", "192.168.5.11"])("preserves %s Host, Origin, and auth payload", async (hostname) => {
    const origin = `http://${hostname}:${port}`;
    const forwarded = await post(hostname, origin);
    expect(forwarded.headers.host).toBe(`${hostname}:${port}`);
    expect(forwarded.headers.origin).toBe(origin);
    expect(forwarded.headers.cookie).toBe("famledger_session=stale-browser-cookie");
    expect(forwarded.headers["x-famledger-csrf"]).toBe("1");
    expect(forwarded.method).toBe("POST");
    expect(JSON.parse(forwarded.body)).toEqual({ username: "test", password: "test-only" });
  });

  it("keeps an untrusted Origin intact so the backend can reject it", async () => {
    const forwarded = await post("localhost", "https://evil.example");
    expect(forwarded.headers.host).toBe(`localhost:${port}`);
    expect(forwarded.headers.origin).toBe("https://evil.example");
  });
});
