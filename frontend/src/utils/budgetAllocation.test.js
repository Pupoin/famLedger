import { describe, expect, it } from 'vitest';
import { allocateBudgetAmounts } from './budgetAllocation';

describe('percentage budgets', () => {
  it('recalculates category amounts when the total changes', () => {
    const percentages = { Food: 25, Shopping: 12.5 };
    expect(allocateBudgetAmounts(1000, percentages)).toEqual({ Food: 250, Shopping: 125 });
    expect(allocateBudgetAmounts(2000, percentages)).toEqual({ Food: 500, Shopping: 250 });
    expect(percentages).toEqual({ Food: 25, Shopping: 12.5 });
  });
  it('distributes cents without increasing the budget during rounding', () => {
    expect(allocateBudgetAmounts(.01, { Food: 50, Shopping: 50 })).toEqual({ Food: .01, Shopping: 0 });
    expect(allocateBudgetAmounts(100, { A: 33.33, B: 33.33, C: 33.34 })).toEqual({ A: 33.33, B: 33.33, C: 33.34 });
  });
  it('preserves unallocated budget and an empty category list', () => {
    expect(allocateBudgetAmounts(100, { A: 0, B: 20 })).toEqual({ A: 0, B: 20 });
    expect(allocateBudgetAmounts(100, {})).toEqual({});
    expect(allocateBudgetAmounts(0, { A: 50 })).toEqual({ A: 0 });
  });
});
