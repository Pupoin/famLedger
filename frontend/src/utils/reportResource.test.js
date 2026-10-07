import { afterEach, describe, expect, it, vi } from 'vitest';
import { createReportCache, createReportResource, subscribeReportUpdates } from './reportResource';

const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};

afterEach(() => vi.useRealTimers());

describe('mounted report refresh', () => {
  it('keeps the displayed charts while refreshing the same query', async () => {
    const next = deferred();
    const data = { amount: 100 };
    const load = vi.fn().mockResolvedValueOnce(data).mockReturnValueOnce(next.promise);
    const report = createReportResource(load);
    await report.refresh();
    const refreshing = report.refresh();
    expect(report.getSnapshot()).toEqual({ data, loading: true, error: '' });
    expect(report.refresh()).toBe(refreshing);
    next.resolve({ amount: 80 });
    await refreshing;
    expect(report.getSnapshot().data.amount).toBe(80);
    expect(load).toHaveBeenCalledTimes(2);
  });

  it('ignores late responses from a cancelled refresh and can restart', async () => {
    const old = deferred();
    const signals = [];
    const load = vi.fn(signal => { signals.push(signal); return old.promise; });
    const report = createReportResource(load);
    const previous = report.refresh();
    await Promise.resolve();
    report.cancel();
    load.mockResolvedValueOnce({ amount: 20 });
    await report.refresh();
    old.resolve({ amount: 999 });
    await previous;
    expect(signals[0].aborted).toBe(true);
    expect(report.getSnapshot().data.amount).toBe(20);
  });

  it('replaces an active request without accepting its late failure', async () => {
    const old = deferred();
    const load = vi.fn().mockReturnValueOnce(old.promise).mockResolvedValueOnce({ amount: 30 });
    const report = createReportResource(load);
    const previous = report.refresh();
    await Promise.resolve();
    await report.refresh({ force: true });
    old.reject(new Error('old request failed'));
    await previous;
    expect(report.getSnapshot()).toEqual({ data: { amount: 30 }, loading: false, error: '' });
  });

  it('does not present a failed refresh as current financial data', async () => {
    const load = vi.fn().mockResolvedValueOnce({ amount: 100 }).mockRejectedValueOnce(new Error('permission revoked'));
    const report = createReportResource(load);
    await report.refresh();
    await report.refresh();
    expect(report.getSnapshot()).toEqual({ data: null, loading: false, error: 'permission revoked' });
  });

  it('starts a different filter, currency or user without reusing the previous data', async () => {
    const old = createReportResource(() => Promise.resolve({ amount: 100 }));
    await old.refresh();
    const next = createReportResource(() => Promise.resolve({ amount: 200 }));
    expect(next.getSnapshot()).toEqual({ data: null, loading: true, error: '' });
  });

  it('combines transaction/account events into one refresh and cancels on unmount', () => {
    vi.useFakeTimers();
    const target = new EventTarget();
    const refresh = vi.fn();
    const unsubscribe = subscribeReportUpdates(target, refresh);
    for (const event of ['transaction-deleted', 'transaction-added', 'accounts-updated']) {
      target.dispatchEvent(new Event(event));
    }
    vi.advanceTimersByTime(50);
    expect(refresh).toHaveBeenCalledTimes(1);
    target.dispatchEvent(new Event('preferences-updated'));
    unsubscribe();
    vi.advanceTimersByTime(100);
    target.dispatchEvent(new Event('transaction-updated'));
    vi.advanceTimersByTime(100);
    expect(refresh).toHaveBeenCalledTimes(1);
  });
});

