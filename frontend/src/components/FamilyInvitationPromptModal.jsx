import { tx, useLocale } from "../localization.js";
import React, { useState, useEffect } from 'react';
import { Inbox, Check, X, Shield } from 'lucide-react';
import { fetchWithAuth } from '../api/fetchWithAuth';
import { useAuth } from '../auth/AuthContext';
import { useToast } from '../ToastContext';
import CurrencyChangeAlertModal from './CurrencyChangeAlertModal';

const SEEN_STORAGE_KEY_PREFIX = 'famledger_seen_family_invitations_';

export default function FamilyInvitationPromptModal() {
  useLocale();
  const { user } = useAuth();
  const { showToast } = useToast();

  const [unseenInvitations, setUnseenInvitations] = useState([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [processingId, setProcessingId] = useState(null);
  const [currencyChangeModal, setCurrencyChangeModal] = useState({ open: false, data: {} });

  const getSeenIds = () => {
    try {
      const key = `${SEEN_STORAGE_KEY_PREFIX}${user?.username || 'anonymous'}`;
      const raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : [];
    } catch {
      return [];
    }
  };

  const markIdsAsSeen = (ids) => {
    try {
      const key = `${SEEN_STORAGE_KEY_PREFIX}${user?.username || 'anonymous'}`;
      const current = getSeenIds();
      const updated = Array.from(new Set([...current, ...ids]));
      localStorage.setItem(key, JSON.stringify(updated));
    } catch {}
  };

  useEffect(() => {
    if (!user?.username) return;

    let isMounted = true;
    const checkInvitations = async () => {
      try {
        const res = await fetchWithAuth('/api/v1/family/invitations/received');
        if (!res.ok || !isMounted) return;

        const data = await res.json();
        const list = Array.isArray(data.invitations) ? data.invitations : [];
        if (list.length === 0) return;

        const seenIds = getSeenIds();
        const unseen = list.filter((inv) => !seenIds.includes(inv.id));

        if (unseen.length > 0 && isMounted) {
          setUnseenInvitations(unseen);
          setModalOpen(true);
        }
      } catch (err) {
        // 静默失败，不打扰主页面渲染
      }
    };

    checkInvitations();

    return () => {
      isMounted = false;
    };
  }, [user?.username]);

  // 默认展示第一份邀请
  const currentInv = unseenInvitations[0];

  const handleDismiss = () => {
    // 标记当前所有未见邀请为已看，关闭后下次登录首页不再提醒
    const allIds = unseenInvitations.map((inv) => inv.id);
    markIdsAsSeen(allIds);
    setModalOpen(false);
    showToast(tx("已暂存邀请，您可随时在「设置 -> 家庭与成员」中查看并处理"), 'info');
  };

  const handleCurrencyModalClose = () => {
    const famName = currencyChangeModal.data?.familyName || '家庭组';
    const newCurr = currencyChangeModal.data?.new_currency || 'CNY';
    setCurrencyChangeModal({ open: false, data: {} });
    showToast(tx("已成功加入「{p0}」，结算币种已更新为 {p1}！", {p0: (famName), p1: (newCurr)}), 'success');
    setTimeout(() => {
      window.location.reload();
    }, 200);
  };

  const handleAccept = async () => {
    try {
      setProcessingId(currentInv.id);
      const res = await fetchWithAuth(`/api/v1/family/invitations/${currentInv.id}/accept`, {
        method: 'POST',
      });
      const data = await res.json();
      if (res.ok) {
        markIdsAsSeen([currentInv.id]);
        setModalOpen(false);

        // 如果用户结算币种被更换，弹窗提示用户确认
        if (data.currency_change?.changed) {
          setCurrencyChangeModal({
            open: true,
            data: {
              familyName: data.family?.name || currentInv.family_name,
              previous_currency: data.currency_change.previous_currency,
              new_currency: data.currency_change.new_currency,
            },
          });
        } else {
          showToast(tx(data.message || `已成功加入「${currentInv.family_name}」！`), 'success');
          setTimeout(() => {
            window.location.reload();
          }, 300);
        }
      } else {
        showToast(tx(data.detail || '加入失败，请稍后重试'), 'error');
      }
    } catch {
      showToast(tx("网络错误，请稍后重试"), 'error');
    } finally {
      setProcessingId(null);
    }
  };

  const handleReject = async () => {
    try {
      setProcessingId(currentInv.id);
      const res = await fetchWithAuth(`/api/v1/family/invitations/${currentInv.id}/reject`, {
        method: 'POST',
      });
      const data = await res.json();
      if (res.ok) {
        markIdsAsSeen([currentInv.id]);
        showToast(tx(data.message || '已婉言谢绝该邀请'), 'info');
        // 移出当前已处理的邀请
        const remaining = unseenInvitations.filter((inv) => inv.id !== currentInv.id);
        if (remaining.length > 0) {
          setUnseenInvitations(remaining);
        } else {
          setModalOpen(false);
        }
      } else {
        showToast(tx(data.detail || '处理失败'), 'error');
      }
    } catch {
      showToast(tx("网络错误，请稍后重试"), 'error');
    } finally {
      setProcessingId(null);
    }
  };

  if (!currencyChangeModal.open && (!modalOpen || unseenInvitations.length === 0)) {
    return null;
  }

  return (
    <>
      {modalOpen && unseenInvitations.length > 0 && currentInv && (
        <div
          data-testid="family-invitation-prompt-modal"
          className="fixed inset-0 z-50 overflow-y-auto flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs animate-in fade-in duration-200"
        >
      <div
        className="relative bg-white dark:bg-zinc-900 rounded-3xl shadow-2xl w-full max-w-md border border-zinc-200/90 dark:border-zinc-800 p-6 space-y-5 animate-in zoom-in-95 duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Top Header */}
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 rounded-2xl bg-gradient-to-tr from-blue-600 to-indigo-600 text-white flex items-center justify-center shrink-0 shadow-md shadow-blue-500/20">
              <Inbox className="w-6 h-6" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-100">{tx("收到家庭组入组邀请")}</h3>
                {unseenInvitations.length > 1 && (
                  <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300">{tx("共")} {unseenInvitations.length} {tx("份")}</span>
                )}
              </div>
              <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">{tx("来自好友或家庭成员的协作记账邀请")}</p>
            </div>
          </div>

          <button
            type="button"
            onClick={handleDismiss}
            title={tx("稍后处理（下次登录不再重复弹窗）")}
            className="p-1.5 rounded-xl text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Invitation Content Card */}
        <div className="p-4 rounded-2xl bg-gradient-to-br from-blue-50/80 to-indigo-50/50 dark:from-blue-950/30 dark:to-indigo-950/20 border border-blue-200/70 dark:border-blue-900/40 space-y-3">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <span className="text-[11px] font-medium text-blue-600 dark:text-blue-400 block">{tx("邀请加入的家庭组")}</span>
              <div className="text-base font-bold text-blue-950 dark:text-blue-100">
                {currentInv.family_name}
              </div>
            </div>
            <div className="text-right">
              <span className="inline-block px-2 py-0.5 rounded-lg text-xs font-semibold bg-white dark:bg-zinc-800 text-blue-700 dark:text-blue-300 border border-blue-100 dark:border-blue-900/60 shadow-2xs">
                {currentInv.members_count || 1} {tx("位成员 ·")} {currentInv.currency || 'CNY'}
              </span>
            </div>
          </div>

          <div className="text-xs text-zinc-600 dark:text-zinc-300 flex items-center gap-1.5 pt-1 border-t border-blue-100/80 dark:border-blue-900/30">
            <span className="font-semibold text-zinc-800 dark:text-zinc-200">{tx("邀请人：")}</span>
            <span>{currentInv.inviter_display_name || currentInv.inviter_username}</span>
          </div>

          {currentInv.message && (
            <div className="text-xs italic bg-white/70 dark:bg-zinc-850/60 p-2.5 rounded-xl text-zinc-700 dark:text-zinc-300 border border-blue-100/60 dark:border-blue-900/20">
              “{currentInv.message}”
            </div>
          )}

          <div className="text-[11px] leading-relaxed text-blue-800/80 dark:text-blue-300/80 flex items-start gap-1.5 pt-1">
            <Shield className="w-3.5 h-3.5 shrink-0 mt-0.5 text-blue-600 dark:text-blue-400" />
            <span>{tx("同意加入后，您现有的私有账户与流水将无损并入该家庭组共同记账，您可随时在账户中设置隐私共享权限。")}</span>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex flex-col sm:flex-row items-center gap-2 pt-1">
          <button
            type="button"
            disabled={processingId !== null}
            onClick={handleDismiss}
            className="w-full sm:flex-1 py-2.5 px-3 rounded-xl border border-zinc-200 dark:border-zinc-700 text-xs font-semibold text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
          >{tx("稍后处理")}</button>

          <button
            type="button"
            disabled={processingId !== null}
            onClick={handleReject}
            className="w-full sm:w-auto py-2.5 px-4 rounded-xl border border-zinc-200 dark:border-zinc-700 text-xs font-semibold text-rose-600 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/30 transition-colors"
          >{tx("婉拒")}</button>

          <button
            type="button"
            disabled={processingId !== null}
            onClick={handleAccept}
            className="w-full sm:flex-1 py-2.5 px-4 rounded-xl bg-blue-600 hover:bg-blue-700 text-white text-xs font-bold transition-all shadow-md shadow-blue-600/20 flex items-center justify-center gap-1.5 disabled:opacity-50"
          >
            <Check className="w-4 h-4" />
            <span>{processingId === currentInv.id ? tx("正在加入...") : tx("同意加入")}</span>
          </button>
        </div>
      </div>
    </div>
      )}

      {/* 结算币种对齐更换提示弹窗 */}
      <CurrencyChangeAlertModal
        isOpen={currencyChangeModal.open}
        data={currencyChangeModal.data}
        onClose={handleCurrencyModalClose}
      />
    </>
  );
}
