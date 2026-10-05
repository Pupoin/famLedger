import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import definitions from '../../../backend/account_types.json';
import { ACCOUNT_TYPE_CONFIGS, getAccountTypeConfig, renderAccountLogo, getAccountEmoji } from './accountIcons';
import AccountTypeSelectDropdown, { ACCOUNT_TYPE_OPTIONS } from '../components/AccountTypeSelectDropdown';
import AccountSelectDropdown from '../components/AccountSelectDropdown';

const aliases = Object.entries(definitions).flatMap(([key, definition]) =>
  definition.aliases.map(alias => [alias, definition.display_type]));

describe('all account type icons use the same catalog', () => {
  it.each(aliases)('type %s ignores account metadata and selects %s', (type, expected) => {
    const account = { id: 'example', account_type: type, name: '贷款信用卡基金房产',
      account_name: '贷款', institution_name: '贷款投资信用卡银行',
      external_identifier: 'credit_card:1234', classification: 'wrong' };
    const cfg = getAccountTypeConfig(account);
    expect(cfg.key).toBe(expected);
    expect(getAccountEmoji(account)).toBe(ACCOUNT_TYPE_CONFIGS[expected].emoji);
    const icon = renderToStaticMarkup(renderAccountLogo(account));
    const iconClass = /class="[^"]*\b(lucide-[a-z0-9-]+)\b/.exec(icon)[1];
    const typeSelector = renderToStaticMarkup(<AccountTypeSelectDropdown value={type} />);
    const accountSelector = renderToStaticMarkup(<AccountSelectDropdown accounts={[account]} value={account.id} />);
    expect(typeSelector).toContain(iconClass);
    expect(typeSelector).toMatch(new RegExp(`<option value="${expected}" selected=""`));
    expect(accountSelector).toContain(iconClass);
  });

  it('type menu icons agree with account cards, settings and details', () => {
    expect(new Set(ACCOUNT_TYPE_OPTIONS.map(option => option.value))).toEqual(new Set(Object.keys(ACCOUNT_TYPE_CONFIGS)));
    for (const option of ACCOUNT_TYPE_OPTIONS) {
      expect(option.Icon).toBe(getAccountTypeConfig(option.value).icon);
    }
  });

  it('a debit account stays a deposit icon after all three metadata fields change', () => {
    const first = getAccountTypeConfig({ account_type: 'checking', name: '存款' });
    const renamed = getAccountTypeConfig({ account_type: 'checking', name: '贷款',
      institution_name: '信用卡银行', external_identifier: 'loan:9999', classification: 'liability' });
    expect(renamed).toBe(first);
    expect(renamed.key).toBe('cash');
  });
});
