import { describe, it, expect } from 'vitest';
import i18n from '../i18n';
import { RETURN_METHODS, formatReturn, returnReason } from './investmentReturns';

describe('investment return presentation',()=>{
  it('keeps unavailable returns distinct from a genuine zero or loss',()=>{
    i18n.changeLanguage('zh');
    expect(formatReturn(null)).toBe('待补充');expect(formatReturn(0)).toBe('0.00%');
    expect(formatReturn(-12.345)).toBe('-12.35%');expect(formatReturn(Infinity)).toBe('待补充');
  });
  it('provides all six metrics and explains missing valuation requirements',()=>{
    i18n.changeLanguage('en');
    expect(RETURN_METHODS.map(([key])=>key)).toEqual(['mwr','xirr','dietz','twr','twr_annual','simple_annual']);
    expect(returnReason('missing_flow_valuation')).toContain('cash-flow times');
    expect(returnReason('under_one_year')).toContain('shorter than one year');
    expect(returnReason('multiple_solutions')).toContain('multiple');
  });
});
