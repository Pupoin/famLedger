import { createLatestRequest } from './latestRequest';

// A mounted report's snapshot; never persisted or shared across query/user keys.
export function createReportResource(load, now = Date.now) {
  let state = { data: null, loading: true, error: '' };
  let pending = null;
  let loadedAt = null;
  const requests = createLatestRequest();
  const listeners = new Set();
  const publish = next => { state = next; listeners.forEach(listener => listener()); };
  return {
    getSnapshot: () => state,
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    hasSubscribers: () => listeners.size > 0,
    isRecent: maxAge => loadedAt !== null && now() - loadedAt < maxAge,
    cancel() { requests.cancel(); pending = null; },
    invalidate({ discard = false } = {}) {
      requests.cancel(); pending = null; loadedAt = null;
      publish({ data: discard ? null : state.data, loading: true, error: '' });
    },
    refresh({ force = false } = {}) {
      if (pending && !force) return pending;
      const request = requests.start({ replace: force });
      publish({ ...state, loading: true, error: '' });
      pending = Promise.resolve().then(() => load(request.signal)).then(data => {
        if (request.isCurrent()) {
          loadedAt = now();
          publish({ data, loading: false, error: '' });
        }
      }).catch(error => {
        if (request.isCurrent()) {
          loadedAt = null;
          publish({ data: null, loading: false, error: error.message || '请求失败' });
        }
      }).finally(() => {
        if (request.isCurrent()) { pending = null; request.finish(); }
      });
      return pending;
    },
  };
}

export function subscribeReportUpdates(target, refresh, invalidate) {
  const events = ['transaction-added', 'transaction-updated', 'transaction-deleted',
    'accounts-updated', 'preferences-updated'];
  let timer;
  const schedule = event => {
    invalidate?.(event);
    clearTimeout(timer);
    timer = setTimeout(refresh, 50);
  };
  events.forEach(event => target.addEventListener(event, schedule));
  return () => {
    clearTimeout(timer);
    events.forEach(event => target.removeEventListener(event, schedule));
  };
}

// Bounded to this signed-in user's layout. Every revisit revalidates; only a
// recent, unmodified query may be shown while its new response is pending.
export function createReportCache(load, { limit = 8, maxAge = 30000, now = Date.now } = {}) {
  const resources = new Map();
  return {
    get(url, failureMessage) {
      const key = JSON.stringify([url, failureMessage]);
      let resource = resources.get(key);
      if (resource) {
        if (!resource.hasSubscribers() && !resource.isRecent(maxAge) && resource.getSnapshot().data !== null) {
          resource.invalidate({ discard: true });
        }
        resources.delete(key);
      } else {
        resource = createReportResource(signal => load(url, signal, failureMessage), now);
      }
      resources.set(key, resource);
      if (resources.size > limit) {
        for (const [candidate, unused] of resources) {
          if (candidate !== key && !unused.hasSubscribers()) {
            unused.cancel(); resources.delete(candidate);
            if (resources.size <= limit) break;
          }
        }
      }
      return resource;
    },
    invalidate() {
      resources.forEach(resource => resource.invalidate({ discard: !resource.hasSubscribers() }));
    },
    refreshActive() {
      resources.forEach(resource => { if (resource.hasSubscribers()) resource.refresh(); });
    },
    cancel() { resources.forEach(resource => resource.cancel()); },
  };
}
