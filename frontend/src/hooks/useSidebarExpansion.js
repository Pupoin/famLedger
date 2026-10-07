import { useCallback, useEffect, useSyncExternalStore } from 'react';
import { createSidebarExpansionStore } from '../utils/sidebarExpansionStore';

const store = createSidebarExpansionStore(() => typeof localStorage === 'undefined' ? null : localStorage);
const subscribe = listener => store.subscribe(listener);

export default function useSidebarExpansion(user) {
  const userKey = String(user?.id || user?.username || 'signed-out');
  const snapshot = useCallback(() => store.get(userKey), [userKey]);
  const value = useSyncExternalStore(subscribe, snapshot, snapshot);
  const setValue = useCallback(update => store.set(userKey, update), [userKey]);
  useEffect(() => {
    const changed = event => { if (event.key === null || event.key === store.key(userKey)) store.reload(userKey); };
    window.addEventListener('storage', changed);
    return () => window.removeEventListener('storage', changed);
  }, [userKey]);
  return [value, setValue];
}
