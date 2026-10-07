import { useEffect, useMemo, useSyncExternalStore } from 'react';
import { fetchWithAuth } from '../api/fetchWithAuth';
import { createSidebarAccountsStore } from '../utils/sidebarAccountsStore';

export default function useSidebarAccounts(user, currency) {
  const userKey = user?.id || user?.username || '';
  // Never relabel amounts cached in the previous display currency while the
  // new currency's response is pending or unavailable.
  const store = useMemo(() => createSidebarAccountsStore(async signal => {
    if (!userKey) return [];
    const response = await fetchWithAuth('/api/v1/accounts', { signal });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(typeof error.detail === 'string' ? error.detail : '账户加载失败');
    }
    const data = await response.json();
    return Array.isArray(data) ? data : data.accounts || data.items || [];
  }), [userKey, currency]);
  const snapshot = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);

  useEffect(() => {
    store.refresh({ force: true });
    let timer;
    const refresh = () => {
      clearTimeout(timer);
      timer = setTimeout(() => store.refresh({ force: true }), 50);
    };
    const updated = event => {
      if (event.detail?.deletedAccountId) {
        store.setAccounts(accounts => accounts.filter(account => account.id !== event.detail.deletedAccountId));
      }
      if (typeof event.detail?.hiddenInSidebar === 'boolean') {
        store.setAccounts(accounts => accounts.map(account => account.id === event.detail.accountId
          ? { ...account, hidden_in_sidebar: event.detail.hiddenInSidebar } : account));
      }
      refresh();
    };
    window.addEventListener('accounts-updated', updated);
    for (const event of ['transaction-added', 'transaction-updated', 'transaction-deleted']) {
      window.addEventListener(event, refresh);
    }
    // Refresh revoked sharing / external imports without delaying drawer opening.
    window.addEventListener('focus', refresh);
    const visible = () => { if (document.visibilityState === 'visible') refresh(); };
    document.addEventListener('visibilitychange', visible);
    return () => {
      clearTimeout(timer);
      store.cancel();
      window.removeEventListener('accounts-updated', updated);
      for (const event of ['transaction-added', 'transaction-updated', 'transaction-deleted']) {
        window.removeEventListener(event, refresh);
      }
      window.removeEventListener('focus', refresh);
      document.removeEventListener('visibilitychange', visible);
    };
  }, [store, currency]);

  return { ...snapshot, fetchAccounts: () => store.refresh({ force: true }), refreshAccounts: () => store.refresh() };
}
