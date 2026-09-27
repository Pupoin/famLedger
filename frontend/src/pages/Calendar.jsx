import React, { useState, useEffect, useMemo, useRef } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  ChevronLeft,
  ChevronRight,
  Calendar as CalendarIcon,
  TrendingDown,
  Flame,
  CreditCard,
  ArrowUpRight,
  Info,
} from 'lucide-react';
import { getExpenses } from '../api/expenses';
import { useCurrency } from '../CurrencyContext';
import { useDateFormat } from '../DateFormatContext';
import { useToast } from '../ToastContext';

const DAYS_OF_WEEK = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

const pad = (n) => String(n).padStart(2, '0');

export default function Calendar() {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { fmt, currency } = useCurrency();
  const { formatDate } = useDateFormat();
  const today = new Date();

  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth());
  const [expenses, setExpenses] = useState([]);
  const [loading, setLoading] = useState(true);
  const [hoveredDay, setHoveredDay] = useState(null);

  useEffect(() => {
    let cancelled = false;
    async function fetchMonthExpenses() {
      setLoading(true);
      try {
        const startDate = `${year}-${pad(month + 1)}-01`;
        const lastDay = new Date(year, month + 1, 0).getDate();
        const endDate = `${year}-${pad(month + 1)}-${pad(lastDay)}`;

        const data = await getExpenses({ start_date: startDate, end_date: endDate, limit: 1000 });
        if (!cancelled) {
          setExpenses(data || []);
        }
      } catch (err) {
        console.error('Failed to load expenses', err);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchMonthExpenses();
    return () => {
      cancelled = true;
    };
  }, [year, month]);

  // Aggregate daily expenses and find max daily spend for heatmap scaling
  const { dailyData, monthTotal, maxDailySpend, activeDaysCount, peakDay } = useMemo(() => {
    const map = {};
    let total = 0;
    let max = 0;
    let peak = null;

    (expenses || []).forEach((e) => {
      if (e.category === 'Payment') return;
      const d = e.date;
      const amt = Math.abs(Number(e.amount) || 0);

      if (!map[d]) {
        map[d] = { total: 0, count: 0, items: [] };
      }
      map[d].total += amt;
      map[d].count += 1;
      map[d].items.push(e);

      total += amt;
    });

    Object.entries(map).forEach(([d, val]) => {
      if (val.total > max) {
        max = val.total;
        peak = { date: d, total: val.total };
      }
    });

    return {
      dailyData: map,
      monthTotal: total,
      maxDailySpend: max || 1,
      activeDaysCount: Object.keys(map).length,
      peakDay: peak,
    };
  }, [expenses]);

  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const dailyAverage = daysInMonth > 0 ? monthTotal / daysInMonth : 0;

  // Calendar matrix calculation
  const firstDayOfWeek = new Date(year, month, 1).getDay();
  const totalCells = Math.ceil((firstDayOfWeek + daysInMonth) / 7) * 7;
  const cells = [];
  for (let i = 0; i < totalCells; i++) {
    const day = i - firstDayOfWeek + 1;
    cells.push(day >= 1 && day <= daysInMonth ? day : null);
  }

  // Navigation handlers
  const goToPrev = () => {
    if (month === 0) {
      setYear(year - 1);
      setMonth(11);
    } else {
      setMonth(month - 1);
    }
  };

  const goToNext = () => {
    if (month === 11) {
      setYear(year + 1);
      setMonth(0);
    } else {
      setMonth(month + 1);
    }
  };

  const goToToday = () => {
    setYear(today.getFullYear());
    setMonth(today.getMonth());
  };

  const isToday = (day) =>
    day === today.getDate() && month === today.getMonth() && year === today.getFullYear();

  // Heatmap intensity level (0 to 4)
  const getIntensityClass = (total) => {
    if (!total || total <= 0) return 'bg-zinc-50/70 dark:bg-zinc-800/40 text-zinc-400 border-zinc-200/50 dark:border-zinc-800/50';
    const ratio = total / maxDailySpend;
    if (ratio < 0.2) {
      return 'bg-emerald-50 dark:bg-emerald-950/30 text-emerald-900 dark:text-emerald-300 border-emerald-200/60 dark:border-emerald-800/40';
    }
    if (ratio < 0.45) {
      return 'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-950 dark:text-emerald-200 border-emerald-300/70 dark:border-emerald-700/50 font-medium';
    }
    if (ratio < 0.75) {
      return 'bg-emerald-200 dark:bg-emerald-800/60 text-emerald-950 dark:text-white border-emerald-400 dark:border-emerald-600 font-semibold';
    }
    return 'bg-emerald-300 dark:bg-emerald-600 text-emerald-950 dark:text-white border-emerald-500 font-bold shadow-xs';
  };

  return (
    <div className="max-w-6xl mx-auto pb-12 space-y-6">
      {/* ── 1. Top Header & Month Picker (Sure Style) ── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-xs text-zinc-500 mb-1">
            <Link to="/" className="hover:text-zinc-900 dark:hover:text-white transition-colors">
              Home
            </Link>
            <span>/</span>
            <span className="font-semibold text-zinc-900 dark:text-zinc-100">
              {t('calendar.title', 'Calendar Heatmap')}
            </span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-zinc-900 dark:text-zinc-100">
            {t('calendar.title', 'Spending Calendar Heatmap')}
          </h1>
          <p className="text-xs text-zinc-500 mt-0.5">
            {t('calendar.subtitle', 'Daily spending intensity and cashflow heatmap grid')}
          </p>
        </div>

        {/* Sure Month Selector & Today button */}
        <div className="flex items-center gap-2">
          <div className="flex items-center bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 rounded-xl p-1 shadow-2xs">
            <button
              onClick={goToPrev}
              className="p-1.5 rounded-lg text-zinc-500 hover:text-zinc-900 dark:hover:text-white hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
              title="上一月"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>

            <span className="px-3 text-xs font-bold font-mono text-zinc-900 dark:text-zinc-100 min-w-32 text-center">
              {MONTH_NAMES[month]} {year}
            </span>

            <button
              onClick={goToNext}
              className="p-1.5 rounded-lg text-zinc-500 hover:text-zinc-900 dark:hover:text-white hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
              title="下一月"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>

          <button
            onClick={goToToday}
            className="px-3 py-2 text-xs font-semibold rounded-xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-800 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-800 shadow-2xs transition-colors"
          >
            {t('calendar.today', 'Today')}
          </button>
        </div>
      </div>

      {/* ── 2. Summary Metric Cards (Sure 4-Card Grid) ── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Metric 1: Month Total */}
        <div className="rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-xs">
          <span className="text-[11px] font-semibold text-zinc-400 uppercase tracking-wider block">
            {t('calendar.monthTotal', '当月总支出')}
          </span>
          <span className="text-xl sm:text-2xl font-bold font-mono text-zinc-900 dark:text-zinc-100 mt-1 block">
            {fmt(monthTotal)}
          </span>
        </div>

        {/* Metric 2: Daily Average */}
        <div className="rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-xs">
          <span className="text-[11px] font-semibold text-zinc-400 uppercase tracking-wider block">
            {t('calendar.dailyAvg', '日均消费')}
          </span>
          <span className="text-xl sm:text-2xl font-bold font-mono text-zinc-900 dark:text-zinc-100 mt-1 block">
            {fmt(dailyAverage)}
          </span>
        </div>

        {/* Metric 3: Peak Day */}
        <div className="rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-xs">
          <span className="text-[11px] font-semibold text-zinc-400 uppercase tracking-wider block">
            {t('calendar.peakDay', '单日消费峰值')}
          </span>
          <span className="text-xl sm:text-2xl font-bold font-mono text-rose-600 dark:text-rose-400 mt-1 block">
            {peakDay ? fmt(peakDay.total) : '¥0.00'}
          </span>
          {peakDay && (
            <span className="text-[10px] text-zinc-400 mt-0.5 block truncate">
              {peakDay.date}
            </span>
          )}
        </div>

        {/* Metric 4: Active Days */}
        <div className="rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-xs">
          <span className="text-[11px] font-semibold text-zinc-400 uppercase tracking-wider block">
            {t('calendar.activeDays', '消费发生天数')}
          </span>
          <span className="text-xl sm:text-2xl font-bold font-mono text-emerald-600 dark:text-emerald-400 mt-1 block">
            {activeDaysCount} / {daysInMonth} 天
          </span>
        </div>
      </div>

      {/* ── 3. Calendar Heatmap Grid (Sure Clean Layout) ── */}
      <div className="rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-xs space-y-4">
        {/* Days of Week Header */}
        <div className="grid grid-cols-7 gap-2 text-center text-xs font-semibold text-zinc-400 uppercase tracking-wider">
          {DAYS_OF_WEEK.map((d) => (
            <div key={d} className="py-1">
              {d}
            </div>
          ))}
        </div>

        {/* Cells Grid */}
        <div className="grid grid-cols-7 gap-2">
          {cells.map((day, idx) => {
            if (!day) {
              return (
                <div
                  key={`empty-${idx}`}
                  className="h-20 sm:h-24 rounded-xl border border-dashed border-zinc-100 dark:border-zinc-800/40 bg-zinc-50/20 dark:bg-transparent"
                />
              );
            }

            const dateStr = `${year}-${pad(month + 1)}-${pad(day)}`;
            const info = dailyData[dateStr];
            const hasSpend = info && info.total > 0;
            const currentDay = isToday(day);

            return (
              <div
                key={dateStr}
                onClick={() => navigate(`/transactions?search=${dateStr}`)}
                onMouseEnter={() => info && setHoveredDay({ date: dateStr, ...info })}
                onMouseLeave={() => setHoveredDay(null)}
                className={`relative h-20 sm:h-24 p-2 rounded-xl border transition-all duration-150 flex flex-col justify-between cursor-pointer group hover:scale-[1.02] hover:shadow-md ${getIntensityClass(
                  info?.total
                )} ${currentDay ? 'ring-2 ring-zinc-900 dark:ring-white ring-offset-1' : ''}`}
              >
                {/* Top: Day Number & Badge */}
                <div className="flex items-center justify-between">
                  <span
                    className={`text-xs font-bold font-mono ${
                      currentDay
                        ? 'px-1.5 py-0.5 rounded bg-zinc-900 text-white dark:bg-white dark:text-zinc-900 text-[10px]'
                        : ''
                    }`}
                  >
                    {day}
                  </span>
                  {info?.count > 0 && (
                    <span className="text-[10px] font-mono px-1 rounded-full bg-black/10 dark:bg-white/10">
                      {info.count}笔
                    </span>
                  )}
                </div>

                {/* Center / Bottom: Amount */}
                <div className="text-right">
                  {hasSpend ? (
                    <span className="text-xs sm:text-sm font-bold font-mono tracking-tight block">
                      {fmt(info.total)}
                    </span>
                  ) : (
                    <span className="text-[11px] text-zinc-300 dark:text-zinc-600 block">-</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {/* ── 4. Bottom Legend (Heatmap Intensity) ── */}
        <div className="pt-4 border-t border-zinc-100 dark:border-zinc-800 flex items-center justify-between text-xs text-zinc-500">
          <div className="flex items-center gap-1.5 text-[11px]">
            <Info className="w-3.5 h-3.5 text-zinc-400" />
            <span>点击任意日期格子可直接下钻查看该日全部交易明细</span>
          </div>

          <div className="flex items-center gap-1.5 text-[11px]">
            <span>Less</span>
            <div className="w-3.5 h-3.5 rounded bg-zinc-100 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700" />
            <div className="w-3.5 h-3.5 rounded bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200" />
            <div className="w-3.5 h-3.5 rounded bg-emerald-100 dark:bg-emerald-900/40 border border-emerald-300" />
            <div className="w-3.5 h-3.5 rounded bg-emerald-200 dark:bg-emerald-800/60 border border-emerald-400" />
            <div className="w-3.5 h-3.5 rounded bg-emerald-300 dark:bg-emerald-600 border border-emerald-500" />
            <span>More</span>
          </div>
        </div>
      </div>
    </div>
  );
}
