/**
 * The minimum scaffold validation: React mounts, Tailwind's stylesheet resolves, and
 * the theme structure works.
 *
 * This is deliberately one small file. S3.3 step 4 builds a foundation, and the proof
 * that a foundation holds is that it compiles and that the root renders -- not a test
 * suite written ahead of the screens it would cover. Screens bring their own tests.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { API_PROXY_TARGET, rewriteApiPath } from "../dev-proxy";
import { BASE_PATH, ApiError, apiUrl } from "./api/client";

describe("the shell", () => {
  it("mounts React", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: "Brandset" })).toBeDefined();
  });

  it("offers both a light and a dark theme, and switching one moves the class on <html>", () => {
    // The `dark:` variant keys off this class. If it stops being set, every dark
    // token silently stops applying and the app only looks broken in dark mode --
    // which is exactly the failure that would otherwise go unnoticed.
    render(<App />);
    const toggle = screen.getByRole("button", { name: /mode/i });

    expect(document.documentElement.classList.contains("dark")).toBe(false);

    // `fireEvent`, not `toggle.click()`: React only flushes the resulting state
    // update and its effects inside `act`, and a raw DOM click asserts against a
    // render that has not happened yet.
    fireEvent.click(toggle);

    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(toggle.getAttribute("aria-pressed")).toBe("true");
  });

  it("makes no API request on load", () => {
    // The load-bearing assertion of this whole step. Mounting the shell must not
    // depend on the backend being up.
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);

    render(<App />);

    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe("the API client", () => {
  it("builds URLs under /api", () => {
    expect(BASE_PATH).toBe("/api");
    expect(apiUrl("/ads")).toBe("/api/ads");
    expect(apiUrl("/ads", { page: 2, page_size: 25 })).toBe("/api/ads?page=2&page_size=25");
  });

  it("omits a null filter rather than sending the string 'null'", () => {
    // An absent filter is not the filter "null". Sending it would suggest a filter
    // exists when it does not, and the backend rejects it.
    expect(apiUrl("/ads", { page: 1, competitor_id: null })).toBe("/api/ads?page=1");
  });

  it("carries a status and a detail on failure", () => {
    const error = new ApiError(404, "Not Found");
    expect(error.status).toBe(404);
    expect(error.detail).toBe("Not Found");
    expect(error).toBeInstanceOf(Error);
  });
});

describe("the dev proxy", () => {
  it("strips /api, because the backend mounts its routers at the root", () => {
    // Without this the backend receives `/api/ads`, 404s, and the failure looks
    // exactly like the API being down rather than like a path mismatch.
    expect(rewriteApiPath("/api/ads")).toBe("/ads");
    expect(rewriteApiPath("/api/competitors")).toBe("/competitors");
    expect(rewriteApiPath("/api")).toBe("");
  });

  it("leaves a path that merely contains /api alone", () => {
    // The prefix must be anchored. `/api` appearing mid-path is a different route
    // and stripping it there would send the request somewhere unintended.
    expect(rewriteApiPath("/assets/api/logo.svg")).toBe("/assets/api/logo.svg");
  });

  it("points at the backend's origin", () => {
    expect(API_PROXY_TARGET).toBe("http://localhost:8000");
  });
});