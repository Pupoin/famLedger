import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it } from 'vitest';
import i18n from '../i18n';
import TransactionAccountFlow from './TransactionAccountFlow';

beforeEach(() => i18n.changeLanguage('zh'));

const transaction = {
  account_id: 'own', account_name: '招商银行 7931', account_is_owner: true, account_owner_name: 'Alice',
  transfer_peer_account: '招商银行 9459', transfer_peer_is_owner: false, transfer_peer_owner_name: 'Bob',
  transfer_is_outflow: false,
};
const render = (changes = {}, fallbackAccount) => renderToStaticMarkup(
  <TransactionAccountFlow transaction={{ ...transaction, ...changes }} fallbackAccount={fallbackAccount} />);
const owners = html => (html.match(/data-testid="transfer-account-owner"/g) || []).length;

describe('ownership labels on both transfer accounts', () => {
  it.each([true, false])('marks the shared peer with a user icon for outgoing=%s', outgoing => {
    const html = render({ transfer_is_outflow: outgoing });
    expect(owners(html)).toBe(1);
    expect(html).toContain('lucide-users');
    expect(html).toContain('Bob');
    expect(html).not.toContain('Alice');
    expect(html.indexOf('招商银行 7931') < html.indexOf('招商银行 9459')).toBe(outgoing);
  });

  it.each([true, false])('also marks a shared primary account for outgoing=%s', outgoing => {
    const html = render({ account_is_owner: false, transfer_peer_is_owner: true, transfer_is_outflow: outgoing });
    expect(owners(html)).toBe(1);
    expect(html).toContain('Alice');
    expect(html).not.toContain('Bob');
  });

  it('independently labels two accounts shared by different users', () => {
    const html = render({ account_is_owner: false });
    expect(owners(html)).toBe(2);
    expect(html).toContain('Alice');
    expect(html).toContain('Bob');
  });

  it('shows only account names when both belong to the viewer', () => {
    const html = render({ transfer_peer_is_owner: true });
    expect(owners(html)).toBe(0);
    expect(html).not.toContain('Alice');
    expect(html).not.toContain('Bob');
  });

  it('keeps the ownership flag authoritative when display names are identical', () => {
    const html = render({ transfer_peer_owner_name: 'Alice' });
    expect(owners(html)).toBe(1);
    expect(html).toContain('Alice');
  });

  it('keeps the shared primary label on an unpaired incoming transfer', () => {
    const html = render({ account_is_owner: false, transfer_peer_account: null,
      transfer_peer_owner_name: null, transfer_peer_is_owner: null });
    expect(owners(html)).toBe(1);
    expect(html).toContain('Alice');
    expect(html).toContain('外部账户');
    expect(html.indexOf('外部账户')).toBeLessThan(html.indexOf('招商银行 7931'));
  });

  it('uses explicit direction before narration for an unpaired transfer', () => {
    const html = render({ transfer_is_outflow: null, transfer_peer_account: null,
      transfer_peer_owner_name: null, funds_direction: 'outflow', narration: '收到转账后退回' });
    expect(html.indexOf('招商银行 7931')).toBeLessThan(html.indexOf('外部账户'));
  });

  it('never replaces a subsidiary card with the parent page account', () => {
    const html = render({ account_is_owner: false }, { id: 'parent', name: 'Parent', is_owner: true });
    expect(html).toContain('招商银行 7931');
    expect(html).not.toContain('Parent');
    expect(owners(html)).toBe(2);
  });

  it('uses the current account ownership as a fallback without comparing usernames', () => {
    const html = render({ account_name: null, account_is_owner: undefined, account_owner_name: null },
      { id: 'own', name: 'Shared account', is_owner: false, owner: 'Carol' });
    expect(html).toContain('Carol');
    expect(html).toContain('Shared account');
    expect(owners(html)).toBe(2);
  });

  it('does not expose an owner label for a redacted private peer', () => {
    const html = render({ transfer_peer_account: '私有账户', transfer_peer_owner_name: '私有成员' });
    expect(html).toContain('私有账户');
    expect(html).not.toContain('私有成员');
    expect(owners(html)).toBe(0);
  });

  it('translates the ownership tooltip in English', async () => {
    await i18n.changeLanguage('en');
    const html = render();
    expect(html).toContain('Bob');
    expect(html).not.toContain('共享');
    expect(html).toContain('title=');
  });

  it('shows an identified readonly source and owner without claiming a paired transfer', () => {
    const html = render({ transfer_peer_account: null, transfer_peer_is_owner: null, transfer_peer_owner_name: null,
      transfer_counterparty: { account_name: '招商银行 9459', owner_name: 'Bob', is_owner: false } });
    expect(html).toContain('招商银行 9459');
    expect(html).toContain('Bob');
    expect(html).toContain('未配对');
    expect(html).not.toContain('外部账户');
    expect(owners(html)).toBe(1);
  });

  it('does not label an actual paired transfer as unpaired', () => {
    const html = render({ transfer_id: 'confirmed-pair',
      transfer_counterparty: { account_name: 'Former account', owner_name: 'Former owner', is_owner: false } });
    expect(html).toContain('Bob');
    expect(html).toContain('招商银行 9459');
    expect(html).not.toContain('未配对');
    expect(html).not.toContain('Former account');
  });
});
