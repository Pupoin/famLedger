import { describe, expect, it, vi } from 'vitest';
import { createSidebarAccountsStore, sidebarBalanceContributions } from './sidebarAccountsStore';

const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};

describe('shared sidebar account loading', () => {
  it('deduplicates simultaneous desktop/mobile loads and keeps loaded rows while refreshing', async () => {
    const next = deferred();
    const load = vi.fn().mockResolvedValueOnce([{ id: 'a', balance: '123.4567' }]).mockReturnValueOnce(next.promise);
    const store = createSidebarAccountsStore(load);
    const first = store.refresh();
    expect(store.refresh()).toBe(first);
    await first;
    expect(load).toHaveBeenCalledTimes(1);
    const refresh = store.refresh();
    expect(store.getSnapshot().accounts[0].balance).toBe('123.4567');
    expect(store.getSnapshot().loading).toBe(true);
    next.resolve([{ id: 'a', balance: '100' }]);
    await refresh;
    expect(store.getSnapshot().accounts[0].balance).toBe('100');
  });

  it('publishes the same snapshot to both sidebar subscribers', async () => {
    const store = createSidebarAccountsStore(async () => [{ id: 'a' }]);
    const desktop = vi.fn(), mobile = vi.fn();
    const close = store.subscribe(mobile);
    store.subscribe(desktop);
    await store.refresh();
    expect(desktop).toHaveBeenCalledTimes(2);
    expect(mobile).toHaveBeenCalledTimes(2);
    close();
    const loaded = store.getSnapshot();
    store.subscribe(mobile);
    expect(store.getSnapshot()).toBe(loaded);
  });

  it('rejects late responses after a newer financial mutation refresh', async () => {
    const old = deferred(), fresh = deferred();
    const store = createSidebarAccountsStore(vi.fn().mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise));
    const before = store.refresh(); await Promise.resolve();
    const after = store.refresh({ force: true }); await Promise.resolve();
    fresh.resolve([{ id: 'a', balance: '200' }]); await after;
    old.resolve([{ id: 'a', balance: '100' }]); await before;
    expect(store.getSnapshot().accounts[0].balance).toBe('200');
  });

  it('does not restore deleted accounts from an older response', async () => {
    const old = deferred();
    const store = createSidebarAccountsStore(() => old.promise);
    store.setAccounts([{ id: 'deleted' }, { id: 'kept' }]);
    const request = store.refresh(); await Promise.resolve();
    store.setAccounts(rows => rows.filter(row => row.id !== 'deleted'));
    old.resolve([{ id: 'deleted' }, { id: 'kept' }]); await request;
    expect(store.getSnapshot().accounts).toEqual([{ id: 'kept' }]);
  });

  it('keeps existing rows and reports a failed background refresh', async () => {
    const store = createSidebarAccountsStore(vi.fn().mockResolvedValueOnce([{ id: 'a' }]).mockRejectedValueOnce(new Error('Unavailable')));
    await store.refresh(); await store.refresh();
    expect(store.getSnapshot()).toEqual({ accounts: [{ id: 'a' }], accountsError: 'Unavailable', loading: false });
  });

  it('clears subscriptions and can reload after Strict Mode effect cleanup', async () => {
    const old = deferred();
    const store = createSidebarAccountsStore(vi.fn().mockReturnValueOnce(old.promise).mockResolvedValueOnce([{ id: 'new' }]));
    const previous = store.refresh(); await Promise.resolve(); store.cancel();
    await store.refresh();
    old.resolve([{ id: 'old' }]); await previous;
    expect(store.getSnapshot().accounts).toEqual([{ id: 'new' }]);
  });

  it('never shares financial rows between separate signed-in layouts', async () => {
    const alice = createSidebarAccountsStore(async () => [{ id: 'private' }]);
    await alice.refresh();
    const bob = createSidebarAccountsStore(async () => []);
    expect(bob.getSnapshot().accounts).toEqual([]);
    await bob.refresh();
    expect(bob.getSnapshot().accounts).toEqual([]);
  });
});

describe('institution / owner / type contributions', () => {
  const master = { id: 'master', report_balance: '500' };
  const child = { id: 'child', parent_account_id: 'master', report_balance: '200' };
  it('counts the group once when both accounts are shown', () => {
    const values = sidebarBalanceContributions([master, child]);
    expect(values.get('master')).toBe(300);
    expect(values.get('child')).toBe(200);
    expect([...values.values()].reduce((sum, value) => sum + value, 0)).toBe(500);
  });
  it('counts the child share when the primary is not authorized or is filtered out', () => {
    expect(sidebarBalanceContributions([child]).get('child')).toBe(200);
  });
  it('uses the converted report amount rather than mixing native currencies', () => {
    expect(sidebarBalanceContributions([{ id: 'usd', balance: '20', report_balance: '140' }]).get('usd')).toBe(140);
  });
  it('keeps a foreign child share at its fixed bank settlement amount', () => {
    expect(sidebarBalanceContributions([{ ...child, report_balance: '800', report_settlement_balance: '700' }]).get('child')).toBe(700);
  });
  it('attributes fixed foreign shares and leaves overpayment on the primary', () => {
    const rows = [{ ...master, report_balance: '-50' },
      { ...child, report_balance: '0', report_settlement_balance: '0' }];
    expect(sidebarBalanceContributions(rows)).toEqual(new Map([['master', -50], ['child', 0]]));
    rows[0].report_balance = '1000';
    rows[1].report_balance = '800';
    rows[1].report_settlement_balance = '700';
    expect(sidebarBalanceContributions(rows)).toEqual(new Map([['master', 300], ['child', 700]]));
  });
});
