import definitions from '../../../backend/account_types.json';

const aliases = new Map(Object.entries(definitions).flatMap(([key, definition]) =>
  definition.aliases.map(alias => [alias.toLowerCase(), key])));

export function canonicalAccountType(account) {
  const value = typeof account === 'string' ? account : account?.account_type;
  return aliases.get(String(value || '').trim().toLowerCase()) || null;
}

export function normalizeAccountTypeKey(account) {
  if (!account) return 'cash';
  return definitions[canonicalAccountType(account)]?.display_type || 'other_asset';
}

export function getAccountClassification(account) {
  return definitions[canonicalAccountType(account)]?.classification || null;
}

export const isLiabilityAccount = account => getAccountClassification(account) === 'liability';

export function accountMatchesScope(account, scope) {
  return scope === 'all' || getAccountClassification(account) === scope;
}

export function accountOutsideScope(accounts, pathname, scope) {
  const id = /^\/accounts\/([^/?]+)\/?$/.exec(pathname)?.[1];
  if (!id || scope === 'all') return false;
  const account = accounts.find(row => String(row.id) === id);
  return !!account && (account.hidden_in_sidebar || !accountMatchesScope(account, scope));
}
