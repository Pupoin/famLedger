import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it } from 'vitest';
import i18n from '../i18n';
import InvestmentSummary from './InvestmentSummary';
import InvestmentValuationEditor from './InvestmentValuationEditor';

beforeEach(() => i18n.changeLanguage('zh'));
const data = { has_accounts:true, valuation_complete:true, currency:'USD', currency_symbol:'$', portfolio_value:12567,
  period_return:-432.1, period_gain:-432.1, period_deposit:2345, period_withdrawal:3456, cash_income:678.9, total_return:7890,
  as_of:'2026-09-30' };

describe('investment summaries', () => {
  it('shows the overview breakdown without counting cash income twice and keeps rates visible in privacy mode', () => {
    const input={...data,composition:{valuation_gain:150,cash_income:20,cash_cost:10,total:160},cash_income:20,cash_cost:10,
      performance:{configured_accounts:1,account_count:1,capital:{},period:{gain:160,rates:{mwr:12.34}}}};
    const visible=renderToStaticMarkup(<InvestmentSummary data={input} overview showChart={false}/>);
    expect(visible).toContain('$150.00 USD');expect(visible).toContain('$20.00 USD');expect(visible).toContain('-$10.00 USD');
    expect(visible).toContain('$160.00 USD');expect(visible).toContain('12.34%');
    const hidden=renderToStaticMarkup(<InvestmentSummary data={input} overview privacy showChart={false}/>);
    expect(hidden).toContain('12.34%');expect(hidden).toContain('••••••');
    for (const amount of ['150.00','160.00','20.00','10.00','12,567']) expect(hidden).not.toContain(amount);
  });
  it('translates the full overview breakdown into English', () => {
    i18n.changeLanguage('en');
    const html=renderToStaticMarkup(<InvestmentSummary data={{...data,composition:{valuation_gain:100}}} overview showChart={false}/>);
    expect(html).toContain('Period return breakdown');expect(html).not.toMatch(/[\p{Script=Han}]/u);
  });
  it('uses real returns and the response currency, including a loss', () => {
    const html = renderToStaticMarkup(<InvestmentSummary data={data} />);
    expect(html).toContain('$12,567.00 USD'); expect(html).toContain('-$432.10 USD');
    expect(html).toContain('$2,345.00 USD'); expect(html).toContain('$3,456.00 USD');
    expect(html).not.toContain('(0.0%)'); expect(html).toContain('市值涨跌不计入消费预算');
  });
  it('shows missing valuations explicitly and includes actual income', () => {
    const html = renderToStaticMarkup(<InvestmentSummary data={{...data,period_return:null,valuation_complete:false}} />);
    expect(html).toContain('待补充'); expect(html).toContain('本期缺少完整市值记录'); expect(html).toContain('$678.90 USD');
  });
  it('masks all metrics in privacy mode, including the budget reference', () => {
    for (const compact of [true,false]) {
      const html = renderToStaticMarkup(<InvestmentSummary data={data} privacy compact={compact} />);
      for (const text of ['12,567','432.10','2,345','3,456','678.90','7,890']) expect(html).not.toContain(text);
      expect(html).toContain('••••••');
    }
  });
  it('labels estimated performance without relabeling actual cash receipts or exposing hidden amounts',()=>{
    const performance={configured_accounts:1,account_count:1,period:{gain:1234,estimated:true,closing_estimated:true},inception:{gain:2345,estimated:false}};
    const html=renderToStaticMarkup(<InvestmentSummary data={{...data,performance}} privacy showChart={false}/>);
    expect(html).toContain('本期投资回报<span');expect(html).toContain('(估算)');
    expect(html).not.toContain('1,234');expect(html).not.toContain('12,567');
    expect(html).not.toContain('分红及利息收入<span');
    expect(html).not.toContain('累计已记录回报<span');
  });
  it('labels a declared capital basis separately and masks it in privacy mode',()=>{
    const performance={configured_accounts:1,account_count:1,capital:{capital_basis:6543.21,contributions:0},period:{gain:100},inception:{gain:100}};
    for (const privacy of [false,true]) {
      const html=renderToStaticMarkup(<InvestmentSummary data={{...data,performance}} privacy={privacy} showChart={false}/>);
      expect(html).toContain('设定本金基准');
      if(privacy) expect(html).not.toContain('6,543.21');else expect(html).toContain('6,543.21');
    }
  });
  it('supports English and hides the budget reference without investment accounts', () => {
    i18n.changeLanguage('en');
    const html=renderToStaticMarkup(<InvestmentSummary data={data} compact />);
    expect(html).toContain('Investment reference'); expect(html).toContain('Market value change');
    expect(html).not.toMatch(/[\p{Script=Han}]/u);
    expect(renderToStaticMarkup(<InvestmentSummary data={{has_accounts:false}} compact />)).toBe('');
  });
  it('edits the total value and timestamp instead of the derived adjustment amount or type', () => {
    const html=renderToStaticMarkup(<InvestmentValuationEditor transaction={{ id:'value', amount:'432.1', currency:'USD',
      occurred_at:'2026-09-10T02:00:00Z', extra:{target_balance:'12567'} }} />);
    expect(html).toContain('value="12567"'); expect(html).toContain('type="time"');
    expect(html).not.toContain('432.1'); expect(html).not.toContain('记账类型');
  });
});
