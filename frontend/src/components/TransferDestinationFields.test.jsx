import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it } from 'vitest';
import i18n from '../i18n';
import TransferDestinationFields from './TransferDestinationFields';

beforeEach(() => i18n.changeLanguage('zh'));
const accounts = [{ id: 'source', name: 'Source', currency: 'CNY', can_edit: true },
  { id: 'target', name: 'Target', currency: 'CNY', can_edit: true },
  { id: 'usd', name: 'Dollar', currency: 'USD', can_edit: true },
  { id: 'readonly', name: 'Readonly', currency: 'CNY', can_edit: false }];
const render = (changes = {}) => renderToStaticMarkup(<TransferDestinationFields
  transaction={{ account_id: 'source', account_name: 'Source', currency: 'CNY' }} accounts={accounts}
  sourceAccountId="source" direction="outflow" onSourceChange={() => {}} onDirectionChange={() => {}}
  destinationId="target" onDestinationChange={() => {}} peerAmount="" onAmountChange={() => {}} {...changes} />);
const selector = (html, name) => html.match(new RegExp(`<select[^>]*name="${name}"[\\s\\S]*?</select>`))[0];

describe('transfer editor', () => {
  it('allows selecting both accounts, excluding the opposite account and readonly accounts', () => {
    const html = render();
    const from = selector(html, 'from_account_id'), to = selector(html, 'to_account_id');
    expect(from).toContain('value="source"'); expect(from).not.toContain('value="target"');
    expect(to).toContain('value="target"'); expect(to).not.toContain('value="source"');
    expect(html).not.toContain('value="readonly"');
  });
  it('requires the actual counterpart amount for different currencies on either side', () => {
    expect(render({ destinationId: 'usd' })).toMatch(/required=""[^>]*data-testid="edit-peer-transfer-amount"/);
    const incoming = render({ direction: 'inflow', sourceAccountId: 'usd', destinationId: 'source' });
    expect(incoming).toMatch(/required=""[^>]*data-testid="edit-peer-transfer-amount"/);
    expect(incoming).toContain('实际转出金额');
    expect(render()).not.toContain('edit-peer-transfer-amount');
  });
  it('shows the direction selector only for an unpaired transaction', () => {
    expect(render()).toContain('edit-transfer-direction');
    expect(render({ transaction: { currency: 'CNY', paired_transfer: { is_outflow: true, counterpart: { account_id: 'target' } } } }))
      .not.toContain('edit-transfer-direction');
  });
  it('keeps both account selectors editable when opening the incoming side of a pair', () => {
    const html = render({ direction: 'inflow', transaction: { account_id: 'target', currency: 'CNY',
      paired_transfer: { is_outflow: false, counterpart: { account_id: 'source', account_name: 'Source', currency: 'CNY' } } } });
    for (const name of ['from_account_id', 'to_account_id']) {
      expect(selector(html, name).split('>')[0]).not.toMatch(/\sdisabled(?:=|\s|>)/);
    }
    expect(html).toContain('edit-transfer-flow');
  });
  it('keeps a readonly counterpart visible and prevents changing its account', () => {
    const html = render({ direction: 'inflow', sourceAccountId: 'readonly', destinationId: 'source',
      transaction: { account_id: 'source', currency: 'CNY', paired_transfer: { is_outflow: false,
        counterpart: { account_id: 'readonly', account_name: 'Readonly', currency: 'CNY' } } } });
    expect(html).toContain('Readonly');
    expect(selector(html, 'from_account_id').split('>')[0]).toMatch(/\sdisabled(?:=|\s|>)/);
  });
});
