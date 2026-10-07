// Only UI preferences are persisted, separately for each signed-in user.
export function createSidebarExpansionStore(storage) {
  const entries = new Map();
  const listeners = new Set();
  const prefix = 'famledger_sidebar_expansion:';
  const sanitize = value => Object.fromEntries(Object.entries(value && typeof value === 'object' && !Array.isArray(value) ? value : {})
    .filter(([key, expanded]) => key.length <= 250 && typeof expanded === 'boolean').slice(0, 500));
  const read = user => {
    try { return sanitize(JSON.parse(storage()?.getItem(prefix + user) || '{}')); }
    catch { return {}; }
  };
  return {
    key: user => prefix + user,
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    get(user) { if (!entries.has(user)) entries.set(user, read(user)); return entries.get(user); },
    set(user, update) {
      const previous = this.get(user);
      const next = sanitize(typeof update === 'function' ? update(previous) : update);
      entries.set(user, next);
      try { storage()?.setItem(prefix + user, JSON.stringify(next)); } catch { /* Keep working without browser storage. */ }
      listeners.forEach(listener => listener());
    },
    reload(user) { entries.set(user, read(user)); listeners.forEach(listener => listener()); },
  };
}
