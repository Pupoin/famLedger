import { chartMoney } from '../../utils/chartMoney';
import { dateLabel, tx, useLocale, currentLocale } from "../../localization.js";
import React, { useState, useEffect, useRef, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useCurrency } from '../../CurrencyContext';
import { usePageViewState } from '../../PageViewContext';
import { fetchWithAuth } from '../../api/fetchWithAuth';
import { calendarWeeksForWidth, expandedCalendarStart } from '../../utils/spendingCalendar';

/**
 * Sure 风格消费日历热力图 (Spending Analytics Heatmap)
 * 严格对标 Sure 源码 (app/views/pages/dashboard/_spending_calendar.html.erb 及 spending_calendar_controller.js):
 * 1. 格子尺寸严格对标 Sure: 32px (w-8 h-8)，间距 4px (gap-1)
 * 2. 完整展示所选周期内的每一周，宽度不足时允许横向滚动
 * 3. 短周期向前补充真实历史消费，长周期保留全部日期；周尾的未来格子不可进入流水
 * 4. 桌面悬停/手机点按显示每日明细；桌面点击/手机长按进入当天流水
 */
function SureSpendingCalendar({
  data,
  currencySymbol: reportSymbol,
  reportCurrency = '',
  userFilter = '',
}) {
  const locale = useLocale();
  const { symbol, privacyMode } = useCurrency() || {};
  const currencySymbol = reportSymbol ?? symbol ?? '';
  const formatAmount = value => chartMoney(value, currencySymbol, privacyMode, currentLocale());
  const navigate = useNavigate();
  const scrollRef = useRef(null);
  const [minimumWeeks, setMinimumWeeks] = useState(0);
  const [expandedData, setExpandedData] = useState(null);
  const [calendarLoading, setCalendarLoading] = useState(false);
  const [calendarError, setCalendarError] = useState(null);
  const [retryCount, setRetryCount] = useState(0);
  const calendarData = expandedData && expandedData.source === data && expandedData.minimumWeeks === minimumWeeks
    ? expandedData.data : data;
  const calendarRange = `${calendarData?.start_date || ''}:${calendarData?.end_date || ''}`;
  const [scrollLeft, setScrollLeft] = usePageViewState(`calendar.scrollLeft.${calendarRange}`, null);
  const [hoveredDetail, setHoveredDetail] = useState(null);
  const [touchMode, setTouchMode] = useState(false);
  const gestureRef = useRef(null);
  const touchClickRef = useRef(false);

  useEffect(() => {
    const element = scrollRef.current;
    const measure = () => {
      if (element?.clientWidth > 0) setMinimumWeeks(calendarWeeksForWidth(element.clientWidth));
    };
    measure();
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure);
    if (element) observer?.observe(element);
    window.addEventListener('resize', measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', measure);
    };
  }, []);

  useEffect(() => {
    const start = data?.period_dates?.start || data?.start_date;
    const end = data?.period_dates?.end || data?.end_date;
    setCalendarError(null);
    if (!minimumWeeks || !start || !end || expandedCalendarStart(start, end, minimumWeeks) === start) {
      setCalendarLoading(false);
      return;
    }
    const controller = new AbortController();
    setCalendarLoading(true);
    // Resize events settle before fetching; abort replies from an older selection.
    const timer = setTimeout(async () => {
      try {
        const params = new URLSearchParams({ start_date: start, end_date: end, minimum_weeks: minimumWeeks });
        if (userFilter && userFilter !== '全部' && userFilter !== 'all') params.set('user', userFilter);
        const response = await fetchWithAuth(`/api/v1/dashboard/spending-calendar?${params}`, { signal: controller.signal });
        if (!response.ok) throw new Error('calendar request failed');
        const result = await response.json();
        if (!controller.signal.aborted) setExpandedData({ source: data, minimumWeeks, data: result });
      } catch (error) {
        if (!controller.signal.aborted) setCalendarError({ source: data, minimumWeeks });
      } finally {
        if (!controller.signal.aborted) setCalendarLoading(false);
      }
    }, 120);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [data, minimumWeeks, userFilter, reportCurrency, retryCount]);

  useEffect(() => {
    setTouchMode(window.matchMedia('(hover: none) and (pointer: coarse)').matches);
    return () => clearTimeout(gestureRef.current?.timer);
  }, []);

  const allWeeks = calendarData?.weeks || [];
  const endLabel = calendarData?.end_date || (() => {
    const now = new Date();
    return `${now.getFullYear()}年${String(now.getMonth() + 1).padStart(2, '0')}月${String(now.getDate()).padStart(2, '0')}日`;
  })();

  // 星期标签 (周一到周日)
  const dayNames = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
  const shortDayNames = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  // A first visit shows the latest week; a returning visit keeps the week viewed.
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollLeft = scrollLeft ?? scrollRef.current.scrollWidth;
  }, [calendarData, scrollLeft]);

  useEffect(() => {
    setHoveredDetail(null);
  }, [calendarData]);

  const visibleWeeks = allWeeks;

  // 3. 计算当前铺满展示的动态日期范围
  const displayRange = useMemo(() => {
    if (visibleWeeks.length === 0) return `${endLabel} – ${endLabel}`;
    const startDay = calendarData?.start_date || visibleWeeks[0]?.find(day => !day.outside)?.date;
    const endWeek = visibleWeeks[visibleWeeks.length - 1];
    const endDay = calendarData?.end_date || [...(endWeek || [])].reverse().find(day => !day.outside)?.date;

    const formatYMD = (dStr) => {
      if (!dStr) return '';
      const parts = dStr.split('-');
      if (parts.length === 3) {
        return `${parts[0]}年${parts[1]}月${parts[2]}日`;
      }
      return dStr;
    };

    return `${formatYMD(startDay)} – ${formatYMD(endDay || endLabel)}`;
  }, [visibleWeeks, endLabel, calendarData?.start_date, calendarData?.end_date]);

  // Spending and refunds use matching shades and opacity for each magnitude level.
  const getCellColor = (day) => {
    if (day.outside) {
      return 'bg-zinc-100/40 dark:bg-zinc-800/20 border-zinc-200/30 dark:border-zinc-800/40 opacity-30';
    }
    if (day.level === 0 || day.amount === 0) {
      return 'bg-zinc-100/80 dark:bg-zinc-800/70 border-zinc-200/60 dark:border-zinc-700/60';
    }
    const palette = day.is_refund || day.amount < 0
      ? [
          'bg-emerald-400/30 dark:bg-emerald-950/40 border-emerald-300 dark:border-emerald-900/60 text-emerald-700 dark:text-emerald-300',
          'bg-emerald-500/50 dark:bg-emerald-900/60 border-emerald-400 dark:border-emerald-800/80 text-white',
          'bg-emerald-500/80 dark:bg-emerald-700/80 border-emerald-500 text-white shadow-2xs',
          'bg-emerald-600 dark:bg-emerald-600 border-emerald-600 text-white shadow-xs',
        ]
      : [
          'bg-red-400/30 dark:bg-red-950/40 border-red-300 dark:border-red-900/60 text-red-700 dark:text-red-300',
          'bg-red-500/50 dark:bg-red-900/60 border-red-400 dark:border-red-800/80 text-white',
          'bg-red-500/80 dark:bg-red-700/80 border-red-500 text-white shadow-2xs',
          'bg-red-600 dark:bg-red-600 border-red-600 text-white shadow-xs',
        ];
    return palette[day.level - 1] || palette[3];
  };

  // 月份标签生成
  const getMonthLabel = (weekIndex) => {
    if (!visibleWeeks[weekIndex] || !visibleWeeks[weekIndex][0]) return '';
    const dateStr = visibleWeeks[weekIndex][0].date;
    const month = parseInt(dateStr.slice(5, 7), 10);
    if (weekIndex === 0) return `${month}月`;
    const prevDateStr = visibleWeeks[weekIndex - 1][0].date;
    const prevMonth = parseInt(prevDateStr.slice(5, 7), 10);
    if (month !== prevMonth) return `${month}月`;
    return '';
  };

  const handleCellClick = (day) => {
    if (day.outside) return;
    const params = new URLSearchParams({ start_date: day.date, end_date: day.date });
    if (userFilter && userFilter !== '全部' && userFilter !== 'all') params.set('user', userFilter);
    navigate(`/transactions?${params.toString()}`);
  };

  const cancelGesture = () => {
    clearTimeout(gestureRef.current?.timer);
    gestureRef.current = null;
  };

  const handlePointerDown = (event, day) => {
    if (event.pointerType === 'mouse') {
      touchClickRef.current = false;
      setTouchMode(false);
      return;
    }
    touchClickRef.current = true;
    setTouchMode(true);
    if (!event.isPrimary || gestureRef.current) {
      // A second finger must cancel, rather than complete, a long press.
      if (gestureRef.current) {
        clearTimeout(gestureRef.current.timer);
        gestureRef.current.moved = true;
      }
      return;
    }
    const gesture = {
      pointerId: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      moved: false,
      opened: false,
      day,
    };
    gesture.timer = setTimeout(() => {
      gesture.opened = true;
      handleCellClick(day);
    }, 550);
    gestureRef.current = gesture;
  };

  const handlePointerMove = (event) => {
    const gesture = gestureRef.current;
    if (!gesture || event.pointerId !== gesture.pointerId) return;
    if (Math.hypot(event.clientX - gesture.x, event.clientY - gesture.y) > 10) {
      gesture.moved = true;
      clearTimeout(gesture.timer);
    }
  };

  const handlePointerUp = (event) => {
    const gesture = gestureRef.current;
    if (!gesture || event.pointerId !== gesture.pointerId) return;
    if (!gesture.moved && !gesture.opened) setHoveredDetail(gesture.day);
    cancelGesture();
  };

  const formatMoney = amt => formatAmount(Math.abs(amt || 0));

  React.useEffect(() => { cancelGesture(); }, [privacyMode]);

  const tooltipFor = day => {
    const amount = day.amount < 0
      ? tx('退款: -{p0}', {p0: formatMoney(day.amount)})
      : day.amount > 0 ? tx('支出: {p0}', {p0: formatMoney(day.amount)}) : tx('无消费');
    return `${day.date} · ${amount}${day.description ? ` (${day.description})` : ''}`;
  };

  const defaultDetail = touchMode
    ? tx('点按查看当天消费金额，长按查看当天流水')
    : tx('悬停查看当天消费金额，点击查看当天流水');

  return (
    <div
      className="space-y-3.5 w-full select-none"
    >
      {/* ── 标题与日期范围 (严格对标 Sure _spending_calendar.html.erb) ── */}
      <div className="flex flex-col gap-0.5">
        <p className="text-sm font-semibold text-zinc-700 dark:text-zinc-200">{tx('短日期范围自动补充历史消费，长日期范围可横向滑动')}</p>
        <p data-testid="spending-calendar-range" className="text-xs font-mono text-zinc-400 dark:text-zinc-500 transition-all">
          {dateLabel(displayRange)}
          {calendarLoading && <span role="status" aria-label={tx('正在加载历史消费…')} title={tx('正在加载历史消费…')} className="inline-block ml-2 h-3 w-3 align-middle rounded-full border-2 border-zinc-300 border-t-zinc-600 animate-spin" />}
        </p>
        {calendarError && calendarError.source === data && calendarError.minimumWeeks === minimumWeeks && (
          <p role="alert" className="text-xs text-rose-600 dark:text-rose-400">
            {tx('历史消费加载失败，当前仅显示所选日期。')}{' '}
            <button type="button" className="underline" onClick={() => setRetryCount(count => count + 1)}>{tx('重试')}</button>
          </p>
        )}
      </div>

      {/* ── 热力图网格主视口 (满宽自适应) ── */}
      <div ref={scrollRef} onScroll={(event) => setScrollLeft(event.currentTarget.scrollLeft)} data-testid="spending-calendar-scroll" className="w-full overflow-x-auto pb-1 scrollbar-thin">
        <div className="inline-flex gap-2 items-start min-w-full w-max">
          {/* 左侧：周一至周日标签 */}
          <div className="grid grid-rows-7 gap-1 pt-6 w-10 shrink-0 text-xs text-zinc-400 dark:text-zinc-500 font-medium select-none sticky left-0 bg-white/95 dark:bg-zinc-900/95 backdrop-blur-xs z-10">
            {dayNames.map((name, i) => (
              <span key={i} title={tx(name)} className="flex h-8 items-center text-xs">
                {locale === 'zh-CN' ? name : shortDayNames[i]}
              </span>
            ))}
          </div>

          {/* 右侧：按周排列的自适应满宽格子列 (每列 32px, 间距 4px) */}
          <div
            className="grid gap-1 flex-1 transition-all duration-150"
            style={{
              gridTemplateColumns: `repeat(${visibleWeeks.length}, 32px)`,
              minWidth: Math.max(0, visibleWeeks.length * 36 - 4),
              justifyContent: 'space-between',
            }}
          >
            {visibleWeeks.map((week, wIdx) => {
              const monthLabel = getMonthLabel(wIdx);
              return (
                <div
                  key={wIdx}
                  className="space-y-1 w-8 shrink-0"
                >
                  {/* 月份标题 */}
                  <p className="h-5 text-left text-xs text-zinc-400 dark:text-zinc-500 font-medium overflow-visible whitespace-nowrap">
                    {dateLabel(monthLabel)}
                  </p>

                  {/* 一周 7 天 (严格 32px x 32px = w-8 h-8) */}
                  <div className="grid grid-rows-7 gap-1">
                    {week.map((day) => {
                      const tooltip = tooltipFor(day);

                      return (
                        <button
                          key={day.date}
                          type="button"
                          data-testid="spending-calendar-cell"
                          data-date={day.date}
                          disabled={day.outside}
                          onClick={(event) => {
                            // Touch generates a click after pointerup; only desktop clicks
                            // and keyboard activation should use the click navigation path.
                            if (touchClickRef.current && event.detail > 0) {
                              event.preventDefault();
                              return;
                            }
                            handleCellClick(day);
                          }}
                          onPointerDown={(event) => handlePointerDown(event, day)}
                          onPointerMove={handlePointerMove}
                          onPointerUp={handlePointerUp}
                          onPointerCancel={cancelGesture}
                          onPointerEnter={(event) => {
                            if (event.pointerType === 'mouse') setHoveredDetail(day);
                          }}
                          onPointerLeave={(event) => {
                            if (event.pointerType === 'mouse') setHoveredDetail(null);
                            else cancelGesture();
                          }}
                          onContextMenu={(event) => {
                            if (touchClickRef.current) event.preventDefault();
                          }}
                          style={{ WebkitTouchCallout: 'none' }}
                          className={`block h-8 w-8 rounded-md border touch-manipulation transition-transform hover:scale-105 active:scale-95 cursor-pointer ${getCellColor(
                            day
                          )}`}
                          title={tooltip}
                          aria-label={tooltip}
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

      {/* ── 底部交互明细信息条 (对标 Sure data-spending-calendar-target="detail") ── */}
      <div data-testid="spending-calendar-detail" className="min-h-10 rounded-xl bg-zinc-50 dark:bg-zinc-800/60 border border-zinc-200/70 dark:border-zinc-800 px-3.5 py-2.5 text-xs text-zinc-600 dark:text-zinc-300 flex items-center justify-between transition-colors shadow-2xs">
        <span className="font-mono font-medium">
          {hoveredDetail ? tooltipFor(hoveredDetail) : defaultDetail}
        </span>
        {hoveredDetail && (
          <span className="text-[11px] text-zinc-400 shrink-0 ml-2 hidden sm:inline">{touchMode ? tx('长按查看流水 →') : tx("点击穿透查看流水 →")}</span>
        )}
      </div>
    </div>
  );
}

export default React.memo(SureSpendingCalendar);
