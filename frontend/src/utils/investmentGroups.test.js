import { describe, it, expect } from 'vitest';
import { investmentGroupKey, sidebarInvestmentGroups } from './investmentGroups';

const a={id:'a',account_type:'investment'}, b={id:'b',account_type:'证券'}, bank={id:'bank',account_type:'checking',name:'投资'};
describe('sidebar investment groups',()=>{
  it('uses exact visible members and normalized types, not account or group names',()=>{
    expect(investmentGroupKey([b,a,a])).toBe('a,b');
    expect(investmentGroupKey([a,bank])).toBe('');
    expect(investmentGroupKey([])).toBe('');
    expect(sidebarInvestmentGroups([{accounts:[a,b]},{accounts:[bank]}],'by_type')).toEqual(['a,b']);
    expect(sidebarInvestmentGroups([{subgroups:[{accounts:[a]},{accounts:[b]},{accounts:[bank]}]}],'owner_by_type')).toEqual(['a','b']);
    expect(sidebarInvestmentGroups([{accounts:[a,b]}],'by_institution')).toEqual([]);
  });
  it('changes the requested portfolio when filtering or hiding removes a member',()=>{
    expect(sidebarInvestmentGroups([{accounts:[a,b]}],'by_type')).not.toEqual(sidebarInvestmentGroups([{accounts:[a]}],'by_type'));
  });
});
