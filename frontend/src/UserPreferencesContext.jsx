import { createContext, useContext, useState, useEffect, useCallback } from "react";
import { getUserPreferences, updateUserPreferences } from "./api/client";
import { useUsers } from "./ConfigContext";
import { formatCurrency } from "./utils/currency";
import i18n from './i18n';
import { tx } from './localization';

/**
 * A single provider backing date_format, currency, and income-mode-enabled —
 * all three are per-user server-side preferences living on the same
 * UserPreference row, so they're fetched and updated together instead of
 * each maintaining its own independent GET to the same endpoint.
 *
 * Exposed via three separately-named hooks (useDateFormat/useCurrency/
 * useIncomeMode) purely so existing call sites don't need to change.
 */

const CURRENCIES = [
  { code: "USD", symbol: "$", name: "US Dollar" },
  { code: "EUR", symbol: "€", name: "Euro" },
  { code: "GBP", symbol: "£", name: "British Pound" },
  { code: "CAD", symbol: "C$", name: "Canadian Dollar" },
  { code: "AUD", symbol: "A$", name: "Australian Dollar" },
  { code: "INR", symbol: "₹", name: "Indian Rupee" },
  { code: "JPY", symbol: "¥", name: "Japanese Yen" },
  { code: "CNY", symbol: "¥", name: "Chinese Yuan" },
  { code: "CHF", symbol: "CHF", name: "Swiss Franc" },
  { code: "SGD", symbol: "S$", name: "Singapore Dollar" },
  { code: "HKD", symbol: "HK$", name: "Hong Kong Dollar" },
];

const DEFAULT_CURRENCY = "CNY";

// Legacy per-device localStorage keys this context migrates away from, once.
const LEGACY_CURRENCY_KEY = "currency";
const LEGACY_INCOME_MODE_KEY = "income_mode_enabled";

/**
 * ISO dates are always YYYY-MM-DD internally.
 * Display formats: MM/DD/YYYY, DD/MM/YYYY, YYYY/MM/DD, YYYY/DD/MM
 */

function isoToDisplay(isoStr, fmt) {
  if (!isoStr || isoStr.length < 10) return isoStr || "";
  const [y, m, d] = isoStr.substring(0, 10).split("-");
  switch (fmt) {
    case "MM/DD/YYYY": return `${m}/${d}/${y}`;
    case "DD/MM/YYYY": return `${d}/${m}/${y}`;
    case "YYYY/MM/DD": return `${y}/${m}/${d}`;
    case "YYYY/DD/MM": return `${y}/${d}/${m}`;
    default:           return `${d}/${m}/${y}`;
  }
}

function displayToISO(displayStr, fmt) {
  if (!displayStr) return "";
  const parts = displayStr.split("/");
  if (parts.length !== 3) return "";
  let y, m, d;
  switch (fmt) {
    case "MM/DD/YYYY": [m, d, y] = parts; break;
    case "DD/MM/YYYY": [d, m, y] = parts; break;
    case "YYYY/MM/DD": [y, m, d] = parts; break;
    case "YYYY/DD/MM": [y, d, m] = parts; break;
    default:           [d, m, y] = parts; break;
  }
  // Validate
  const yi = parseInt(y, 10);
  const mi = parseInt(m, 10);
  const di = parseInt(d, 10);
  if (isNaN(yi) || isNaN(mi) || isNaN(di)) return "";
  if (mi < 1 || mi > 12 || di < 1 || di > 31) return "";
  return `${String(yi).padStart(4, "0")}-${String(mi).padStart(2, "0")}-${String(di).padStart(2, "0")}`;
}

function getPlaceholder(fmt) {
  return fmt.toLowerCase();
}

function getSeparatorPositions(fmt) {
  // Return indices where "/" should be auto-inserted
  switch (fmt) {
    case "MM/DD/YYYY": return [2, 5];
    case "DD/MM/YYYY": return [2, 5];
    case "YYYY/MM/DD": return [4, 7];
    case "YYYY/DD/MM": return [4, 7];
    default:           return [2, 5];
  }
}

const UserPreferencesContext = createContext(null);

