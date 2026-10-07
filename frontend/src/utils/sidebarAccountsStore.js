// One in-memory snapshot per signed-in layout; financial data is not persisted.
export function createSidebarAccountsStore(load) {
  let state = { accounts: [], accountsError: '', loading: true };
  let version = 0;
  let controller = null;
  let pending = null;
  const listeners = new Set();
  const publish = next => { state = next; listeners.forEach(listener => listener()); };
  const store = {
    getSnapshot: () => state,
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    cancel() {
      version += 1;
      controller?.abort();
      controller = null;
      pending = null;
      if (state.loading) publish({ ...state, loading: false });
    },
    setAccounts(update) {
      // An older request must not restore a locally removed/hidden account.
      store.cancel();
      publish({ ...state, accounts: typeof update === 'function' ? update(state.accounts) : update });
    },
    refresh({ force = false } = {}) {
      if (pending && !force) return pending;
      controller?.abort();
      const request = ++version;
      const currentController = new AbortController();
      controller = currentController;
      publish({ ...state, accountsError: '', loading: true });
      pending = Promise.resolve().then(() => load(currentController.signal)).then(accounts => {
        if (request === version) publish({ accounts, accountsError: '', loading: false });
      }).catch(error => {
        if (request === version && error.name !== 'AbortError') {
          publish({ ...state, accountsError: error.message || '账户加载失败', loading: false });
        }
      }).finally(() => {
        if (request === version) { pending = null; controller = null; }
      });
      return pending;
    },
  };
  return store;
}

export function sidebarBalanceContributions(accounts) {
  const values = new Map(accounts.map(account => [account.id,
    Number(account.report_balance ?? account.balance ?? 0)]));
  for (const account of accounts) {
    if (!account.parent_account_id) continue;
    const share = Number(account.report_settlement_balance ?? account.report_balance ?? account.balance ?? 0);
    values.set(account.id, share);
    if (values.has(account.parent_account_id)) {
      values.set(account.parent_account_id, values.get(account.parent_account_id) - share);
    }
  }
  return values;
}
