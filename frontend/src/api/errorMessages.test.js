import { describe, expect, it } from 'vitest';
import { apiErrorMessage } from './errorMessages';

describe('financial input validation messages', () => {
  it('shows ordinary backend explanations', () => expect(apiErrorMessage('原币金额必须大于零')).toBe('原币金额必须大于零'));
  it('renders validation arrays as text without original inputs', () => {
    const result=apiErrorMessage([{loc:['body','settlement_amount'],msg:'Input should be greater than 0',input:'private payload'}]);
    expect(result).toBe('settlement_amount: Input should be greater than 0');
    expect(result).not.toContain('private payload');
  });
  it('handles unknown response shapes', () => expect(apiErrorMessage({unexpected:true},'金额输入有误')).toBe('金额输入有误'));
});
