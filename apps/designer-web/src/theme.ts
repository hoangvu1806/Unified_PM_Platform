import { useEffect, useState } from "react";

export type ThemeMode = "light" | "dark" | "system";

const THEME_STORAGE_KEY = "designer.theme";

export function getSystemTheme(): "light" | "dark" {
    if (typeof window === "undefined") return "dark";
    return window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light";
}

export function getSavedTheme(): ThemeMode {
    try {
        const saved = localStorage.getItem(THEME_STORAGE_KEY);
        if (saved === "light" || saved === "dark" || saved === "system") {
            return saved;
        }
    } catch {
        // fallback
    }
    return "dark"; // Default to modern dark theme
}

export function applyTheme(mode: ThemeMode) {
    const resolved = mode === "system" ? getSystemTheme() : mode;
    document.documentElement.setAttribute("data-theme", resolved);
    document.documentElement.classList.remove("theme-light", "theme-dark");
    document.documentElement.classList.add(`theme-${resolved}`);

    const metaThemeColor = document.querySelector('meta[name="theme-color"]');
    if (metaThemeColor) {
        metaThemeColor.setAttribute(
            "content",
            resolved === "dark" ? "#0f1117" : "#f8f9fa",
        );
    }
}

export function useTheme() {
    const [theme, setThemeState] = useState<ThemeMode>(getSavedTheme);

    const setTheme = (newTheme: ThemeMode) => {
        setThemeState(newTheme);
        try {
            localStorage.setItem(THEME_STORAGE_KEY, newTheme);
        } catch {
            // storage error ignored
        }
        applyTheme(newTheme);
    };

    const toggleTheme = () => {
        const resolved = theme === "system" ? getSystemTheme() : theme;
        setTheme(resolved === "dark" ? "light" : "dark");
    };

    useEffect(() => {
        applyTheme(theme);

        if (theme === "system") {
            const mediaQuery = window.matchMedia(
                "(prefers-color-scheme: dark)",
            );
            const handler = () => {
                applyTheme("system");
            };
            mediaQuery.addEventListener("change", handler);
            return () => mediaQuery.removeEventListener("change", handler);
        }
    }, [theme]);

    const resolvedTheme = theme === "system" ? getSystemTheme() : theme;

    return { theme, resolvedTheme, setTheme, toggleTheme };
}
