import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';

export default function SureSpendingCalendar({
  data,
  currencySymbol = '¥',
}) {
  const navigate = useNavigate();
  const [activeCell, setActiveCell] = useState(null);

  const startDateStr = data?.start_date || '2025年12月01日';
  const endDateStr = data?.end_date || '2026年09月27日';
  const weeks = data?.weeks || [];

  const dayNames = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];

  // Color mappings
  const getCellColor = (day) => {
    if (day.outside) {
      return 'bg-zinc-100/40 dark:bg-zinc-800/20 border-zinc-200/40 dark:border-zinc-800/40';
    }
    if (day.level === 0 || day.amount === 0) {
      return 'bg-zinc-50 dark:bg-zinc-800/50 border-zinc-200/80 dark:border-zinc-700/60';
    }
    if (day.is_refund || day.amount < 0) {
      return 'bg-emerald-400 dark:bg-emerald-500 border-emerald-500 text-white';
    }
    // Red levels
    switch (day.level) {
      case 1:
        return 'bg-red-200/90 dark:bg-red-900/60 border-red-300 dark:border-red-800';
      case 2:
        return 'bg-red-300 dark:bg-red-700/70 border-red-400 dark:border-red-600';
      case 3:
        return 'bg-red-400 dark:bg-red-600 border-red-500';
      case 4:
      default:
        return 'bg-red-500 dark:bg-red-500 border-red-600';
    }
  };

  const getMonthLabel = (weekIndex) => {
    if (!weeks[weekIndex] || !weeks[weekIndex][0]) return '';
    const dateStr = weeks[weekIndex][0].date;
    const month = parseInt(dateStr.slice(5, 7), 10);
    // Only show if first week or first week of month
    if (weekIndex === 0) return `${month}月`;
    const prevDateStr = weeks[weekIndex - 1][0].date;
    const prevMonth = parseInt(prevDateStr.slice(5, 7), 10);
    if (month !== prevMonth) return `${month}月`;
    return '';
  };

  return (
    <div className="space-y-3">
      {/* ── Header details ── */}
      <div className="flex flex-col gap-0.5">
        <p className="text-xs text-zinc-500">
          所选范围较短时自动向前补充历史消费并铺满可用宽度
        </p>
        <p className="text-xs font-mono text-zinc-400">
          {startDateStr} – {endDateStr}
        </p>
      </div>

      {/* ── Heatmap Grid Container ── */}
      <div className="overflow-x-auto pb-2">
        <div className="inline-flex gap-2">
          {/* Weekday Labels (Left column) */}
          <div className="grid grid-rows-7 gap-1 pt-6 w-9 shrink-0 text-xs text-zinc-400 font-medium">
            {dayNames.map((name, i) => (
              <span key={i} className="flex h-7 items-center justify-start">
                {name}
              </span>
            ))}
          </div>

          {/* Weeks Columns */}
          <div className="flex gap-1">
            {weeks.map((week, wIdx) => {
              const monthLabel = getMonthLabel(wIdx);
              return (
                <div key={wIdx} className="space-y-1 w-7 shrink-0">
                  {/* Month header */}
                  <p className="h-5 text-xs text-zinc-400 font-medium truncate overflow-visible whitespace-nowrap">
                    {monthLabel}
                  </p>

                  {/* 7 Days in Week */}
                  <div className="grid grid-rows-7 gap-1">
                    {week.map((day, dIdx) => {
                      const colorClasses = getCellColor(day);
                      const isHovered = activeCell?.date === day.date;
                      return (
                        <button
                          key={dIdx}
                          type="button"
                          disabled={day.outside}
                          onMouseEnter={() => !day.outside && setActiveCell(day)}
                          onMouseLeave={() => setActiveCell(null)}
                          onClick={() => {
                            if (!day.outside) {
                              navigate(`/transactions?start_date=${day.date}&end_date=${day.date}`);
                            }
                          }}
                          className={`w-7 h-7 rounded-md border transition-all duration-150 relative ${colorClasses} ${
                            isHovered ? 'scale-110 z-10 shadow-sm ring-2 ring-zinc-900 dark:ring-white' : ''
                          }`}
                          title={`${day.date} · ${currencySymbol}${Math.abs(day.amount).toFixed(2)}`}
                        />
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* ── Bottom status bar ── */}
      <div className="rounded-xl bg-zinc-50 dark:bg-zinc-800/50 border border-zinc-100 dark:border-zinc-800 px-3.5 py-2.5 text-xs text-zinc-500 flex items-center justify-between min-h-[38px]">
        {activeCell ? (
          <div className="flex items-center gap-2">
            <span className="font-medium text-zinc-900 dark:text-zinc-100">{activeCell.date}</span>
            <span>·</span>
            <span className={`font-mono font-bold ${activeCell.amount < 0 ? 'text-emerald-600' : 'text-zinc-900 dark:text-zinc-100'}`}>
              {activeCell.amount < 0 ? '退款 ' : '支出 '}{currencySymbol}{Math.abs(activeCell.amount).toFixed(2)}
            </span>
          </div>
        ) : (
          <span>电脑端悬浮查看金额、点击进入明细；触屏端短按查看金额、长按进入明细。</span>
        )}
      </div>
    </div>
  );
}
