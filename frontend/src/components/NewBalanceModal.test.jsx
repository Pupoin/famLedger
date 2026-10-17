import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import i18n from '../i18n';
import NewBalanceModal from './NewBalanceModal';

vi.mock('../ToastContext', () => ({ useToast: () => ({showToast:vi.fn()}) }));
beforeEach(() => i18n.changeLanguage('zh'));

describe('investment valuation entry', () => {
  const render=type=>renderToStaticMarkup(<NewBalanceModal isOpen account={{id:'portfolio',currency:'CNY',balance:0,account_type:type}} />);
  it('allows recording a zero change and defaults investment accounts to valuation', () => {
    const html=render('investment');
    expect(html).toContain('投资盈亏'); expect(html).toContain('含账户现金');
    expect(html).toMatch(/checked=""[^>]*value="investment"/);
    expect(html).not.toContain('不会在活动流水列表中生成新的收支或对账交易');
  });
  it('does not offer investment gain for a checking account', () => {
    expect(render('checking')).not.toContain('balance-reason-investment');
  });
});
