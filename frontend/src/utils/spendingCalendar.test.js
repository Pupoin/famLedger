import { describe, it, expect } from 'vitest';
import { calendarWeeksForWidth, expandedCalendarStart } from './spendingCalendar';

describe('spending calendar responsive history range', () => {
  it('fits complete week columns after reserving the weekday labels', () => {
    expect(calendarWeeksForWidth(332)).toBe(8);
    expect(calendarWeeksForWidth(1000)).toBe(26);
    expect(calendarWeeksForWidth(44 + 10 * 36)).toBe(10);
    expect(calendarWeeksForWidth(44 + 10 * 36 - 1)).toBe(9);
    expect(calendarWeeksForWidth(0)).toBe(1);
  });

  it('adds earlier real dates, keeping the selected end fixed across years', () => {
    expect(expandedCalendarStart('2026-01-01', '2026-01-04', 3)).toBe('2025-12-15');
    expect(expandedCalendarStart('2026-01-01', '2026-01-05', 3)).toBe('2025-12-22');
  });

  it('keeps long ranges intact and adjusts the range when the viewport shrinks', () => {
    expect(expandedCalendarStart('2025-01-01', '2026-01-04', 3)).toBe('2025-01-01');
    expect(expandedCalendarStart('2026-01-01', '2026-01-04', 1)).toBe('2025-12-29');
    expect(expandedCalendarStart('', '', 3)).toBe('');
  });
});
