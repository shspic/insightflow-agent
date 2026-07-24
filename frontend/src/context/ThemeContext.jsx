import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { normalizeTheme, readThemePreference } from "../utils/ui";

const ThemeContext = createContext(null);
const STORAGE_KEY = "insightflow-theme";

function readInitialTheme() {
  return readThemePreference(window.localStorage, STORAGE_KEY);
}

export function ThemeProvider({ children }) {
  const [theme, setThemeState] = useState(readInitialTheme);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      window.localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      // 浏览器禁用存储时仍保留当前会话主题。
    }
  }, [theme]);

  const value = useMemo(() => ({
    theme,
    setTheme: (nextTheme) => setThemeState(normalizeTheme(nextTheme)),
  }), [theme]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme 必须在 ThemeProvider 内使用");
  return context;
}
