import { describe, expect, it } from 'vitest';
import { createPageViewStore } from './pageViewStore';

describe('chart page history', () => {
  it('returns to the original custom range and chart controls after a drilldown', () => {
    const store = createPageViewStore();
    const overview = '/:overview-1';
    store.get(overview, 'range', 'monthly');
    store.set(overview, 'range', { period: 'custom', start: '2026-08-01', end: '2026-09-15' });
    store.get(overview, 'moneyInOut.trendRange', '6m');
    store.set(overview, 'moneyInOut.trendRange', '12m');
    store.setScroll(overview, { y: 1320, section: 'calendar', top: 82 });
    store.get('/transactions:details-1', 'range', 'all');

    expect(store.get(overview, 'range', 'monthly')).toEqual({
      period: 'custom', start: '2026-08-01', end: '2026-09-15',
    });
    expect(store.get(overview, 'moneyInOut.trendRange', '6m')).toBe('12m');
    expect(store.getScroll(overview)).toEqual({ y: 1320, section: 'calendar', top: 82 });
  });

  it('keeps different visits to the same page and other report pages independent', () => {
    const store = createPageViewStore();
    store.get('/:first', 'period', 'monthly');
    store.set('/:first', 'period', 'quarterly');
    store.get('/analytics:report', 'period', 'monthly');
    store.set('/analytics:report', 'period', 'ytd');
    expect(store.get('/:second', 'period', 'monthly')).toBe('monthly');
    expect(store.get('/:first', 'period', 'monthly')).toBe('quarterly');
    expect(store.get('/analytics:report', 'period', 'monthly')).toBe('ytd');
  });

  it('retains collapsed sections through functional updates', () => {
    const store = createPageViewStore();
    store.get('overview', 'collapsed', { cashflow: false, calendar: false });
    store.set('overview', 'collapsed', (previous) => ({ ...previous, cashflow: true }));
    store.set('overview', 'collapsed', (previous) => ({ ...previous, calendar: true }));
    expect(store.get('overview', 'collapsed', {})).toEqual({ cashflow: true, calendar: true });
  });

  it('does not share view state across authenticated sessions', () => {
    const firstUser = createPageViewStore();
    firstUser.get('/:default', 'userFilter', '全部');
    firstUser.set('/:default', 'userFilter', 'private-member');
    const nextUser = createPageViewStore();
    expect(nextUser.get('/:default', 'userFilter', '全部')).toBe('全部');
    expect(nextUser.getScroll('/:default')).toBeNull();
  });

  it('bounds the history cache while preserving recent views', () => {
    const store = createPageViewStore(2);
    for (const key of ['old', 'recent', 'current']) {
      store.get(key, 'period', 'monthly');
      store.set(key, 'period', 'custom');
    }
    expect(store.get('recent', 'period', 'monthly')).toBe('custom');
    expect(store.get('current', 'period', 'monthly')).toBe('custom');
    expect(store.get('old', 'period', 'monthly')).toBe('monthly');
  });
});
