import React, { createContext, useContext, useEffect, useMemo } from 'react';
import { useAuth } from './auth/AuthContext';
import { useCurrency } from './CurrencyContext';
import { fetchWithAuth } from './api/fetchWithAuth';
import { createReportCache, subscribeReportUpdates } from './utils/reportResource';

const ReportDataContext = createContext(null);

export async function loadReportData(url, signal, failureMessage) {
  const response = await fetchWithAuth(url, { signal });
  if (!response.ok) {
    const failure = await response.json().catch(() => ({}));
    throw new Error(typeof failure.detail === 'string' ? failure.detail : failureMessage);
  }
  return response.json();
}

export function ReportDataProvider({ children }) {
  const { user } = useAuth();
  const { currency } = useCurrency();
  const userKey = user?.username || '';
  const cache = useMemo(() => createReportCache(loadReportData), [userKey, currency]);
  useEffect(() => {
    const unsubscribe = subscribeReportUpdates(window, () => cache.refreshActive(), () => cache.invalidate());
    const refresh = () => { cache.invalidate(); cache.refreshActive(); };
    const visible = () => { if (document.visibilityState === 'visible') refresh(); };
    window.addEventListener('focus', refresh);
    document.addEventListener('visibilitychange', visible);
    return () => {
      unsubscribe(); cache.cancel();
      window.removeEventListener('focus', refresh);
      document.removeEventListener('visibilitychange', visible);
    };
  }, [cache]);
  return <ReportDataContext.Provider value={cache}>{children}</ReportDataContext.Provider>;
}

export const useReportCache = () => useContext(ReportDataContext);
