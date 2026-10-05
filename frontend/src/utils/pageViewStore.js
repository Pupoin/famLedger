// UI state belongs to a browser history entry, not to the route as a whole.
// A fresh visit starts with defaults; Back/Forward returns to the previous view.
export function createPageViewStore(limit = 100) {
  const entries = new Map();
  const listeners = new Set();

  const entry = (key) => {
    if (!entries.has(key)) {
      entries.set(key, { values: new Map(), scroll: null });
      if (entries.size > limit) entries.delete(entries.keys().next().value);
    }
    return entries.get(key);
  };

  return {
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    get(key, name, initialValue) {
      const values = entry(key).values;
      if (!values.has(name)) {
        values.set(name, typeof initialValue === 'function' ? initialValue() : initialValue);
      }
      return values.get(name);
    },
    set(key, name, value) {
      const values = entry(key).values;
      const next = typeof value === 'function' ? value(values.get(name)) : value;
      if (Object.is(values.get(name), next)) return;
      values.set(name, next);
      listeners.forEach((listener) => listener());
    },
    getScroll(key) {
      return entry(key).scroll;
    },
    setScroll(key, position) {
      entry(key).scroll = position;
    },
  };
}
