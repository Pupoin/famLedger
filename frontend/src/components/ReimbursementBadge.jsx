import { tx, useLocale } from "../localization.js";
import React, { useState, useRef, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { CheckCircle2, Clock, Ban, X, ChevronDown, RotateCcw, Check } from 'lucide-react';
import { fetchWithAuth } from '../api/fetchWithAuth';
import { useToast } from '../ToastContext';
import { getReimbursementSummary } from '../utils/reimbursement';

/** 计算 fixed 浮层弹出位置，确保完全在视口内显示，永不被裁剪遮挡 */
function calcPopoverPosition(triggerEl) {
  const rect = triggerEl.getBoundingClientRect();
  const popW = 260; // 宽度约 260px
  const popH = 380; // 预估最大高度约 380px
  const margin = 8;

  let top = rect.bottom + margin;
  let left = rect.left;

  // 水平边界防溢出
  if (left + popW > window.innerWidth - margin) {
    left = window.innerWidth - popW - margin;
  }
  if (left < margin) left = margin;

  // 垂直边界防溢出：若下方空间不足则向上弹出，并严格贴边限制不超过屏幕
  if (top + popH > window.innerHeight - margin) {
    top = rect.top - popH - margin;
    if (top < margin) {
      top = Math.max(margin, window.innerHeight - popH - margin);
    }
  }

  return { top, left };
}

export default function ReimbursementBadge({ txn, onStatusUpdated }) {
  useLocale();
  const { showToast } = useToast();
  const [isOpen, setIsOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [popoverPos, setPopoverPos] = useState({ top: 0, left: 0 });
  const [editingCounterparty, setEditingCounterparty] = useState('');
  const triggerRef = useRef(null);
  const popoverRef = useRef(null);

  const summary = getReimbursementSummary(txn);

  // 打开时计算屏幕位置并初始化对象名称
  const openPopover = useCallback((e) => {
    e.stopPropagation();
    if (isOpen) {
      setIsOpen(false);
      return;
    }
    if (triggerRef.current) {
      setPopoverPos(calcPopoverPosition(triggerRef.current));
    }
    setEditingCounterparty(summary.counterparty);
    setIsOpen(true);
  }, [isOpen, summary.counterparty]);


  // 点击外部检测
  useEffect(() => {
    if (!isOpen) return;

    function handleClickOutside(e) {
      if (triggerRef.current && triggerRef.current.contains(e.target)) return;
      if (popoverRef.current && popoverRef.current.contains(e.target)) return;
      setIsOpen(false);
    }

    const id = setTimeout(() => {
      document.addEventListener('pointerdown', handleClickOutside);
    }, 0);
    return () => {
      clearTimeout(id);
      document.removeEventListener('pointerdown', handleClickOutside);
    };
  }, [isOpen]);

  // 页面滚动时更新位置或关闭
  useEffect(() => {
    if (!isOpen) return;
    const handleScroll = () => {
      if (triggerRef.current) {
        setPopoverPos(calcPopoverPosition(triggerRef.current));
      }
    };
    window.addEventListener('scroll', handleScroll, true);
    return () => window.removeEventListener('scroll', handleScroll, true);
  }, [isOpen]);

  if (!summary.isReimbursable) return null;

  const isCorporate = summary.isCorporate;
  const counterparty = summary.counterparty;
  const currentStatus = summary.status;
  const isSettled = summary.isSettled;

  // 统一更新状态或报销配置
  const handleUpdate = async (updates) => {
    try {
      setLoading(true);
      const res = await fetchWithAuth(
        `/api/v1/transactions/${txn.id}/reimbursement`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(updates),
        }
      );

      if (res.ok) {
        const data = await res.json();
        showToast(tx("报销设置已更新"), 'success');
        setIsOpen(false);
        if (onStatusUpdated) {
          onStatusUpdated(txn.id, {
            is_reimbursable: data.is_reimbursable,
            reimbursement_status: data.reimbursement_status,
            excluded_from_stats: data.excluded_from_stats,
            extra: data.extra,
          });
        }
      } else {
        showToast(tx("更新失败"), 'error');
      }
    } catch {
      showToast(tx("网络错误"), 'error');
    } finally {
      setLoading(false);
    }
  };

  // 切换报销类型
  const handleChangeType = (newType) => {
    const isCorp = newType === 'corporate';
    const newStatus = isCorp ? '审批中' : '待还款';
    const newCp = isCorp ? '公司' : (counterparty === '公司' ? '张三' : counterparty);
    setEditingCounterparty(newCp);
    handleUpdate({
      is_reimbursable: true,
      reimbursement_type: newType,
      reimbursement_status: newStatus,
      counterparty: newCp,
    });
  };

  // 保存修改对象姓名
  const handleSaveCounterparty = (e) => {
    e?.preventDefault();
    if (!editingCounterparty.trim()) {
      showToast(tx("请输入往来对象名称"), 'error');
      return;
    }
    handleUpdate({ counterparty: editingCounterparty.trim() });
  };

  // 取消报销
  const handleCancelReimbursement = () => {
    handleUpdate({
      is_reimbursable: false,
      reimbursement_status: null,
      excluded_from_stats: false,
    });
  };

  const corporateStatuses = [
    { label: '未提报', icon: Clock },
    { label: '审批中', icon: Clock },
    { label: '已打款', icon: CheckCircle2 },
  ];

  const personalStatuses = [
    { label: '待还款', icon: Clock },
    { label: '部分已还', icon: Clock },
    { label: '已结清', icon: CheckCircle2 },
  ];

  const statusList = isCorporate ? corporateStatuses : personalStatuses;

  // 使用 fixed 定位并渲染到 body
  const popoverContent = isOpen
    ? createPortal(
        <div
          ref={popoverRef}
          onClick={(e) => e.stopPropagation()}
          style={{
            position: 'fixed',
            top: popoverPos.top,
            left: popoverPos.left,
            zIndex: 999999,
            width: 250,
          }}
          className="p-3 rounded-2xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 shadow-2xl space-y-2.5 text-zinc-900 dark:text-zinc-100 animate-in fade-in zoom-in-95 duration-150 select-none"
        >
          {/* Header */}
          <div className="flex items-center justify-between pb-1.5 border-b border-zinc-100 dark:border-zinc-800">
            <span className="text-[11px] font-bold text-zinc-500 uppercase tracking-wider">{tx("报销与代垫设置")}</span>
            <button
              onClick={() => setIsOpen(false)}
              className="text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 p-0.5"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* 报销性质切换 (选择是否报销 / 报销模式) */}
          <div className="space-y-1">
            <label className="text-[11px] font-semibold text-zinc-400 uppercase">{tx("报销类型")}</label>
            <div className="grid grid-cols-2 gap-1.5 p-1 bg-zinc-100 dark:bg-zinc-800/80 rounded-xl">
              <button
                type="button"
                disabled={loading}
                onClick={() => handleChangeType('corporate')}
                className={`flex items-center justify-center gap-1 py-1.5 rounded-lg text-xs font-semibold transition ${
                  isCorporate
                    ? 'bg-white dark:bg-zinc-700 text-blue-600 dark:text-blue-400 shadow-xs'
                    : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-white'
                }`}
              >
                <span>🏢</span>
                <span>{tx("公费报销")}</span>
              </button>
              <button
                type="button"
                disabled={loading}
                onClick={() => handleChangeType('personal_advance')}
                className={`flex items-center justify-center gap-1 py-1.5 rounded-lg text-xs font-semibold transition ${
                  !isCorporate
                    ? 'bg-white dark:bg-zinc-700 text-amber-600 dark:text-amber-400 shadow-xs'
                    : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-white'
                }`}
              >
                <span>👤</span>
                <span>{tx("代垫借款")}</span>
              </button>
            </div>
          </div>

          {/* 往来对象编辑 (解决用户反馈“张三”看不到可编辑的地方) */}
          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <label className="text-[11px] font-semibold text-zinc-400 uppercase">
                {isCorporate ? tx("报销对象 / 公司部门") : tx("欠款人 / 往来对象")}
              </label>
              {editingCounterparty.trim() && editingCounterparty.trim() !== counterparty && (
                <button
                  type="button"
                  onClick={handleSaveCounterparty}
                  disabled={loading}
                  className="text-[11px] text-blue-600 dark:text-blue-400 font-bold hover:underline cursor-pointer"
                >{tx("保存对象")}</button>
              )}
            </div>
            <input
              type="text"
              data-testid="reimb-badge-counterparty-input"
              value={editingCounterparty}
              onChange={(e) => setEditingCounterparty(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleSaveCounterparty(e);
              }}
              placeholder={isCorporate ? tx("如：公司财务部") : tx("如：张三")}
              className="w-full px-2.5 py-1 text-xs rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-white focus:outline-hidden focus:ring-1 focus:ring-blue-500"
            />
          </div>

          {/* 状态选项列表 */}
          <div className="space-y-1">
            <label className="text-[11px] font-semibold text-zinc-400 uppercase">{tx("当前流转状态")}</label>
            <div className="space-y-1">
              {statusList.map((st) => {
                const active = currentStatus === st.label;
                const Icon = st.icon;
                return (
                  <button
                    key={st.label}
                    data-testid={`reimb-status-option-${st.label}`}
                    disabled={loading}
                    onClick={() => handleUpdate({ reimbursement_status: st.label })}
                    className={`w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer ${
                      active
                        ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-900 font-semibold'
                        : 'text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800'
                    }`}
                  >
                    <span className="flex items-center gap-2">
                      <Icon className="w-3.5 h-3.5" />
                      <span>{tx(st.label)}</span>
                    </span>
                    {active && (
                      <Check className="w-3.5 h-3.5 text-emerald-400 dark:text-emerald-600" />
                    )}
                  </button>
                );
              })}
            </div>
          </div>

          {/* 切换是否不计支出 */}
          <div className="pt-2 border-t border-zinc-100 dark:border-zinc-800 space-y-1.5">
            <button
              onClick={() => handleUpdate({ excluded_from_stats: !txn.excluded_from_stats })}
              disabled={loading}
              className="w-full flex items-center justify-between py-1 text-[11px] font-medium text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100 cursor-pointer"
            >
              <span className="flex items-center gap-1.5">
                <Ban className="w-3 h-3 text-zinc-400" />
                <span>{tx("不计入家庭支出统计")}</span>
              </span>
              <span
                className={`w-3.5 h-3.5 rounded border flex items-center justify-center text-[11px] ${
                  txn.excluded_from_stats
                    ? 'bg-zinc-900 text-white border-zinc-900 dark:bg-white dark:text-zinc-900'
                    : 'border-zinc-300 dark:border-zinc-600'
                }`}
              >
                {txn.excluded_from_stats ? '✓' : ''}
              </span>
            </button>

            {/* 取消报销按钮 */}
            <button
              onClick={handleCancelReimbursement}
              disabled={loading}
              className="w-full flex items-center justify-center gap-1 py-1 rounded-lg text-[11px] font-medium text-zinc-400 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors"
            >
              <RotateCcw className="w-3 h-3" />
              <span>{tx("取消报销，设为普通交易")}</span>
            </button>
          </div>
        </div>,
        document.body
      )
    : null;

  return (
    <>
      {/* Keep the counterparty and status readable at narrow widths. */}
      <button
        ref={triggerRef}
        type="button"
        data-testid="reimbursement-badge-trigger"
        onClick={openPopover}
        className={`inline-flex items-center gap-1 sm:gap-1.5 min-w-0 w-max max-w-full px-2 py-0.5 sm:px-2.5 sm:py-1 rounded-2xl text-[11px] font-semibold leading-snug transition-all shadow-2xs cursor-pointer select-none active:scale-95 border ${
          isSettled
            ? 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border-emerald-200/80 dark:border-emerald-800'
            : isCorporate
            ? 'bg-blue-50 hover:bg-blue-100/80 dark:bg-blue-950/40 dark:hover:bg-blue-900/50 text-blue-700 dark:text-blue-300 border-blue-200/80 dark:border-blue-800'
            : 'bg-amber-50 hover:bg-amber-100/80 dark:bg-amber-950/40 dark:hover:bg-amber-900/50 text-amber-700 dark:text-amber-300 border-amber-200/80 dark:border-amber-800'
        }`}
        aria-label={`${tx(isCorporate ? "公费报销" : "朋友代垫")} · ${counterparty} · ${tx(currentStatus)}`}
        title={`${tx(isCorporate ? "公费报销" : "朋友代垫")} · ${counterparty} · ${tx(currentStatus)}\n${tx("点击配置报销与还款状态，修改往来对象")}`}
      >
        {isCorporate ? (
          <span className="shrink-0 text-xs">🏢</span>
        ) : (
          <span className="shrink-0 text-xs">👤</span>
        )}
        <span className="min-w-0 text-left [overflow-wrap:anywhere]">
          <span data-testid="reimbursement-badge-counterparty">
            {counterparty}
          </span>
          {" "}
          <span data-testid="reimbursement-badge-status" className="inline-block font-bold">
            · {tx(currentStatus)}
          </span>
        </span>
        <ChevronDown
          className={`w-3 h-3 shrink-0 transition-transform ${isOpen ? 'rotate-180' : ''}`}
        />
      </button>

      {/* Fixed Popover Content */}
      {popoverContent}
    </>
  );
}
