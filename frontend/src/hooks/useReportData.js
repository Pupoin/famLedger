import { useEffect, useMemo, useSyncExternalStore } from 'react';
import { useAuth } from '../auth/AuthContext';
import { loadReportData, useReportCache } from '../ReportDataContext';
import { createReportResource, subscribeReportUpdates } from '../utils/reportResource';

export default function useReportData(url, currency, failureMessage, retryCount) {
  const { user } = useAuth() || {};
  const userKey = user?.username || '';
  const cache = useReportCache();
  // New filters, display currency or login must start without the old amounts.
  const resource = useMemo(() => cache && url ? cache.get(url, failureMessage)
    : createReportResource(signal => loadReportData(url, signal, failureMessage)),
  [cache, url, currency, userKey, failureMessage]);
  const snapshot = useSyncExternalStore(resource.subscribe, resource.getSnapshot, resource.getSnapshot);

  useEffect(() => {
    if (!url) return;
    // Navigation shares a pending prefetch; revisits still validate with the API.
    resource.refresh({ force: retryCount > 0 });
    if (cache) return;
    const unsubscribe = subscribeReportUpdates(window, () => resource.refresh({ force: true }));
    return () => { unsubscribe(); resource.cancel(); };
  }, [resource, cache, retryCount, url]);

  return snapshot;
}
