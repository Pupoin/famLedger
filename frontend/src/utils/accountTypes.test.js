import { describe, expect, it } from 'vitest';
import { canonicalAccountType, normalizeAccountTypeKey, getAccountClassification,
  accountMatchesScope, accountOutsideScope } from './accountTypes';
import { getAccountTypeConfig } from './accountIcons';

describe('account type is authoritative', () => {
  it.each(['贷款', '房贷', '借呗', '信用卡', '股票投资', '基金', '加密资产'])('ignores %s in cash account metadata', name => {
    const account = { account_type: 'checking', classification: 'liability', name,
      account_name: name, institution_name: name };
    expect(normalizeAccountTypeKey(account)).toBe('cash');
    expect(getAccountClassification(account)).toBe('asset');
    expect(accountMatchesScope(account, 'asset')).toBe(true);
    expect(accountMatchesScope(account, 'liability')).toBe(false);
    expect(getAccountTypeConfig(account).key).toBe('cash');
  });

  it.each([[' loan ', 'loan', 'liability'], ['抵押贷款', 'loan', 'liability'],
    ['借款', 'loan', 'liability'], ['信用卡', 'credit_card', 'liability'],
    ['借出款', 'iou', 'asset'], ['brokerage', 'investment', 'asset']])('normalizes explicit type %s', (type, key, classification) => {
    const account = { account_type: type, name: '现金信用卡贷款基金', classification: 'wrong' };
    expect(canonicalAccountType(account)).toBe(key);
    expect(normalizeAccountTypeKey(account)).toBe(key);
    expect(getAccountClassification(account)).toBe(classification);
  });

  it('identifies a selected account that is outside the new scope', () => {
    const accounts = [{ id: 'asset', account_type: 'cash', name: '贷款' },
      { id: 'debt', account_type: 'loan', name: '现金' }];
    expect(accountOutsideScope(accounts, '/accounts/asset', 'liability')).toBe(true);
    expect(accountOutsideScope(accounts, '/accounts/debt', 'liability')).toBe(false);
    expect(accountOutsideScope(accounts, '/accounts/asset', 'all')).toBe(false);
    expect(accountOutsideScope(accounts, '/analytics', 'liability')).toBe(false);
  });

  it('never guesses a missing type from names or classification', () => {
    expect(canonicalAccountType({ name: '贷款', classification: 'liability' })).toBeNull();
    expect(accountMatchesScope({ name: '贷款', classification: 'liability' }, 'liability')).toBe(false);
  });
});