export function UserPreferencesProvider({ children }) {
  const { mode } = useUsers();
  const canUseIncome = mode === "personal" || mode === "blended";

  const [dateFormat, setDateFormatState] = useState("DD/MM/YYYY");
  const [currency, setCurrencyState] = useState(DEFAULT_CURRENCY);
  const [hasChosenCurrency, setHasChosenCurrency] = useState(true);
  const [language, setLanguageState] = useState('en');
  const [hasChosenLanguage, setHasChosenLanguage] = useState(true);
  const [incomeModeEnabled, setIncomeModeState] = useState(false);
  const [timezone, setTimezoneState] = useState(() => localStorage.getItem('famledger_tz') || 'Asia/Shanghai');
  const [loaded, setLoaded] = useState(false);

  const setTimezone = (tz) => {
    setTimezoneState(tz);
    localStorage.setItem('famledger_tz', tz);
  };

  const applyLanguage = useCallback(async (prefs) => {
    const code = prefs.language === 'zh' ? 'zh' : 'en';
    setLanguageState(code);
    setHasChosenLanguage(Boolean(prefs.has_chosen_language));
    await i18n.changeLanguage(code);
    try { localStorage.setItem('famledger_lang', code); } catch {}
  }, []);

  const reloadPreferences = useCallback(async () => {
    try {
      const prefs = await getUserPreferences();
      await applyLanguage(prefs);
      if (prefs.date_format) setDateFormatState(prefs.date_format);

      let resolvedCurrency =
        prefs.currency && CURRENCIES.some((c) => c.code === prefs.currency)
          ? prefs.currency
          : DEFAULT_CURRENCY;
      setCurrencyState(resolvedCurrency);
      if (typeof prefs.has_chosen_currency !== 'undefined') {
        setHasChosenCurrency(Boolean(prefs.has_chosen_currency));
      }
      if (typeof prefs.income_mode_enabled !== 'undefined') {
        setIncomeModeState(Boolean(prefs.income_mode_enabled));
      }
      return prefs;
    } catch {
      return null;
    }
  }, [applyLanguage]);

  useEffect(() => {
    const handleUpdated = () => {
      reloadPreferences();
    };
    window.addEventListener('preferences-updated', handleUpdated);
    return () => {
      window.removeEventListener('preferences-updated', handleUpdated);
    };
  }, [reloadPreferences]);

  useEffect(() => {
    getUserPreferences()
      .then(async (prefs) => {
        await applyLanguage(prefs);
        if (prefs.date_format) setDateFormatState(prefs.date_format);

        let resolvedCurrency =
          prefs.currency && CURRENCIES.some((c) => c.code === prefs.currency)
            ? prefs.currency
            : DEFAULT_CURRENCY;
        let resolvedIncome = Boolean(prefs.income_mode_enabled);

        // One-time migration from the old per-device localStorage settings,
        // so upgrading doesn't silently reset a currency/toggle a user
        // already chose. Only kicks in while the server value is still at
        // its default (i.e. never explicitly set server-side before).
        const legacyCurrency = localStorage.getItem(LEGACY_CURRENCY_KEY);
        const legacyIncomeEnabled = localStorage.getItem(LEGACY_INCOME_MODE_KEY) === "true";
        const migration = {};
        if (
          resolvedCurrency === DEFAULT_CURRENCY &&
          legacyCurrency &&
          legacyCurrency !== DEFAULT_CURRENCY &&
          CURRENCIES.some((c) => c.code === legacyCurrency)
        ) {
          migration.currency = legacyCurrency;
        }
        if (!resolvedIncome && legacyIncomeEnabled) {
          migration.income_mode_enabled = true;
        }
        if (Object.keys(migration).length > 0) {
          try {
            await updateUserPreferences(migration);
            if (migration.currency) resolvedCurrency = migration.currency;
            if (migration.income_mode_enabled) resolvedIncome = true;
          } catch {
            // Best-effort migration — fall back to the server's values.
          }
        }
        localStorage.removeItem(LEGACY_CURRENCY_KEY);
        localStorage.removeItem(LEGACY_INCOME_MODE_KEY);

        setCurrencyState(resolvedCurrency);
        if (typeof prefs.has_chosen_currency !== 'undefined') {
          setHasChosenCurrency(Boolean(prefs.has_chosen_currency));
        }
        setIncomeModeState(resolvedIncome);
      })
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, [applyLanguage]);

  const setLanguage = useCallback(async (code) => {
    const prefs = await updateUserPreferences({ language: code });
    await applyLanguage(prefs);
    window.dispatchEvent(new CustomEvent('preferences-updated'));
  }, [applyLanguage]);

  const chooseInitialCurrency = useCallback(async (code) => {
    await updateUserPreferences({ currency: code, has_chosen_currency: true });
    setCurrencyState(code);
    setHasChosenCurrency(true);
    window.dispatchEvent(new CustomEvent('preferences-updated'));
    window.dispatchEvent(new CustomEvent('accounts-updated'));
  }, []);

  const setDateFormat = useCallback(async (newFormat) => {
    await updateUserPreferences({ date_format: newFormat });
    setDateFormatState(newFormat);
  }, []);

  const setCurrency = useCallback(async (code) => {
    await updateUserPreferences({ currency: code });
    setCurrencyState(code);
    window.dispatchEvent(new CustomEvent("preferences-updated"));
    window.dispatchEvent(new CustomEvent("accounts-updated"));
  }, []);

  const toggleIncome = useCallback(async (val) => {
    await updateUserPreferences({ income_mode_enabled: val });
    setIncomeModeState(val);
  }, []);

  const clearIncome = useCallback(() => {
    toggleIncome(false);
  }, [toggleIncome]);

  const formatDate = useCallback(
    (isoStr) => isoToDisplay(isoStr, dateFormat),
    [dateFormat],
  );

  const parseInputToISO = useCallback(
    (displayStr) => displayToISO(displayStr, dateFormat),
    [dateFormat],
  );

  const toInputValue = useCallback(
    (isoStr) => isoToDisplay(isoStr, dateFormat),
    [dateFormat],
  );

  const [privacyMode, setPrivacyMode] = useState(() => {
    try {
      return localStorage.getItem('privacy_mode') === 'true';
    } catch {
      return false;
    }
  });

  const togglePrivacyMode = useCallback(() => {
    setPrivacyMode((prev) => {
      const next = !prev;
      try {
        localStorage.setItem('privacy_mode', String(next));
      } catch {}
      return next;
    });
  }, []);

  const currentCurrency = CURRENCIES.find((c) => c.code === currency) || CURRENCIES[0];

  const fmt = useCallback(
    (amount, ignorePrivacy = false) => {
      if (privacyMode && !ignorePrivacy) {
        return '••••••';
      }
      return formatCurrency(amount, currentCurrency.symbol);
    },
    [currentCurrency.symbol, privacyMode],
  );

  if (!loaded) return null;

  return (
    <UserPreferencesContext.Provider
      value={{
        // date format
        language,
        hasChosenLanguage,
        setLanguage,
        dateFormat,
        setDateFormat,
        formatDate,
        parseInputToISO,
        toInputValue,
        placeholder: getPlaceholder(dateFormat),
        separatorPositions: getSeparatorPositions(dateFormat),
        // currency & privacy
        currency,
        symbol: currentCurrency.symbol,
        setCurrency,
        setCurrencyState,
        reloadPreferences,
        hasChosenCurrency,
        chooseInitialCurrency,
        fmt,
        currencies: CURRENCIES.map(item => ({ ...item, name: tx(item.name) })),
        privacyMode,
        togglePrivacyMode,
        // timezone
        timezone,
        setTimezone,
        // income mode
        incomeEnabled: incomeModeEnabled && canUseIncome,
        canUseIncome,
        toggleIncome,
        clearIncome,
      }}
    >
      {children}
    </UserPreferencesContext.Provider>
  );
}

export function useDateFormat() {
  return useContext(UserPreferencesContext);
}

export function useCurrency() {
  return useContext(UserPreferencesContext);
}

export function useIncomeMode() {
  return useContext(UserPreferencesContext);
}
