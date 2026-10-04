import { tx, useLocale } from "../localization.js";
import React, { useState, useEffect, useRef, useMemo } from 'react';
import { ChevronDown, Check, Users } from 'lucide-react';
import { renderAccountLogo, formatAccountDisplayName } from '../utils/accountIcons';

/**
 * 严格对齐 ~/me/1.png 的全平台同构账户选择下拉组件
 *
 * 特性：
 * 1. 包含银行专属 Logo / 资产分类图标渲染
 * 2. 区分「我的账户 (N)」与「家人共享 (N)」分组（带紫色胶囊标头与成员标记）
 * 3. 支持只读权限徽标 [只读]
 * 4. 支持 emptyLabel="无 (独立主账户)"
 * 5. 移动端/桌面端完全统一的精致 text-xs (12px) 布局与平滑展开动画
 * 6. 内置隐藏原生 select 保持对表单及自动化测试完全兼容
 */
export default function AccountSelectDropdown({
  name = 'account_id',
  value = '',
  onChange,
  accounts = [],
  selectedAccountFallback = null,
  disabled = false,
  placeholder = '选择账户',
  emptyLabel = null,
  isReadOnly = false,
  showSharedTip = false,
  testId,
  className = '',
}) {
  useLocale();
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef(null);

  const selectedAccount = useMemo(() => {
    if (!value) return null;
    return accounts.find((a) => String(a.id) === String(value))
      || (String(selectedAccountFallback?.id) === String(value) ? selectedAccountFallback : null);
  }, [accounts, value, selectedAccountFallback]);

  const { myAccounts, sharedAccounts } = useMemo(() => {
    const my = [];
    const shared = [];
    accounts.forEach((acc) => {
      if (acc.is_owner === false) {
        shared.push(acc);
      } else {
        my.push(acc);
      }
    });
    return { myAccounts: my, sharedAccounts: shared };
  }, [accounts]);

  // 点击外部收起
  useEffect(() => {
    const handleOutsideClick = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setIsOpen(false);
      }
    };
    if (isOpen) {
      document.addEventListener('mousedown', handleOutsideClick);
    }
    return () => document.removeEventListener('mousedown', handleOutsideClick);
  }, [isOpen]);

  const handleSelect = (accId) => {
    if (disabled) return;
    if (onChange) {
      onChange({ target: { name, value: accId } });
    }
    setIsOpen(false);
  };

  const renderOptionItem = (acc) => {
    const isSelected = String(acc.id) === String(value);
    const isShared = acc.is_owner === false;
    return (
      <div
        key={acc.id}
        data-testid={`account-option-${acc.id}`}
        onClick={() => handleSelect(acc.id)}
        className={`flex items-center justify-between px-2.5 py-1.5 text-xs rounded-lg mx-1 cursor-pointer transition-colors ${
          isSelected
            ? 'bg-zinc-100 dark:bg-zinc-800 font-semibold'
            : 'hover:bg-zinc-50 dark:hover:bg-zinc-800/60'
        }`}
      >
        <div className="flex items-center gap-2 min-w-0 pr-2">
          {renderAccountLogo(acc, {
            className: 'w-3.5 h-3.5',
            containerClassName: 'w-6 h-6 rounded-lg border shadow-2xs',
          })}
          <span className="truncate text-zinc-900 dark:text-zinc-100">
            {formatAccountDisplayName(acc)}
          </span>
          {isShared && (
            <span
              title={tx("由 {p0} 共享", {p0: (acc.owner)})}
              className="inline-flex items-center gap-0.5 px-1 py-0.5 rounded text-[10.5px] font-medium bg-purple-50 dark:bg-purple-950/60 text-purple-600 dark:text-purple-400 border border-purple-200/60 dark:border-purple-800/60 shrink-0"
            >
              <Users className="w-2.5 h-2.5" />
              {acc.owner}
            </span>
          )}
          {acc.can_edit === false && (
            <span className="text-[10.5px] px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-900/60 text-amber-800 dark:text-amber-200 shrink-0 font-medium">{tx("只读")}</span>
          )}
        </div>
        {isSelected && (
          <Check className="w-3.5 h-3.5 text-zinc-900 dark:text-zinc-100 shrink-0 ml-1" />
        )}
      </div>
    );
  };

  const renderEmptyOption = () => {
    if (!emptyLabel) return null;
    const isSelected = !value;
    return (
      <div
        key="__empty__"
        data-testid="account-option-empty"
        onClick={() => handleSelect('')}
        className={`flex items-center justify-between px-2.5 py-1.5 text-xs rounded-lg mx-1 cursor-pointer transition-colors ${
          isSelected
            ? 'bg-zinc-100 dark:bg-zinc-800 font-semibold'
            : 'hover:bg-zinc-50 dark:hover:bg-zinc-800/60'
        }`}
      >
        <div className="flex items-center gap-2 min-w-0 pr-2">
          <div className="w-6 h-6 rounded-lg border border-dashed border-zinc-300 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800/50 flex items-center justify-center shrink-0">
            <span className="text-[11px] text-zinc-400 font-medium">—</span>
          </div>
          <span className="truncate text-zinc-700 dark:text-zinc-300">
            {tx(emptyLabel)}
          </span>
        </div>
        {isSelected && (
          <Check className="w-3.5 h-3.5 text-zinc-900 dark:text-zinc-100 shrink-0 ml-1" />
        )}
      </div>
    );
  };

  return (
    <div className={`relative w-full ${className}`} ref={dropdownRef}>
      {/* 原生隐藏 select：确保表单与自动化测试兼容 */}
      <select
        name={name}
        value={value || ''}
        onChange={onChange}
        disabled={disabled}
        className="sr-only"
        tabIndex={-1}
        aria-hidden="true"
      >
        {emptyLabel && <option value="">{tx(emptyLabel)}</option>}
        {selectedAccount && !accounts.some((a) => String(a.id) === String(value)) && (
          <option value={selectedAccount.id} disabled>{formatAccountDisplayName(selectedAccount)}</option>
        )}
        {accounts.map((acc) => (
          <option key={acc.id} value={acc.id}>
            {formatAccountDisplayName(acc)}
          </option>
        ))}
      </select>

      {/* 自定义触发器按钮 */}
      <button
        type="button"
        data-testid={testId || `select-${name}`}
        disabled={disabled}
        onClick={() => setIsOpen((prev) => !prev)}
        className={`w-full px-3 py-2 rounded-xl border text-xs transition text-left flex items-center justify-between cursor-pointer ${
          isReadOnly
            ? 'border-amber-400 dark:border-amber-600 bg-amber-50/40 dark:bg-amber-950/30 text-amber-950 dark:text-amber-200'
            : isOpen
            ? 'border-zinc-900 dark:border-white ring-2 ring-zinc-900/10 dark:ring-white/20 bg-white dark:bg-zinc-800'
            : 'border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 hover:border-zinc-300 dark:hover:border-zinc-600'
        }`}
      >
        <div className="flex items-center gap-2 min-w-0 pr-2">
          {selectedAccount ? (
            <>
              {renderAccountLogo(selectedAccount, {
                className: 'w-3.5 h-3.5',
                containerClassName: 'w-6 h-6 rounded-lg border shadow-2xs',
              })}
              <span className="truncate text-zinc-900 dark:text-zinc-100 font-medium">
                {formatAccountDisplayName(selectedAccount)}
              </span>
              {selectedAccount.is_owner === false && (
                <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10.5px] font-semibold bg-purple-50 dark:bg-purple-950/60 text-purple-600 dark:text-purple-400 border border-purple-200/60 dark:border-purple-800/60 shrink-0">
                  <Users className="w-2.5 h-2.5" />
                  {selectedAccount.relationship_only ? tx("主卡所有者：{p0}", {p0: (selectedAccount.owner)}) : tx("{p0} 共享", {p0: (selectedAccount.owner)})}
                </span>
              )}
              {selectedAccount.can_edit === false && (
                <span className="text-[10.5px] px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-900/60 text-amber-800 dark:text-amber-200 shrink-0 font-medium">{tx("只读")}</span>
              )}
            </>
          ) : emptyLabel && !value ? (
            <div className="flex items-center gap-2">
              <div className="w-5 h-5 rounded-md border border-dashed border-zinc-300 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800/50 flex items-center justify-center shrink-0 text-[10px] text-zinc-400 font-medium">
                —
              </div>
              <span className="truncate text-zinc-700 dark:text-zinc-300 font-medium">
                {tx(emptyLabel)}
              </span>
            </div>
          ) : (
            <span className="text-zinc-400 dark:text-zinc-500">{tx(placeholder)}</span>
          )}
        </div>
        <ChevronDown
          className={`w-3.5 h-3.5 text-zinc-400 transition-transform duration-200 shrink-0 ${
            isOpen ? 'rotate-180' : ''
          }`}
        />
      </button>

      {/* 共享账户防呆实时提醒 */}
      {showSharedTip && selectedAccount && selectedAccount.is_owner === false && !isReadOnly && (
        <p className="text-[11px] text-purple-600 dark:text-purple-400 flex items-center gap-1 mt-1.5 font-medium animate-in fade-in">
          <Users className="w-3 h-3 shrink-0" />
          <span>{tx("当前正在为")} <strong>{selectedAccount.owner}</strong> {tx("的共享账户记账")}</span>
        </p>
      )}

      {/* 展开浮层菜单 */}
      {isOpen && (
        <div className="absolute left-0 right-0 top-full mt-1.5 z-50 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-xl shadow-xl max-h-60 overflow-y-auto py-1 animate-in fade-in-50 zoom-in-95 duration-100">
          {emptyLabel && (
            <div className="pb-1 border-b border-zinc-100 dark:border-zinc-800 mb-1">
              {renderEmptyOption()}
            </div>
          )}

          {accounts.length === 0 ? (
            <div className="px-3 py-3 text-xs text-center text-zinc-400">
              {emptyLabel ? tx("暂无其他可选账户") : tx("暂无可选择的账户")}
            </div>
          ) : sharedAccounts.length > 0 ? (
            <>
              {/* 我的账户组 */}
              {myAccounts.length > 0 && (
                <div>
                  <div className="px-3 py-1.5 text-[10.5px] font-semibold text-zinc-400 dark:text-zinc-500 uppercase tracking-wider bg-zinc-50/60 dark:bg-zinc-800/40">{tx("我的账户 (")} {myAccounts.length})
                  </div>
                  {myAccounts.map(renderOptionItem)}
                </div>
              )}

              {/* 家人共享组 */}
              {sharedAccounts.length > 0 && (
                <div className={myAccounts.length > 0 ? 'border-t border-zinc-100 dark:border-zinc-800 mt-1 pt-1' : ''}>
                  <div className="px-3 py-1.5 text-[10.5px] font-semibold text-purple-600 dark:text-purple-400 flex items-center gap-1 uppercase tracking-wider bg-purple-50/40 dark:bg-purple-950/20">
                    <Users className="w-3 h-3" /> {tx("家人共享 (")} {sharedAccounts.length})
                  </div>
                  {sharedAccounts.map(renderOptionItem)}
                </div>
              )}
            </>
          ) : (
            accounts.map(renderOptionItem)
          )}
        </div>
      )}
    </div>
  );
}
