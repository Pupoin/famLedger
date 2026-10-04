import i18n from '../i18n';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it } from 'vitest';
import TransactionAmount from './TransactionAmount';

beforeEach(() => i18n.changeLanguage('zh'));

describe('original activity amount and preference detail amount', () => {
  const transaction = { transaction_type:'expense', amount:'705', currency:'CNY',
    original_amount:'100', original_currency:'USD', display_amount:'705', display_currency:'CNY' };
  const render = (props = {}) => renderToStaticMarkup(<TransactionAmount transaction={transaction} {...props} />);
  it('shows the original price and unambiguous currency in activity rows', () => {
    const html = render();
    expect(html).toContain('-$100.00'); expect(html).toContain('USD');
    expect(html).not.toContain('705'); expect(html).not.toContain('CNY');
  });
  it('shows the converted preference amount in detail', () => {
    const html = render({detailed:true});
    expect(html).toContain('-¥705.00'); expect(html).toContain('CNY');
    expect(html).not.toContain('USD');
  });
  it('does not mistake the original amount for an unavailable conversion', () => {
    const html = render({detailed:true, transaction:{...transaction, display_amount:null}});
    expect(html).toContain('待换算 CNY'); expect(html).not.toContain('100'); expect(html).not.toContain('705');
  });
  it('keeps original money in primary-card activity after fixed settlement mapping', () => {
    expect(render({transaction:{...transaction, amount:'90', currency:'EUR', child_book_amount:'705', child_book_currency:'CNY'}})).toContain('-$100.00');
  });
  it('uses known child booking money when legacy original money is missing', () => {
    const html = render({transaction:{...transaction, original_amount:null, original_currency:null,
      amount:'90', currency:'EUR', child_book_amount:'705', child_book_currency:'CNY'}});
    expect(html).toContain('-¥705.00'); expect(html).toContain('CNY'); expect(html).not.toContain('EUR');
  });
  it('hides amounts in privacy mode for both views', () => {
    expect(render({privacy:true})).toBe('••••••');
    expect(render({privacy:true, detailed:true})).toBe('••••••');
  });
});
