/**
 * Test environment shims.
 *
 * ## `matchMedia` does not exist in jsdom
 *
 * jsdom implements no part of CSS media queries, so `window.matchMedia` is
 * `undefined` rather than a function. `App.initialTheme` calls it to honour the OS
 * preference, which meant every render of the shell threw a `TypeError` under test.
 *
 * The stub is installed here rather than guarded in `App` because this is a gap in the
 * *test environment*, not a runtime condition: every browser this app targets has
 * `matchMedia`, and wrapping the app in a feature check to satisfy a test runner
 * would add a branch no user can reach.
 *
 * The default is `matches: false` (light), so a test that says nothing about the OS
 * preference gets the light theme and an explicit assertion is needed to test dark.
 */
import { afterEach, vi } from "vitest";

if (typeof window.matchMedia !== "function") {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as typeof window.matchMedia;
}

afterEach(() => {
  // Per-test stubbing (`vi.stubGlobal`, a reassigned `matchMedia`) must not leak into
  // the next test. A leaked stub is the classic source of a test that passes only
  // because it ran second.
  vi.unstubAllGlobals();
  window.localStorage.clear();
  document.documentElement.classList.remove("dark");
});