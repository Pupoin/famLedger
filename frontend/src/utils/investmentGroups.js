import { normalizeAccountTypeKey } from './accountTypes';

export function investmentGroupKey(accounts) {
  if (!accounts?.length || accounts.some(account => !account.id || normalizeAccountTypeKey(account) !== 'investment')) return '';
  return [...new Set(accounts.map(account => String(account.id)))].sort().join(',');
}

export function sidebarInvestmentGroups(tree, mode) {
  const groups = mode === 'by_type' ? tree : mode === 'owner_by_type'
    ? tree.flatMap(group => group.subgroups || []) : [];
  return [...new Set(groups.map(group => investmentGroupKey(group.accounts)).filter(Boolean))].sort();
}
