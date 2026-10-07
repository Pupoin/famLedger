import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it } from 'vitest';
import i18n from '../i18n';
import DeleteTransactionModal from './DeleteTransactionModal';

const transaction = { id: 'out', name: 'Bank transfer', amount: '100', currency: 'CNY', account_name: 'Source',
  transacted_at: '2026-09-09', original_amount: '100', original_currency: 'CNY',
  paired_transfer: { transfer_id: 'pair', counterpart: { id: 'in', account_name: 'Destination', amount: '14', currency: 'USD', occurred_at: '2026-09-09T08:00:00Z' } },
  deletion_info: { can_delete: true, can_delete_pair: true, transfer_id: 'pair' } };
const render = (changes = {}, scope = null, privacyMode = false) => renderToStaticMarkup(<DeleteTransactionModal
  transaction={{ ...transaction, ...changes }} scope={scope} onScopeChange={() => {}} onConfirm={() => {}}
  onClose={() => {}} deleting={false} privacyMode={privacyMode} />);
beforeEach(() => i18n.changeLanguage('zh'));

describe('paired transfer deletion confirmation', () => {
  it('requires an explicit choice and displays both original currencies and dates', () => {
    const html = render();
    expect(html).toContain('请选择删除范围');
    expect(html).toContain('Source'); expect(html).toContain('Destination');
    expect(html).toContain('¥100.00 CNY'); expect(html).toContain('$14.00 USD');
    expect(html).toContain('2026-09-09');
    expect(html).toMatch(/data-testid="confirm-delete-transaction-btn"[^>]*\sdisabled=""/);
    expect(html).not.toMatch(/type="radio"[^>]*checked/);
  });
  it.each(['single', 'pair'])('enables confirmation after choosing %s', scope => {
    expect(render({}, scope)).not.toMatch(/data-testid="confirm-delete-transaction-btn"[^>]*\sdisabled=""/);
  });
  it('disables deleting both when the counterpart is readonly', () => {
    const html = render({ deletion_info: { ...transaction.deletion_info, can_delete_pair: false,
      pair_reason: '同时删除需要两侧账户的写入权限。' } }, 'pair');
    expect(html).toMatch(/<input[^>]*disabled[^>]*value="pair"/);
    expect(html).toMatch(/data-testid="confirm-delete-transaction-btn"[^>]*\sdisabled=""/);
    expect(html).toContain('同时删除需要两侧账户的写入权限。');
  });
  it('masks amounts while privacy mode is enabled', () => {
    const html = render({}, 'single', true);
    expect(html).toContain('••••••');
    expect(html).not.toContain('100.00'); expect(html).not.toContain('14.00');
  });
  it('explains refund unlinking without offering to delete the associated refund', () => {
    const html = render({ paired_transfer: null, deletion_info: { can_delete: true, linked_refund_count: 2 } });
    expect(html).toContain('关联了 2 笔退款');
    expect(html).toContain('退款流水会保留');
    expect(html).not.toContain('transaction-delete-scope');
  });
  it('translates the choices in English', () => {
    i18n.changeLanguage('en');
    const html = render();
    expect(html).toContain('Delete this paired transfer?');
    expect(html).toContain('Delete both paired transactions');
    expect(html).not.toContain('请选择删除范围');
  });
});
