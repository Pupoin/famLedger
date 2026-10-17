import { describe, expect, it } from 'vitest';
import { normalizeInvestmentFilters } from './investmentFilters';

describe('investment Sankey filter correction', () => {
  it.each([
    ['投资盈利','income','gain'],['投资盈利','','gain'],['投资亏损','expense,refund','loss'],
    ['Investment gains','income','gain'],['Investment losses','expense','loss'],
  ])('corrects %s without discarding the chosen scope', (name,type,expected) => {
    const input=new URLSearchParams({category_name:name,transaction_type:type,spending_net:'true',spending_currency:'USD',
      start_date:'2026-10-01',end_date:'2026-10-31',user:'alice',account_id:'selected-account'});
    const output=normalizeInvestmentFilters(input);
    expect(output.get('investment_activity')).toBe(expected);
    for (const key of ['category_name','transaction_type','spending_net','spending_currency']) expect(output.has(key)).toBe(false);
    for (const key of ['start_date','end_date','user','account_id']) expect(output.get(key)).toBe(input.get(key));
    expect(input.get('category_name')).toBe(name);
  });
  it.each([
    {category_name:'餐饮美食',transaction_type:'expense'},
    {category_name:'投资盈利,餐饮美食',transaction_type:'income'},
    {category_name:'投资盈利',transaction_type:'transfer'},
    {category_name:'投资盈利',transaction_type:'income',category_id:'explicit-category'},
    {category_name:'投资盈利',investment_activity:'loss'},
    {category_name:'投资盈利',funds_flow:'all'},
  ])('retains explicit or ordinary filters: %j', values => {
    const input=new URLSearchParams(values);
    expect(normalizeInvestmentFilters(input).toString()).toBe(input.toString());
  });
});
