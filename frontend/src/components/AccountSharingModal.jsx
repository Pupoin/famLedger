import { tx, useLocale } from "../localization.js";
import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { X, Shield, ChevronDown, Edit2, ArrowRightLeft, Trash2 } from 'lucide-react';
import { fetchWithAuth } from '../api/fetchWithAuth';
import { useToast } from '../ToastContext';

export default function AccountSharingModal({
  accountId,
  open,
  isOpen,
  onClose,
  onUpdated,
  onSuccess,
  onEdit,
  onTransfer,
  onDelete,
}) {
  useLocale();
  const isModalOpen = Boolean(open ?? isOpen);
  const handleUpdated = onUpdated || onSuccess;
  const { showToast } = useToast();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [data, setData] = useState(null);

  // 共享草稿状态
  const [members, setMembers] = useState([]);
  const [includeInFinances, setIncludeInFinances] = useState(true);

  useEffect(() => {
    if (!isModalOpen || !accountId) return;
    let cancelled = false;

    (async () => {
      try {
        setLoading(true);
        const res = await fetchWithAuth(`/api/v1/accounts/${accountId}/shares`);
        if (!res.ok) throw new Error(tx("Failed to load shares"));
        const json = await res.json();
        if (cancelled) return;
        setData(json);
        setMembers(json.members || []);
        if (json.my_share) {
          setIncludeInFinances(json.my_share.include_in_finances);
        }
      } catch (err) {
        showToast(tx("获取账户共享设置失败"), 'error');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, [isModalOpen, accountId]);

  if (!isModalOpen) return null;

  const handleToggleShare = (index) => {
    setMembers((prev) =>
      prev.map((m, i) => (i === index ? { ...m, shared: !m.shared } : m))
    );
  };

  const handleChangePermission = (index, perm) => {
    setMembers((prev) =>
      prev.map((m, i) => (i === index ? { ...m, permission: perm } : m))
    );
  };

  const handleSave = async () => {
    try {
      setSaving(true);
      const payload = data?.can_manage
        ? { members }
        : { include_in_finances: includeInFinances };

      const res = await fetchWithAuth(`/api/v1/accounts/${accountId}/shares`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        const result = await res.json();
        showToast(tx(result.unlinked_from_parent ? '共享已取消，副卡关系已解除' : '账户共享权限已成功更新'), 'success');
        onClose();
        if (handleUpdated) handleUpdated();
      } else {
        showToast(tx("更新共享失败"), 'error');
      }
    } catch {
      showToast(tx("网络请求失败"), 'error');
    } finally {
      setSaving(false);
    }
  };

  const modal = (
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center p-4 bg-black/50 backdrop-blur-xs animate-in fade-in duration-150"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="relative w-full max-w-lg bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl border border-zinc-200 dark:border-zinc-800 overflow-hidden flex flex-col max-h-[85vh] animate-in zoom-in-95 duration-150">
        {/* Header */}
        <div className="px-5 py-4 border-b border-zinc-100 dark:border-zinc-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center text-zinc-700 dark:text-zinc-300">
              <Shield className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-zinc-900 dark:text-white">{tx("账户共享与成员授权")}</h3>
              <p className="text-xs text-zinc-400 mt-0.5 truncate max-w-xs">
                {data?.account_name || tx("加载中...")}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label={tx("关闭")}
            data-testid="account-sharing-modal-close-btn"
            className="p-1 rounded-lg text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4 text-xs">
          {loading ? (
            <div className="py-12 flex flex-col items-center justify-center gap-2">
              <div className="w-6 h-6 border-2 border-zinc-900 dark:border-white border-t-transparent rounded-full animate-spin" />
              <span className="text-zinc-400">{tx("正在读取授权配置...")}</span>
            </div>
          ) : data?.can_manage ? (
            <>
              <div className="p-3 rounded-xl bg-zinc-50 dark:bg-zinc-800/60 border border-zinc-100 dark:border-zinc-800 flex items-center justify-between">
                <div>
                  <span className="font-semibold text-zinc-800 dark:text-zinc-200">{tx("拥有者")}</span>
                  <p className="text-[11px] text-zinc-400">{tx("创建并拥有该卡号的唯一所有人")}</p>
                </div>
                <span className="px-2.5 py-1 rounded-full bg-zinc-200 dark:bg-zinc-700 font-bold text-zinc-900 dark:text-zinc-100">
                  {data?.owner?.display_name || data?.owner?.username}
                </span>
              </div>

              {/* 账户核心操作快捷入口 */}
              {(onEdit || onTransfer || onDelete) && (
                <div className="flex items-center justify-between p-2.5 rounded-xl bg-zinc-50 dark:bg-zinc-800/40 border border-zinc-200/80 dark:border-zinc-800">
                  <span className="text-[11px] font-semibold text-zinc-500 dark:text-zinc-400">{tx("账户操作")}</span>
                  <div className="flex items-center gap-1.5 flex-wrap">
                    {onEdit && (
                      <button
                        type="button"
                        data-testid="modal-edit-account-btn"
                        onClick={() => {
                          onClose();
                          onEdit({
                            id: accountId,
                            name: data.account_name,
                            institution_name: data.institution_name,
                            external_identifier: data.external_identifier,
                            account_type: data.account_type || 'checking',
                            balance: data.balance || 0,
                            parent_account_id: data.parent_account_id,
                            parent_account: data.parent_account,
                            can_manage: data.can_manage,
                          });
                        }}
                        className="px-2.5 py-1 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 hover:bg-zinc-100 dark:hover:bg-zinc-700 text-xs font-semibold text-zinc-700 dark:text-zinc-300 transition flex items-center gap-1 cursor-pointer"
                        title={tx("编辑账户基本信息")}
                      >
                        <Edit2 className="w-3 h-3 text-zinc-500" />
                        <span>{tx("编辑")}</span>
                      </button>
                    )}
                    {onTransfer && (
                      <button
                        type="button"
                        data-testid="modal-transfer-account-btn"
                        onClick={() => {
                          onClose();
                          onTransfer({
                            id: accountId,
                            name: data.account_name,
                            owner: data.owner?.display_name || data.owner?.username,
                            can_manage_shares: data.can_manage,
                          });
                        }}
                        className="px-2.5 py-1 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 hover:bg-zinc-100 dark:hover:bg-zinc-700 text-xs font-semibold text-zinc-700 dark:text-zinc-300 transition flex items-center gap-1 cursor-pointer"
                        title={tx("转移账户所有权")}
                      >
                        <ArrowRightLeft className="w-3 h-3 text-blue-500" />
                        <span>{tx("转移")}</span>
                      </button>
                    )}
                    {onDelete && (
                      <button
                        type="button"
                        data-testid="modal-delete-account-btn"
                        onClick={() => {
                          onClose();
                          onDelete({
                            id: accountId,
                            name: data.account_name,
                          });
                        }}
                        className="px-2.5 py-1 rounded-lg border border-red-200 dark:border-red-900/60 bg-red-50/50 dark:bg-red-950/30 hover:bg-red-100/60 dark:hover:bg-red-900/40 text-xs font-semibold text-red-600 dark:text-red-400 transition flex items-center gap-1 cursor-pointer"
                        title={tx("删除该账户")}
                      >
                        <Trash2 className="w-3 h-3 text-red-500" />
                        <span>{tx("删除")}</span>
                      </button>
                    )}
                  </div>
                </div>
              )}

              <div className="space-y-2">
                {data?.parent_account_id && data?.parent_owner_id !== data?.owner?.id && (
                  <p className="text-[11px] text-zinc-500 dark:text-zinc-400">{tx("取消对主卡所有者的共享，会同时解除此账户的副卡关系。账户和流水将保留。")}</p>
                )}
                <div className="flex items-center justify-between text-[11px] font-semibold text-zinc-400 uppercase tracking-wider px-1">
                  <span>{tx("家庭成员")}</span>
                  <span>{tx("细粒度权限")}</span>
                  <span>{tx("开启共享")}</span>
                </div>

                <div className="space-y-2">
                  {members.map((m, idx) => (
                    <div
                      key={m.user_id}
                      className="p-3 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 flex items-center justify-between gap-3 shadow-2xs"
                    >
                      {/* 成员头像与名称 */}
                      <div className="flex items-center gap-2.5 min-w-0">
                        <div className="w-8 h-8 rounded-full bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 font-bold flex items-center justify-center text-xs shrink-0">
                          {m.username.slice(0, 2).toUpperCase()}
                        </div>
                        <div className="min-w-0">
                          <p className="font-bold text-zinc-900 dark:text-zinc-100 text-xs truncate">
                            {m.display_name}
                          </p>
                          <p className="text-[11px] text-zinc-400 font-mono">@{m.username}</p>
                        </div>
                      </div>

                      {/* 权限选择下拉框 */}
                      <div className="flex-1 max-w-[170px] relative">
                        <select
                          value={m.shared ? m.permission : 'none'}
                          onChange={(e) => {
                            const val = e.target.value;
                            if (val === 'none') {
                              setMembers((prev) =>
                                prev.map((item, i) => (i === idx ? { ...item, shared: false } : item))
                              );
                            } else {
                              setMembers((prev) =>
                                prev.map((item, i) => (i === idx ? { ...item, shared: true, permission: val } : item))
                              );
                            }
                          }}
                          className={`w-full py-1.5 pl-2 pr-7 rounded-lg border text-xs font-medium outline-none appearance-none transition ${
                            m.shared
                              ? 'bg-zinc-50 dark:bg-zinc-800 border-zinc-200 dark:border-zinc-700 text-zinc-900 dark:text-zinc-100 focus:ring-1 focus:ring-zinc-900'
                              : 'bg-zinc-100 dark:bg-zinc-800/50 border-zinc-200 dark:border-zinc-700 text-zinc-400'
                          }`}
                        >
                          <option value="none">{tx("🚫 不共享此账号")}</option>
                          <option value="read_only">{tx("👁️ 只读 (查看流水)")}</option>
                          <option value="read_write">{tx("✏️ 读写 (可录入)")}</option>
                          <option value="full_control">{tx("⚡ 完全控制")}</option>
                        </select>
                        <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-zinc-400 pointer-events-none" />
                      </div>

                      {/* 共享开关 Toggle */}
                      <button
                        type="button"
                        onClick={() => handleToggleShare(idx)}
                        className={`w-10 h-6 flex items-center rounded-full p-1 transition-colors shrink-0 cursor-pointer ${
                          m.shared ? 'bg-zinc-900 dark:bg-white' : 'bg-zinc-200 dark:bg-zinc-700'
                        }`}
                      >
                        <div
                          className={`bg-white dark:bg-zinc-900 w-4 h-4 rounded-full shadow-md transform transition-transform ${
                            m.shared ? 'translate-x-4' : 'translate-x-0'
                          }`}
                        />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            </>
          ) : (
            /* 非 Owner：仅可切换 include_in_finances */
            <div className="space-y-4">
              <div className="p-3.5 rounded-xl bg-zinc-50 dark:bg-zinc-800/60 border border-zinc-200 dark:border-zinc-800 space-y-1">
                <span className="text-zinc-500 text-[11px]">{tx("账户所有者")}</span>
                <p className="font-bold text-zinc-900 dark:text-zinc-100 text-sm">
                  {data?.owner?.display_name} (@{data?.owner?.username})
                </p>
                <p className="text-zinc-400 text-[11px] pt-1">{tx("您的访问权限：")} <span className="font-semibold text-zinc-800 dark:text-zinc-200 ml-1">
                    {data?.my_share?.permission === 'full_control'
                      ? tx("完全控制")
                      : data?.my_share?.permission === 'read_write'
                      ? tx("读写 (可录入交易)")
                      : tx("只读 (查看流水)")}
                  </span>
                </p>
              </div>

              <div className="p-4 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 flex items-center justify-between">
                <div>
                  <p className="font-bold text-zinc-900 dark:text-zinc-100 text-xs">{tx("纳入我的财务概览")}</p>
                  <p className="text-[11px] text-zinc-400 mt-0.5">{tx("开启后，该账户的余额与收支将合并计入您的总资产仪表盘与统计报表")}</p>
                </div>
                <button
                  type="button"
                  onClick={() => setIncludeInFinances(!includeInFinances)}
                  className={`w-10 h-6 flex items-center rounded-full p-1 transition-colors shrink-0 cursor-pointer ${
                    includeInFinances ? 'bg-zinc-900 dark:bg-white' : 'bg-zinc-200 dark:bg-zinc-700'
                  }`}
                >
                  <div
                    className={`bg-white dark:bg-zinc-900 w-4 h-4 rounded-full shadow-md transform transition-transform ${
                      includeInFinances ? 'translate-x-4' : 'translate-x-0'
                    }`}
                  />
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-zinc-100 dark:border-zinc-800 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-2 text-xs font-semibold rounded-lg text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition"
          >{tx("取消")}</button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving || loading}
            className="px-4 py-2 text-xs font-bold rounded-lg bg-zinc-900 hover:bg-zinc-800 dark:bg-white dark:text-zinc-900 text-white shadow-xs transition active:scale-95 disabled:opacity-50"
          >
            {saving ? tx("保存中...") : tx("保存授权")}
          </button>
        </div>
      </div>
    </div>
  );

  return createPortal(modal, document.body);
}
