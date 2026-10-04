import { createContext, useContext, useState, useEffect } from "react";

const ThemeContext = createContext();

function getInitialMode() {
  try {
    const stored = localStorage.getItem("theme");
    if (["light", "dark", "auto"].includes(stored)) return stored;
  } catch {}
  return "auto";
}

export function ThemeProvider({ children }) {
  const [themeMode, setThemeMode] = useState(getInitialMode);
  const [systemDark, setSystemDark] = useState(() => window.matchMedia("(prefers-color-scheme: dark)").matches);
  const theme = themeMode === 'auto' ? (systemDark ? 'dark' : 'light') : themeMode;

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => setSystemDark(media.matches);
    update();
    media.addEventListener('change', update);
    const syncTab = (event) => {
      if (event.key === 'theme' || event.key === null) {
        setThemeMode(['light', 'dark', 'auto'].includes(event.newValue) ? event.newValue : 'auto');
      }
    };
    window.addEventListener('storage', syncTab);
    return () => {
      media.removeEventListener('change', update);
      window.removeEventListener('storage', syncTab);
    };
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    root.dataset.themeMode = themeMode;
    root.style.colorScheme = theme;
    if (theme === "dark") {
      root.classList.add("dark");
      root.style.backgroundColor = "#09090b";
    } else {
      root.classList.remove("dark");
      root.style.backgroundColor = "#FAFAFA";
    }
    try { localStorage.setItem("theme", themeMode); } catch {}
  }, [theme, themeMode]);

  const toggleTheme = () => setThemeMode((mode) => ({light:'dark', dark:'auto', auto:'light'}[mode]));

  return (
    <ThemeContext.Provider value={{ theme, themeMode, setThemeMode, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  return useContext(ThemeContext);
}