describe('signed-in report cache', () => {
  it('reuses a pending navigation prefetch, then shows recent data during revalidation', async () => {
    const response = deferred();
    const load = vi.fn().mockReturnValueOnce(response.promise).mockResolvedValueOnce({ amount: 80 });
    const cache = createReportCache(load);
    const prefetched = cache.get('/report?month=10', 'failed');
    const pending = prefetched.refresh();
    const page = cache.get('/report?month=10', 'failed');
    expect(page).toBe(prefetched);
    expect(page.refresh()).toBe(pending);
    response.resolve({ amount: 100 });
    await pending;
    expect(cache.get('/report?month=10', 'failed').getSnapshot().data.amount).toBe(100);
    await page.refresh();
    expect(page.getSnapshot().data.amount).toBe(80);
    expect(load).toHaveBeenCalledTimes(2);
  });

  it('does not reuse amounts from another filter or another login/currency cache', async () => {
    const load = vi.fn().mockResolvedValue({ amount: 100 });
    const first = createReportCache(load);
    await first.get('/report?month=10', 'failed').refresh();
    expect(first.get('/report?month=09', 'failed').getSnapshot().data).toBeNull();
    expect(createReportCache(load).get('/report?month=10', 'failed').getSnapshot().data).toBeNull();
  });

  it('expires an inactive snapshot after 30 seconds', async () => {
    let clock = 0;
    const cache = createReportCache(() => Promise.resolve({ amount: 100 }), { now: () => clock });
    await cache.get('/report', 'failed').refresh();
    clock = 29999;
    expect(cache.get('/report', 'failed').getSnapshot().data.amount).toBe(100);
    clock = 30000;
    expect(cache.get('/report', 'failed').getSnapshot().data).toBeNull();
  });

  it('invalidates inactive data immediately and ignores a pre-edit pending response', async () => {
    const response = deferred();
    const load = vi.fn().mockResolvedValueOnce({ amount: 100 }).mockReturnValueOnce(response.promise);
    const cache = createReportCache(load);
    const resource = cache.get('/report', 'failed');
    await resource.refresh();
    const previous = resource.refresh();
    await Promise.resolve();
    cache.invalidate();
    expect(resource.getSnapshot().data).toBeNull();
    response.resolve({ amount: 200 });
    await previous;
    expect(resource.getSnapshot().data).toBeNull();
  });

  it('refreshes a mounted report and retains its charts while changed data is loading', async () => {
    const next = deferred();
    const load = vi.fn().mockResolvedValueOnce({ amount: 100 }).mockReturnValueOnce(next.promise);
    const cache = createReportCache(load);
    const active = cache.get('/report', 'failed');
    const unsubscribe = active.subscribe(() => {});
    await active.refresh();
    const hidden = cache.get('/other-report', 'failed');
    cache.invalidate(); cache.refreshActive();
    expect(active.getSnapshot()).toEqual({ data: { amount: 100 }, loading: true, error: '' });
    expect(hidden.getSnapshot().data).toBeNull();
    next.resolve({ amount: 80 });
    await active.refresh();
    expect(active.getSnapshot().data.amount).toBe(80);
    expect(load).toHaveBeenCalledTimes(2);
    unsubscribe();
  });

  it('does not reuse changed data if navigation happens before the debounced refresh', async () => {
    const cache = createReportCache(() => Promise.resolve({ amount: 100 }));
    const active = cache.get('/report', 'failed');
    const unsubscribe = active.subscribe(() => {});
    await active.refresh();
    cache.invalidate();
    expect(active.getSnapshot().data.amount).toBe(100);
    unsubscribe();
    expect(cache.get('/report', 'failed').getSnapshot().data).toBeNull();
  });

  it('bounds inactive cached reports and cancels evicted requests', async () => {
    let signal;
    const cache = createReportCache((url, currentSignal) => {
      signal = currentSignal;
      return new Promise(() => {});
    }, { limit: 2 });
    const oldest = cache.get('/first', 'failed');
    oldest.refresh();
    await Promise.resolve();
    cache.get('/second', 'failed'); cache.get('/third', 'failed');
    expect(signal.aborted).toBe(true);
    expect(cache.get('/first', 'failed')).not.toBe(oldest);
  });
});
