import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, it, expect } from 'vitest';
import i18n from '../i18n';
import AccountInvestmentReturn from './AccountInvestmentReturn';

beforeEach(() => i18n.changeLanguage('zh'));
const account = { account_type:'investment', investment_ytd:{ rate:5.852555, as_of:'2026-10-17', currency:'CNY' } };
const render = value => renderToStaticMarkup(<AccountInvestmentReturn account={value}/>);

describe('sidebar investment YTD returns', () => {
  it('labels an actual investment group without reintroducing non-investment placeholders', () => {
    const html=renderToStaticMarkup(<AccountInvestmentReturn account={account} group/>);
    expect(html).toContain('data-testid="investment-group-ytd-return"');
    expect(html).toContain('今年 +5.85%');
    expect(html).not.toContain('data-testid="account-ytd-return"');
  });
  it('shows dated positive returns in green, losses in red and zero in neutral text', () => {
    const gain = render(account);
    expect(gain).toContain('今年 +5.85%'); expect(gain).toContain('text-emerald-600');
    expect(gain).toContain('截至 2026-10-17');
    const loss = render({...account,investment_ytd:{rate:-7.123}});
    expect(loss).toContain('今年 -7.12%'); expect(loss).toContain('text-red-600');
    const zero = render({...account,investment_ytd:{rate:0}});
    expect(zero).toContain('今年 0.00%'); expect(zero).toContain('text-zinc-500');
  });
  it('uses account type alone and never adds badges to other types', () => {
    expect(render({...account,account_type:'checking',name:'证券投资账户'})).toBe('');
    expect(render({...account,account_type:'credit_card'})).toBe('');
    expect(render({...account,account_type:'证券'})).toContain('+5.85%');
  });
  it('does not label missing data as a zero return, and explains loading or missing valuations', () => {
    expect(render({account_type:'investment'})).toContain('今年 —');
    const html=render({...account,investment_ytd:{rate:null,reason:'missing_closing_valuation'}});
    expect(html).toContain('今年 —'); expect(html).not.toContain('0.00%'); expect(html).toContain('缺少可用的市值或本金记录');
  });
  it('marks carried values as estimates, including zero, and provides reference dates',()=>{
    const html=render({...account,investment_ytd:{rate:0,estimated:true,closing_estimated:true,closing_reference_dates:['2026-09-26']}});
    expect(html).toContain('今年 ≈ 0.00%');expect(html).toContain('期末参考记录：2026-09-26');
    expect(html).toContain('未记录的市场涨跌未计入');expect(html).toContain('text-zinc-500');
  });
  it('supports English and keeps percentages independent of monetary privacy masking', () => {
    i18n.changeLanguage('en');
    const html=render(account);
    expect(html).toContain('YTD +5.85%');expect(html).toContain('As of 2026-10-17');
    expect(html).not.toMatch(/[\p{Script=Han}]/u);
    expect(html).not.toContain('••••');
  });
});
