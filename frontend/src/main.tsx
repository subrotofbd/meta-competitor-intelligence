import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./styles/index.css";

/**
 * Entry point.
 *
 * The theme class is set **before** `createRoot`, not in an effect. React mounts after
 * the first paint opportunity, so a class applied in an effect would flash the light
 * theme at a dark-mode user on every load. This is a one-line script rather than
 * something clever precisely because it must run synchronously, early.
 *
 * It reads the same storage key and OS preference as `App`, so the first render
 * already has the right class and React's own `useEffect` then just persists the
 * user's next choice.
 */
const stored = window.localStorage.getItem("brandset.theme");
const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
const theme = stored === "light" || stored === "dark" ? stored : prefersDark ? "dark" : "light";
document.documentElement.classList.toggle("dark", theme === "dark");

const container = document.getElementById("root");
if (!container) {
  // A missing mount point means index.html and this file disagree, which is a build
  // error, not a runtime condition to recover from.
  throw new Error("#root is missing from index.html");
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);