import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, it, expect, vi } from 'vitest';
import i18n from '../i18n';
import InvestmentReturnsChart from './InvestmentReturnsChart';

vi.mock('../ThemeContext',()=>({useTheme:()=>({theme:'dark'})}));
const data={period:{rates:{mwr:21,xirr:10},reasons:{},start:'2024-01-01',end:'2025-12-31'},
  period_series:[{date:'2024-12-31',mwr:10,xirr:10},{date:'2025-12-31',mwr:21,xirr:10}]};
describe('investment return controls',()=>{
  it('follows the parent date range without a second independent range selector',()=>{
    i18n.changeLanguage('zh');
    const html=renderToStaticMarkup(<InvestmentReturnsChart data={{...data,inception:{rates:{mwr:99},reasons:{}}}} embedded scope="period"/>);
    expect(html).toContain('21.00%');expect(html).not.toContain('99.00%');
    expect(html).not.toContain('investment-return-scope');
    expect(html).toContain('investment-return-method');
  });
  it('offers method and range switches, and renders percentages instead of money',()=>{
    i18n.changeLanguage('zh');const html=renderToStaticMarkup(<InvestmentReturnsChart data={data}/>);
    expect(html).toContain('21.00%');expect(html).toContain('value="xirr"');expect(html).toContain('value="twr"');
    expect(html).toContain('Dietz 估算');expect(html).toContain('起算以来');expect(html).not.toContain('¥');
  });
  it('explains initialization and does not fabricate a zero curve',()=>{
    i18n.changeLanguage('en');const html=renderToStaticMarkup(<InvestmentReturnsChart data={{period:{rates:{mwr:null},reasons:{mwr:'not_initialized'}},period_series:[]}}/>);
    expect(html).toContain('Investment settings');expect(html).not.toContain('0.00%');expect(html).not.toMatch(/[\p{Script=Han}]/u);
  });
  it('shows missing-boundary estimates and their actual reference dates in both languages',()=>{
    const estimated={...data,period:{...data.period,estimated:true,opening_estimated:true,opening_reference_dates:['2026-09-26']}};
    for(const locale of ['zh','en']) {
      i18n.changeLanguage(locale);
      const html=renderToStaticMarkup(<InvestmentReturnsChart data={estimated} embedded scope="period"/>);
      expect(html).toContain('investment-return-estimated');
      expect(html).toContain('investment-return-estimate-note');
      expect(html).toContain('2026-09-26');expect(html).toContain('21.00%');
      expect(html).not.toContain('investment-return-scope');
      if(locale==='en') expect(html).not.toMatch(/[\p{Script=Han}]/u);
    }
    i18n.changeLanguage('zh');
    expect(renderToStaticMarkup(<InvestmentReturnsChart data={data}/>)).not.toContain('investment-return-estimated');
  });
});
