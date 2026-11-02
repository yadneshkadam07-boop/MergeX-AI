import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, ApiError, setAuthToken } from "./http";

describe("http client", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("performs GET request and parses JSON successfully", async () => {
    const mockData = { id: "p1", name: "Demo" };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        statusText: "OK",
        headers: new Headers({ "content-type": "application/json" }),
        json: () => Promise.resolve(mockData),
      }),
    );

    const result = await http.get<{ id: string; name: string }>("/projects");
    expect(result).toEqual(mockData);
  });

  it("injects Authorization Bearer token when present", async () => {
    setAuthToken("secret-token-123");
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/json" }),
      json: () => Promise.resolve({ success: true }),
    });
    vi.stubGlobal("fetch", fetchSpy);

    await http.get("/protected");

    expect(fetchSpy).toHaveBeenCalled();
    const calls = fetchSpy.mock.calls as [string, RequestInit][];
    const init = calls[0]?.[1];
    const headers = new Headers(init?.headers);
    expect(headers.get("Authorization")).toBe("Bearer secret-token-123");
  });

  it("throws ApiError with detail message on 400 error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        statusText: "Bad Request",
        headers: new Headers({ "content-type": "application/json" }),
        text: () => Promise.resolve(JSON.stringify({ detail: "Invalid project ID" })),
      }),
    );

    await expect(http.get("/projects/invalid")).rejects.toThrow("Invalid project ID");
  });

  it("dispatches mergex:unauthorized event on 401 response", async () => {
    setAuthToken("expired-token");
    const unauthorizedListener = vi.fn();
    window.addEventListener("mergex:unauthorized", unauthorizedListener);

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 401,
        statusText: "Unauthorized",
        headers: new Headers({ "content-type": "application/json" }),
        text: () => Promise.resolve(JSON.stringify({ detail: "Token expired" })),
      }),
    );

    await expect(http.get("/secure")).rejects.toThrow(ApiError);
    expect(unauthorizedListener).toHaveBeenCalled();
    expect(localStorage.getItem("mergex_auth_token")).toBeNull();

    window.removeEventListener("mergex:unauthorized", unauthorizedListener);
  });

  it("returns undefined on 204 No Content response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 204,
        statusText: "No Content",
        headers: new Headers(),
      }),
    );

    const result = await http.delete("/item/1");
    expect(result).toBeUndefined();
  });
});
