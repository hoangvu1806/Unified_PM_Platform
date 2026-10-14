// Theme shared with the Designer app (same key, same tokens): dark by default.
import { useEffect, useState } from "react";

const KEY = "designer.theme";
type Mode = "light" | "dark";

function resolve(): Mode {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "light" || saved === "dark") return saved;
    if (saved === "system") return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  } catch {
    /* private mode */
  }
  return "dark";
}

export function applyTheme(mode: Mode = resolve()): void {
  document.documentElement.setAttribute("data-theme", mode);
  window.dispatchEvent(new CustomEvent("platform:theme", { detail: mode }));
}

export function toggleTheme(): void {
  const next: Mode = resolve() === "dark" ? "light" : "dark";
  try {
    localStorage.setItem(KEY, next);
  } catch {
    /* ignore */
  }
  applyTheme(next);
}

export function useThemeMode(): Mode {
  const [mode, setMode] = useState<Mode>(resolve());
  useEffect(() => {
    const on = (e: Event) => setMode((e as CustomEvent<Mode>).detail);
    // Another tab (e.g. the Designer opened alone) switched the theme.
    const onStorage = (e: StorageEvent) => {
      if (e.key === KEY) applyTheme(resolve());
    };
    window.addEventListener("platform:theme", on);
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener("platform:theme", on);
      window.removeEventListener("storage", onStorage);
    };
  }, []);
  return mode;
}
