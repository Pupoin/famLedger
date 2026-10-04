import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import SureCashflowSankey from './SureCashflowSankey';
import SureOutflowsDonut from './SureOutflowsDonut';
import SureMoneyInOut from './SureMoneyInOut';
import SureSpendingCalendar from './SureSpendingCalendar';
import SureMerchantSpending from './SureMerchantSpending';

const preference = vi.hoisted(() => ({ symbol: '$', privacyMode: false }));
afterEach(() => { preference.privacyMode = false; });
vi.mock('../../CurrencyContext', () => ({ useCurrency: () => preference }));

const widgets = [
  ['现金流', SureCashflowSankey, {income_sources:[{name:'工资', amount:20}], pool:{name:'Cash Flow', amount:12.34}, expense_destinations:[{name:'消费', amount:12.34}]}],
  ['支出分布', SureOutflowsDonut, {total:12.34, categories:[{name:'消费', amount:12.34, percentage:100}]}],
  ['收支图', SureMoneyInOut, {income:20, expenses:12.34, balance:7.66, last_6_months:[{month:'7月', year_month:'2026-07', income:20, expense:12.34}]}],
  ['消费日历提示', SureSpendingCalendar, {end_date:'2026年07月06日', weeks:[[{date:'2026-07-06', amount:12.34, level:1}]]}],
  ['商户图与排行', SureMerchantSpending, {treemap:[{name:'商户', amount:12.34, placement:'1/1/7/7'}], ranking:[{name:'商户', amount:12.34, average:12.34, count:1}]}],
];

describe('overview chart money uses display currency', () => {
  it.each(widgets)('%s follows current user preference and its changes', (_, Widget, data) => {
    const render = (props={}) => renderToStaticMarkup(<MemoryRouter><Widget data={data} {...props} /></MemoryRouter>);
    preference.symbol = '$';
    expect(render()).toContain('$12.34');
    expect(render()).not.toContain('¥');
    preference.symbol = '€';
    expect(render()).toContain('€12.34');
    expect(render({currencySymbol:'A$'})).toContain('A$12.34');
  });
});

describe('overview charts preserve the complete selected period', () => {
  it.each([
    ['month', '2026-09-01', '2026-09-30'],
    ['quarter', '2026-07-01', '2026-09-30'],
    ['year to date', '2026-01-01', '2026-09-30'],
    ['six months', '2026-04-01', '2026-09-30'],
  ])('renders every selected date for %s without truncating earlier weeks', (_, start, end) => {
    const from = new Date(`${start}T00:00:00Z`);
    const until = new Date(`${end}T00:00:00Z`);
    const cursor = new Date(from);
    cursor.setUTCDate(cursor.getUTCDate() - (cursor.getUTCDay() + 6) % 7);
    const weeks = [];
    while (cursor <= until) {
      const week = [];
      for (let i = 0; i < 7; i += 1) {
        week.push({ date: cursor.toISOString().slice(0, 10), amount: 12.34, level: 1, outside: cursor < from || cursor > until });
        cursor.setUTCDate(cursor.getUTCDate() + 1);
      }
      weeks.push(week);
    }
    const html = renderToStaticMarkup(<MemoryRouter><SureSpendingCalendar data={{ start_date: start, end_date: end, weeks }} /></MemoryRouter>);
    expect(html.match(/data-testid="spending-calendar-cell"/g)).toHaveLength(weeks.length * 7);
    expect(html).toContain(`data-date="${start}"`);
    expect(html).toContain(`data-date="${end}"`);
    expect(html).toContain(`${start} – ${end}`);
    expect(html.match(/disabled=""/g)).toHaveLength(weeks.flat().filter(day => day.outside).length);
  });

  it('renders independent recent-month bars with full-month drill-down boundaries', () => {
    const bars = [
      { ym: '2025-12', month: '12月', income: 50, expense: 12.34, start_date: '2025-12-01', end_date: '2025-12-31' },
      { ym: '2026-01', month: '1月', income: 70, expense: 22, start_date: '2026-01-01', end_date: '2026-01-31' },
    ];
    const html = renderToStaticMarkup(<MemoryRouter><SureMoneyInOut data={{ last_6_months: bars, last_12_months: bars, income: 120, expenses: 34.34, period_dates: { start: '2026-01-03', end: '2026-01-03' } }} /></MemoryRouter>);
    expect(html.match(/data-testid="money-in-out-month"/g)).toHaveLength(2);
    expect(html).toContain('data-start-date="2025-12-01"');
    expect(html).toContain('data-end-date="2026-01-31"');
  });
});


describe('privacy hides chart amounts and retains percentages', () => {
  it.each(widgets)('%s masks labels, SVG titles and accessible tooltips', (_, Widget, data) => {
    preference.symbol = '$';
    preference.privacyMode = true;
    const html = renderToStaticMarkup(<MemoryRouter><Widget data={data}/></MemoryRouter>);
    const text = html.replace(/<[^>]+>/g, '');
    expect(html).toContain('••••••');
    expect(text).not.toContain('12.34');
    expect(html).not.toContain('$12.34');
    expect(html).not.toContain('$20.00');
    // Native title and aria-label attributes must not reveal the masked amounts.
    const labels = [...html.matchAll(/(?:title|aria-label)="([^"]*)"/g)].map(m => m[1]).join(' ');
    expect(labels).not.toContain('12.34');
  });

  it('leaves expense percentages visible and restores amounts when privacy is off', () => {
    const data = {total:12.34, categories:[{name:'消费', amount:12.34, percentage:100}]};
    preference.privacyMode = true;
    const masked = renderToStaticMarkup(<MemoryRouter><SureOutflowsDonut data={data}/></MemoryRouter>);
    expect(masked).toContain('100%');
    preference.privacyMode = false;
    const visible = renderToStaticMarkup(<MemoryRouter><SureOutflowsDonut data={data}/></MemoryRouter>);
    expect(visible).toContain('$12.34');
    expect(visible).not.toContain('••••••');
  });
});
