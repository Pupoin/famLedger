import i18n from '../i18n';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it } from 'vitest';
import BookingMoneyInfo from './BookingMoneyInfo';

beforeEach(() => i18n.changeLanguage('zh'));

describe('fixed booking and native refund explanations', () => {
  const transaction = { amount:'720',currency:'CNY',original_amount:'100',original_currency:'USD',
    exchange_rate:'7.2',exchange_rate_date:'2026-09-29',exchange_rate_source:'bank',refund_info:{
      allocated_amount:'100',original_total:'100',currency:'USD',allocations:[{allocated_amount:'100',original_currency:'USD',
        original_book_amount:'700',original_book_currency:'CNY',refund_book_amount:'720',refund_book_currency:'CNY',fx_difference_amount:'20',fx_difference_currency:'CNY'}]}};
  it('distinguishes the original quota, cash settlement and FX difference', () => {
    const html=renderToStaticMarkup(<BookingMoneyInfo transaction={transaction} detailed />);
    expect(html).toContain('100'); expect(html).toContain('USD');expect(html).toContain('700');
    expect(html).toContain('720');expect(html).toContain('汇兑损益');expect(html).toContain('20');
  });
  it('does not expose amounts in privacy mode', () => {
    expect(renderToStaticMarkup(<BookingMoneyInfo transaction={transaction} detailed privacy />)).toBe('');
  });
  it('does not duplicate same-currency amounts', () => {
    expect(renderToStaticMarkup(<BookingMoneyInfo transaction={{amount:'100',currency:'CNY',original_amount:'100',original_currency:'CNY'}} />)).not.toContain('原币');
  });
  it('does not repeat the original amount below original-price activity rows', () => {
    expect(renderToStaticMarkup(<BookingMoneyInfo transaction={transaction} />)).not.toContain('100');
  });
  it('explains both booking and preference conversion in detail', () => {
    const html = renderToStaticMarkup(<BookingMoneyInfo transaction={{...transaction, display_currency:'EUR',
      display_exchange_rate:'0.14', display_exchange_rate_base_currency:'CNY', display_exchange_rate_date:'2026-09-29', display_exchange_rate_source:'frankfurter'}} detailed />);
    expect(html).toContain('固定入账'); expect(html).toContain('720'); expect(html).toContain('展示换算');
    expect(html).toContain('EUR'); expect(html).toContain('交易日历史汇率');
  });
  it('marks legacy money as requiring review', () => {
    const html = renderToStaticMarkup(<BookingMoneyInfo transaction={{needs_money_review:true, amount:'100', currency:'CNY',
      original_amount:'100', original_currency:null, display_currency:'CNY'}} detailed />);
    expect(html).toContain('待核对');
    expect(html).not.toContain('原币 100');
  });
});
