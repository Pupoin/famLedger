import { tx, useLocale } from "../localization.js";
import React, { useState, useEffect, useRef, useMemo } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Plus, ChevronRight, ChevronDown, X, Check, Users, Edit2, Search } from 'lucide-react';
import { fetchWithAuth } from '../api/fetchWithAuth';
import { Modal, Button } from './ds/DesignSystem';
import AccountSharingModal from './AccountSharingModal';
import { EditAccountModal } from './AccountModals';
import AccountSelectDropdown from './AccountSelectDropdown';
import AccountTypeSelectDropdown from './AccountTypeSelectDropdown';
import ExternalIdentifierField from './ExternalIdentifierField';
import { useCurrency } from '../CurrencyContext';
import { formatCurrency } from '../utils/currency';
const accountCurrencySymbols = {USD:'$', EUR:'€', GBP:'£', CAD:'C$', AUD:'A$', INR:'₹', JPY:'¥', CNY:'¥', CHF:'CHF', SGD:'S$', HKD:'HK$'};
import { useAuth } from '../auth/AuthContext';
import { renderAccountLogo, formatAccountDisplayName } from '../utils/accountIcons';

export const ACCOUNT_TYPES = [
  { code: 'cash', label: '现金', category: 'asset' },
  { code: 'iou', label: '借据', category: 'asset' },
  { code: 'investment', label: '投资', category: 'asset' },
  { code: 'crypto', label: '加密资产', category: 'asset' },
  { code: 'real_estate', label: '房产', category: 'asset' },
  { code: 'vehicle', label: '车辆', category: 'asset' },
  { code: 'other_asset', label: '其他资产', category: 'asset' },
  { code: 'credit_card', label: '信用卡', category: 'liability' },
  { code: 'loan', label: '贷款', category: 'liability' },
  { code: 'other_liability', label: '其他负债', category: 'liability' },
];




export const normalizeAccountType = (acc) => {
  if (!acc) return '现金';
  const type = String(acc.account_type || '').trim().toLowerCase();
  const name = String(acc.name || acc.account_name || '').toLowerCase();
  const classification = String(acc.classification || '').toLowerCase();

  // 1. 信用卡 (credit_card)
  if (
    ['信用卡', 'credit_card', 'credit', '贷记卡', '花呗', '白条'].includes(type) ||
    name.includes('信用卡') ||
    name.includes('花呗') ||
    name.includes('白条')
  ) {
    return '信用卡';
  }

  // 2. 贷款 (loan)
  if (
    ['贷款', 'loan', 'mortgage', '抵押贷款', '借款', '微粒贷', '借呗'].includes(type) ||
    name.includes('贷款') ||
    name.includes('房贷') ||
    name.includes('车贷') ||
    name.includes('借呗') ||
    name.includes('微粒贷')
  ) {
    return '贷款';
  }

  // 3. 其他负债 (other_liability)
  if (['其他负债', 'other_liability'].includes(type) || (classification === 'liability' && !['credit_card', 'loan'].includes(type))) {
    return '其他负债';
  }

  // 3.5 借据 (iou / receivable) - 别人向我借的钱 (资产)
  if (
    ['借据', 'iou', 'receivable', 'loan_receivable', '借出款', '借出', '借条', '欠条'].includes(type) ||
    name.includes('借据') ||
    name.includes('借出款') ||
    name.includes('借条') ||
    name.includes('欠条') ||
    name.includes('借给')
  ) {
    return '借据';
  }

  // 4. 加密资产 (crypto)
  if (
    ['加密资产', 'crypto', 'cryptocurrency', 'btc', 'eth', '数字货币', '加密'].includes(type) ||
    name.includes('加密') ||
    name.includes('数字货币') ||
    name.includes('btc') ||
    name.includes('eth')
  ) {
    return '加密资产';
  }

  // 5. 房产 (real_estate)
  if (
    ['房产', 'real_estate', 'property', 'house', '不动产', '房屋'].includes(type) ||
    name.includes('房产') ||
    name.includes('住宅') ||
    name.includes('公寓')
  ) {
    return '房产';
  }

  // 6. 车辆 (vehicle)
  if (
    ['车辆', 'vehicle', 'car', '汽车', '机动车'].includes(type) ||
    name.includes('车辆') ||
    name.includes('汽车') ||
    name.includes('私家车')
  ) {
    return '车辆';
  }

  // 7. 投资 (investment)
  if (
    ['投资', 'investment', 'brokerage', 'mutual_fund', 'stock', '证券', '理财', '基金', '股票'].includes(type) ||
    name.includes('理财') ||
    name.includes('证券') ||
    name.includes('基金') ||
    name.includes('股票') ||
    name.includes('投资')
  ) {
    return '投资';
  }

  // 8. 其他资产 (other_asset)
  if (['其他资产', 'other_asset'].includes(type)) {
    return '其他资产';
  }

  // 9. 现金 (cash / checking / savings)
  if (
    ['现金', 'cash', 'checking', 'savings', '活期', '借记卡', '储蓄', '储蓄卡'].includes(type) ||
    name.includes('借记卡') ||
    name.includes('活期') ||
    name.includes('储蓄') ||
    name.includes('现金')
  ) {
    return '现金';
  }

  return classification === 'liability' ? '其他负债' : '现金';
};

export const getAccountCategory = (typeLabel) => {
  if (['信用卡', '贷款', '其他负债'].includes(typeLabel)) return 'liability';
  return 'asset';
};

export const renderAccountIcon = (acc, isShared = false, hasSubAccounts = false) => {
  const isOutboundShared = acc?.is_owner && Number(acc?.shared_with_count || 0) > 0;
  const owner = String(acc?.owner_display_name || acc?.owner || '').trim();
  const ownerInitial = owner ? Array.from(owner)[0].toUpperCase() : '享';
  const isSubAccount = Boolean(acc?.parent_account_id);
  const isMaster = !isSubAccount && Boolean(hasSubAccounts || acc?.has_sub_accounts);

  return (
    <div className="relative shrink-0 flex items-center justify-center">
      {renderAccountLogo(acc, { className: 'w-[18px] h-[18px]' })}
      {/* 附属卡 / 子账户专属徽标：右上角深橙底 + 纯白字 */}
      {isSubAccount && (
        <span
          title={acc?.parent_account?.name
            ? tx("附属卡 · 所属主卡：{p0}（{p1}）", {p0: (acc.parent_account.name), p1: (acc.parent_account.owner || tx("未知用户"))})
            : tx("附属卡 / 子账户（消费并入主卡还款）")}
          className="absolute -top-0.5 -right-0.5 w-[10.5px] h-[10.5px] rounded-full bg-orange-600 text-white text-[7.5px] font-bold flex items-center justify-center ring-1.5 ring-white dark:ring-zinc-900 shadow-2xs leading-none select-none"
        >{tx("副")}</span>
      )}
      {/* 主卡 / 主账户专属徽标：右上角深蓝底 + 纯白字 */}
      {isMaster && (
        <span
          title={tx("主账户 / 主卡（下挂附属卡，统筹合并还款）")}
          className="absolute -top-0.5 -right-0.5 w-[10.5px] h-[10.5px] rounded-full bg-blue-600 text-white text-[7.5px] font-bold flex items-center justify-center ring-1.5 ring-white dark:ring-zinc-900 shadow-2xs leading-none select-none"
        >{tx("主")}</span>
      )}
      {/* 共享徽标：右下角 */}
      {isShared ? (
        <span
          title={tx("由 {p0} 共享", {p0: (owner || tx("家人"))})}
          className="absolute -bottom-0.5 -right-0.5 w-[10px] h-[10px] rounded-full bg-purple-600 text-white text-[7px] font-bold flex items-center justify-center ring-1.5 ring-white dark:ring-zinc-900 shadow-2xs leading-none select-none"
        >
          {ownerInitial}
        </span>
      ) : isOutboundShared ? (
        <span
          title={tx("已共享给 {p0} 位家庭成员", {p0: (acc.shared_with_count)})}
          className="absolute -bottom-0.5 -right-0.5 w-2 h-2 rounded-full bg-blue-600 ring-1.5 ring-white dark:ring-zinc-900 shadow-2xs"
        />
      ) : null}
    </div>
  );
};

/**
 * 智能渲染账户名称（保证后4位卡号/编号永不被截断，零占宽确保名称完整展开）
 * 附属卡/子账户字体稍微小一点点（text-[11px]），形成优雅的主次层级
 */
export const renderAccountDisplayName = (acc, isChild = false) => {
  const fullText = formatAccountDisplayName(acc);
  const match = fullText.match(/^(.*?)(\s+[*#\d\w]{3,6})$/);
  const nameSize = isChild ? 'text-xs' : 'text-[13px] font-medium';
  const maskSize = isChild ? 'text-[11px]' : 'text-xs';

  if (match) {
    return (
      <span className={`flex items-center min-w-0 max-w-full text-zinc-800 dark:text-zinc-200 ${nameSize}`} title={fullText}>
        <span className="truncate">{match[1]}</span>
        <span className={`shrink-0 font-mono text-zinc-500 dark:text-zinc-400 ml-1 ${maskSize}`}>{match[2].trim()}</span>
      </span>
    );
  }
  return (
    <span className={`truncate text-zinc-800 dark:text-zinc-200 ${nameSize}`} title={fullText}>
      {fullText}
    </span>
  );
};

/**
 * 将账户列表按“主账户 -> 附属卡紧随其后”排序组织，返回带有 isChildInTree 属性的列表
 */
export const organizeAccountsWithSubAccounts = (accList) => {
  if (!accList || accList.length === 0) return [];
  const idMap = new Map();
  accList.forEach((a) => idMap.set(a.id, a));

  const result = [];
  const visited = new Set();

  // 1. 遍历所有独立主账户（parent_account_id 为空，或者其父账户不在当前列表分组中）
  accList.forEach((acc) => {
    const parentInList = acc.parent_account_id && idMap.has(acc.parent_account_id);
    if (!parentInList) {
      // 主卡不在当前分组时平级显示，不能用缩进暗示属于前一张无关账户。
      result.push({ ...acc, isChildInTree: false });
      visited.add(acc.id);

      // 紧接着找出所有挂在它下面的附属卡
      accList.forEach((child) => {
        if (child.parent_account_id === acc.id) {
          result.push({ ...child, isChildInTree: true });
          visited.add(child.id);
        }
      });
    }
  });

  // 2. 兜底未包含的（防止意外遗漏）
  accList.forEach((acc) => {
    if (!visited.has(acc.id)) {
      result.push({ ...acc, isChildInTree: false });
    }
  });

  return result;
};


export default function AccountsPanel({
  selectedAccountId,
  onSelectAccount,
  onClose,
  isMobileDrawer = false,
}) {
  useLocale();
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useTranslation();
  const { user } = useAuth();
  const { privacyMode, currency: prefCurrency, currencies, symbol } = useCurrency();

  const [accounts, setAccounts] = useState([]);
  const [accountsError, setAccountsError] = useState("");
  const fmt = (value) => privacyMode ? "••••" : formatCurrency(value, accountCurrencySymbols[accounts[0]?.report_currency] || symbol);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('all'); // 'all' | 'asset' | 'liability'
  const [accountSearch, setAccountSearch] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [sharingModalAccountId, setSharingModalAccountId] = useState(null);

  const isAccountShared = (acc) => {
    if (!acc) return false;
    if (acc.is_owner === false) return true;
    if (acc.owner && user?.username && acc.owner.toLowerCase() !== user.username.toLowerCase()) return true;
    return false;
  };

  // 跨用户同名账户消歧集合
  const duplicateNameSet = useMemo(() => {
    const counts = {};
    accounts.forEach((a) => {
      const name = (a.name || a.account_name || '').trim().toLowerCase();
      if (name) counts[name] = (counts[name] || 0) + 1;
    });
    const dupes = new Set();
    Object.entries(counts).forEach(([name, count]) => {
      if (count > 1) dupes.add(name);
    });
    return dupes;
  }, [accounts]);

  // 计算拥有下属副卡/子账户的主账户集合
  const masterAccountIdSet = useMemo(() => {
    return new Set(accounts.filter((a) => a.parent_account_id).map((a) => a.parent_account_id));
  }, [accounts]);

  // 新建账户时可选的主账户候选集（仅限信用卡主卡，区分我的账户与家人共享账户）
  const parentCandidates = useMemo(() => {
    return accounts.filter((a) => !a.parent_account_id && (a.account_type === 'credit_card' || a.classification === 'liability'));
  }, [accounts]);
  const myParentCandidates = useMemo(() => {
    return parentCandidates.filter((a) => a.is_owner !== false);
  }, [parentCandidates]);
  const sharedParentCandidates = useMemo(() => {
    return parentCandidates.filter((a) => a.is_owner === false);
  }, [parentCandidates]);

  // Group By mode: 'owner_by_institution' | 'owner_by_type' | 'by_type' | 'by_institution' | 'by_owner'
  const [groupBy, setGroupBy] = useState(() => {
    return localStorage.getItem('famledger_account_group_by') || 'owner_by_institution';
  });
  const [showGroupMenu, setShowGroupMenu] = useState(false);
  const [showUserSubmenu, setShowUserSubmenu] = useState(() => {
    const cur = localStorage.getItem('famledger_account_group_by') || 'owner_by_institution';
    return cur === 'owner_by_institution' || cur === 'owner_by_type' || cur === 'by_owner';
  });
  const [editingAccount, setEditingAccount] = useState(null);
  const groupMenuRef = useRef(null);

  // Expanded state map for group nodes: { [groupId]: boolean }
  const [expandedGroups, setExpandedGroups] = useState({
    'group-0': true,
    'group-1': true,
    'group-2': true,
    'group-3': true,
  });

  const toggleGroup = (id) => {
    setExpandedGroups((prev) => ({
      ...prev,
      [id]: prev[id] === undefined ? false : !prev[id],
    }));
  };

  // Close group menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (groupMenuRef.current && !groupMenuRef.current.contains(e.target)) {
        setShowGroupMenu(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const isOwnerMode =
    groupBy === 'owner_by_institution' || groupBy === 'owner_by_type' || groupBy === 'by_owner';

  const currentGroupLabel = {
    by_type: '分组：账户类型',
    by_institution: '分组：金融机构',
    owner_by_type: '分组：用户 › 账户类型',
    owner_by_institution: '分组：用户 › 金融机构',
  }[groupBy] || '分组：用户';

  // 判断是否需要在当前视图显式渲染所属人徽标（非所属人视图，或发生同名冲突时智能消歧）
  const shouldShowOwnerBadge = (acc) => {
    if (!isAccountShared(acc)) return false;
    if (!isOwnerMode) return true;
    const name = (acc.name || acc.account_name || '').trim().toLowerCase();
    return duplicateNameSet.has(name);
  };

  // New account form
  const [form, setForm] = useState({
    name: '',
    institution_name: '',
    external_identifier: '',
    account_type: 'checking',
    currency: prefCurrency || 'CNY',
    balance: '0',
    parent_account_id: '',
  });

  const fetchAccounts = async () => {
    try {
      setLoading(true);
      setAccountsError("");
      const res = await fetchWithAuth('/api/v1/accounts');
      if (!res.ok) {
        const error = await res.json().catch(() => ({}));
        throw new Error(typeof error.detail === "string" ? error.detail : "账户加载失败");
      }
      if (res.ok) {
        const data = await res.json();
        const list = Array.isArray(data)
          ? data
          : data.accounts || data.items || [];
        setAccounts(list);
      }
    } catch (err) {
      setAccountsError(err.message);
      console.error('Failed to load accounts in SureAccountsPanel', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAccounts();

    let debounceTimer = null;
    const triggerRefresh = () => {
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        fetchAccounts();
      }, 50);
    };

    const handleAccountsUpdated = (e) => {
      if (e?.detail?.deletedAccountId) {
        setAccounts((prev) => prev.filter((a) => a.id !== e.detail.deletedAccountId));
      }
      if (typeof e?.detail?.hiddenInSidebar === 'boolean') {
        setAccounts((prev) => prev.map((account) => account.id === e.detail.accountId
          ? { ...account, hidden_in_sidebar: e.detail.hiddenInSidebar } : account));
      }
      triggerRefresh();
    };

    // 监听所有账户和交易生命周期事件，任何变动毫秒级实时刷新侧边栏余额
    window.addEventListener('accounts-updated', handleAccountsUpdated);
    window.addEventListener('transaction-added', triggerRefresh);
    window.addEventListener('transaction-updated', triggerRefresh);
    window.addEventListener('transaction-deleted', triggerRefresh);

    return () => {
      if (debounceTimer) clearTimeout(debounceTimer);
      window.removeEventListener('accounts-updated', handleAccountsUpdated);
      window.removeEventListener('transaction-added', triggerRefresh);
      window.removeEventListener('transaction-updated', triggerRefresh);
      window.removeEventListener('transaction-deleted', triggerRefresh);
    };
  }, []);

  const handleCreateAccount = async (e) => {
    e.preventDefault();
    try {
      const finalName = form.name.trim();
      const finalInst = form.institution_name.trim();

      const res = await fetchWithAuth('/api/v1/accounts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: finalName,
          institution_name: finalInst,
          external_identifier: form.external_identifier.trim() || null,
          account_type: form.account_type,
          currency: form.currency || prefCurrency || 'CNY',
          balance: Number(form.balance) || 0,
          parent_account_id: form.parent_account_id ? form.parent_account_id.trim() : undefined,
        }),
      });
      if (res.ok) {
        setModalOpen(false);
        fetchAccounts();
      }
    } catch (err) {
      console.error('Failed to create account', err);
    }
  };

  const [actionSheetAccount, setActionSheetAccount] = useState(null);
  const touchTimerRef = useRef(null);
  const touchStartPosRef = useRef({ x: 0, y: 0 });
  const isLongPressRef = useRef(false);

  useEffect(() => {
    return () => {
      if (touchTimerRef.current) {
        clearTimeout(touchTimerRef.current);
      }
    };
  }, []);

  const handleTouchStart = (acc, e) => {
    if (!isMobileDrawer && typeof window !== 'undefined' && window.innerWidth >= 1024) return;
    const touch = e.touches ? e.touches[0] : e;
    touchStartPosRef.current = { x: touch.clientX, y: touch.clientY };
    isLongPressRef.current = false;
    if (touchTimerRef.current) clearTimeout(touchTimerRef.current);
    touchTimerRef.current = setTimeout(() => {
      isLongPressRef.current = true;
      if (typeof navigator !== 'undefined' && navigator.vibrate) {
        try {
          navigator.vibrate(25);
        } catch (_) {}
      }
      setActionSheetAccount(acc);
    }, 450);
  };

  const handleTouchMove = (e) => {
    if (!touchTimerRef.current) return;
    const touch = e.touches ? e.touches[0] : e;
    const dx = Math.abs(touch.clientX - touchStartPosRef.current.x);
    const dy = Math.abs(touch.clientY - touchStartPosRef.current.y);
    if (dx > 8 || dy > 8) {
      clearTimeout(touchTimerRef.current);
      touchTimerRef.current = null;
    }
  };

  const handleTouchEnd = () => {
    if (touchTimerRef.current) {
      clearTimeout(touchTimerRef.current);
      touchTimerRef.current = null;
    }
  };

  const handleAccountClick = (acc) => {
    if (isLongPressRef.current) {
      isLongPressRef.current = false;
      return;
    }
    if (onSelectAccount) {
      onSelectAccount(acc);
    } else {
      navigate(acc ? `/accounts/${acc.id}` : '/transactions');
    }
    if (isMobileDrawer && onClose) {
      onClose();
    }
  };

  // Search only the accounts already available to this user and visible in the sidebar.
  const filteredAccounts = useMemo(() => {
    const query = accountSearch.trim().toLocaleLowerCase();
    return accounts.filter((account) => {
      if (account.hidden_in_sidebar) return false;
      if (activeTab !== 'all' && (account.classification || getAccountCategory(normalizeAccountType(account))) !== activeTab) return false;
      if (!query) return true;
      return [account.name, account.account_name, account.institution_name, account.external_identifier,
              account.owner, account.owner_username, account.owner_display_name]
        .some(value => String(value || '').toLocaleLowerCase().includes(query));
    });
  }, [accounts, activeTab, accountSearch]);

  // Compute Hierarchical Tree based on groupBy
  const groupedTree = useMemo(() => {
    const defaultOwner = user?.displayName || user?.username || '当前用户';

    const groupBalance = (a) => Number(a.report_own_balance ?? a.report_balance ?? a.balance ?? 0);

    if (groupBy === 'owner_by_institution') {
      // Group by Owner -> Institution
      const groups = {};
      filteredAccounts.forEach((acc) => {
        const owner = acc.owner || defaultOwner;
        if (!groups[owner]) {
          groups[owner] = {
            id: `owner-${owner}`,
            title: owner,
            type: 'owner',
            subgroups: {},
            total: 0,
            changePercent: 0.0,
          };
        }
        const inst = acc.institution_name || tx('其他机构');
        if (!groups[owner].subgroups[inst]) {
          groups[owner].subgroups[inst] = {
            id: `inst-${owner}-${inst}`,
            title: inst,
            accounts: [],
            total: 0,
            changePercent: 0.0,
          };
        }
        groups[owner].subgroups[inst].accounts.push(acc);
        const bal = groupBalance(acc);
        const isLiab = acc.classification === 'liability';
        const netBal = activeTab === 'all' && isLiab ? -bal : bal;
        // 按可见账户自身余额计算，主副卡各累计一次。
        {
          groups[owner].subgroups[inst].total += netBal;
          groups[owner].total += netBal;
        }
      });

      return Object.values(groups).map((g) => ({
        ...g,
        subgroups: Object.values(g.subgroups),
      }));
    }

    if (groupBy === 'owner_by_type') {
      // Group by Owner -> 9 Account Types
      const groups = {};
      filteredAccounts.forEach((acc) => {
        const owner = acc.owner || defaultOwner;
        if (!groups[owner]) {
          groups[owner] = {
            id: `owner-${owner}`,
            title: owner,
            type: 'owner',
            subgroups: {},
            total: 0,
            changePercent: 0.0,
          };
        }
        const typeLabel = normalizeAccountType(acc);
        if (!groups[owner].subgroups[typeLabel]) {
          groups[owner].subgroups[typeLabel] = {
            id: `type-${owner}-${typeLabel}`,
            title: typeLabel,
            accounts: [],
            total: 0,
            changePercent: 0.0,
          };
        }
        groups[owner].subgroups[typeLabel].accounts.push(acc);
        const bal = groupBalance(acc);
        const isLiab = acc.classification === 'liability';
        const netBal = activeTab === 'all' && isLiab ? -bal : bal;
        // 按可见账户自身余额计算，主副卡各累计一次。
        {
          groups[owner].subgroups[typeLabel].total += netBal;
          groups[owner].total += netBal;
        }
      });

      return Object.values(groups).map((g) => ({
        ...g,
        subgroups: Object.values(g.subgroups),
      }));
    }

    if (groupBy === 'by_type') {
      // Group by 9 official account types
      const groups = {};
      const typeOrder =
        activeTab === 'asset'
          ? ['现金', '借据', '投资', '加密资产', '房产', '车辆', '其他资产']
          : activeTab === 'liability'
          ? ['信用卡', '贷款', '其他负债']
          : ['现金', '借据', '投资', '加密资产', '房产', '车辆', '其他资产', '信用卡', '贷款', '其他负债'];

      typeOrder.forEach((t) => {
        groups[t] = {
          id: `type-${t}`,
          title: t,
          accounts: [],
          total: 0,
          changePercent: 0.0,
        };
      });

      filteredAccounts.forEach((acc) => {
        const typeLabel = normalizeAccountType(acc);
        if (!groups[typeLabel]) {
          groups[typeLabel] = {
            id: `type-${typeLabel}`,
            title: typeLabel,
            accounts: [],
            total: 0,
            changePercent: 0.0,
          };
        }
        groups[typeLabel].accounts.push(acc);
        // 按可见账户自身余额计算，主副卡各累计一次。
        {
          groups[typeLabel].total += (activeTab === 'all' && acc.classification === 'liability' ? -1 : 1) * groupBalance(acc);
        }
      });

      return Object.values(groups).filter((g) => g.accounts.length > 0);
    }

    if (groupBy === 'by_institution') {
      // Group by institution_name
      const groups = {};
      filteredAccounts.forEach((acc) => {
        const inst = acc.institution_name || tx('其他机构');
        if (!groups[inst]) {
          groups[inst] = {
            id: `inst-${inst}`,
            title: inst,
            accounts: [],
            total: 0,
            changePercent: 0.0,
          };
        }
        groups[inst].accounts.push(acc);
        // 按可见账户自身余额计算，主副卡各累计一次。
        {
          groups[inst].total += (activeTab === 'all' && acc.classification === 'liability' ? -1 : 1) * groupBalance(acc);
        }
      });
      return Object.values(groups);
    }

    // Default: by_owner
    const groups = {};
    filteredAccounts.forEach((acc) => {
      const owner = acc.owner || defaultOwner;
      if (!groups[owner]) {
        groups[owner] = {
          id: `owner-${owner}`,
          title: owner,
          accounts: [],
          total: 0,
          changePercent: 0.0,
        };
      }
      groups[owner].accounts.push(acc);
      // 按可见账户自身余额计算，主副卡各累计一次。
      {
        groups[owner].total += (activeTab === 'all' && acc.classification === 'liability' ? -1 : 1) * groupBalance(acc);
      }
    });
    return Object.values(groups);
  }, [filteredAccounts, groupBy, user, activeTab]);

  return (
    <div className="flex flex-col h-full bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 select-none border-r border-zinc-200/80 dark:border-zinc-800">
      {accountsError && <p role="alert" className="p-3 text-xs text-red-600">{tx(accountsError)}</p>}
      <div data-testid="accounts-panel-header" className="shrink-0 px-3 pt-4 pb-3 space-y-3 border-b border-zinc-100 dark:border-zinc-800">
        {/* Title and primary action share the first row. */}
        <div className="flex items-center gap-2">
          <h2 className="flex-1 text-lg font-bold text-zinc-900 dark:text-zinc-100">
            {t('accounts.title', tx("账户"))}
          </h2>
          <button
            type="button"
            data-testid="sidebar-add-account-btn"
            onClick={() => {
              setForm({
                name: '',
                institution_name: '',
                external_identifier: '',
                account_type: activeTab === 'liability' ? 'credit_card' : 'cash',
                currency: prefCurrency || 'CNY',
                balance: '0',
                parent_account_id: '',
              });
              setModalOpen(true);
            }}
            className="shrink-0 inline-flex items-center justify-center gap-1.5 h-9 px-3 rounded-lg bg-blue-600 hover:bg-blue-700 dark:bg-blue-500 dark:hover:bg-blue-600 text-white text-xs font-semibold shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-zinc-900"
          >
            <Plus className="w-4 h-4" aria-hidden="true" />
            <span>{tx("添加账户")}</span>
          </button>
          {isMobileDrawer && (
            <button
              type="button"
              onClick={onClose}
              className="p-1.5 rounded-lg text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors shrink-0"
              aria-label={tx("关闭侧栏")}
              title={tx("关闭侧栏")}
            >
              <X className="w-4 h-4" aria-hidden="true" />
            </button>
          )}
        </div>

        {/* Display scope is separate from the grouping of the list. */}
        <div role="group" aria-label={tx("账户范围")} className="flex items-center p-1 bg-zinc-100 dark:bg-zinc-800 rounded-xl">
            {[
              { id: 'all', label: t('accounts.all', tx("全部")) },
              { id: 'asset', label: t('accounts.assets', tx("资产")) },
              { id: 'liability', label: t('accounts.debts', tx("负债")) },
            ].map((tItem) => (
              <button
                type="button"
                key={tItem.id}
                data-testid={`account-scope-${tItem.id}`}
                aria-pressed={activeTab === tItem.id}
                onClick={() => setActiveTab(tItem.id)}
                className={`flex-1 min-w-0 py-2 text-[13px] font-semibold rounded-lg text-center transition-colors ${
                  activeTab === tItem.id
                    ? 'bg-blue-600 dark:bg-blue-500 text-white shadow-sm'
                    : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
                }`}
              >
                {tx(tItem.label)}
              </button>
            ))}
        </div>

        <div className="relative flex flex-wrap items-center gap-2">
          <div className="relative min-w-[104px] flex-[1_1_104px]">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-zinc-400 pointer-events-none" aria-hidden="true" />
            <input
              type="text"
              role="searchbox"
              data-testid="account-search-input"
              aria-label={tx("搜索账户或用户")}
              placeholder={tx("账户/用户…")}
              value={accountSearch}
              autoComplete="off"
              spellCheck={false}
              onChange={(event) => setAccountSearch(event.target.value)}
              onKeyDown={(event) => { if (event.key === 'Escape') setAccountSearch(''); }}
              className={`w-full h-9 pl-8 ${accountSearch ? 'pr-7' : 'pr-2'} rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-xs text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500`}
            />
            {accountSearch && (
              <button
                type="button"
                data-testid="account-search-clear-btn"
                onClick={() => setAccountSearch('')}
                aria-label={tx("清除搜索")}
                className="absolute right-1 top-1/2 -translate-y-1/2 p-1 rounded-md text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200"
              >
                <X className="w-3 h-3" aria-hidden="true" />
              </button>
            )}
          </div>

          <div className="max-w-full" ref={groupMenuRef}>
            <button
              type="button"
              data-testid="account-groupby-btn"
              aria-expanded={showGroupMenu}
              onClick={() => {
                setShowGroupMenu(!showGroupMenu);
                if (isOwnerMode) setShowUserSubmenu(true);
              }}
              className="min-h-9 text-[12px] font-medium text-zinc-600 hover:text-zinc-900 dark:text-zinc-300 dark:hover:text-white flex items-center gap-1.5 transition-colors px-2 py-2 rounded-lg bg-zinc-100 hover:bg-zinc-200/70 dark:bg-zinc-800 dark:hover:bg-zinc-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            >
              <span>{tx(currentGroupLabel)}</span>
              <ChevronDown className={`w-3.5 h-3.5 shrink-0 transition-transform ${showGroupMenu ? 'rotate-180' : ''}`} aria-hidden="true" />
            </button>

            {/* Popup Dropdown Menu (按账户类型 / 按金融机构 / 按用户 -> 用户-金融机构 / 用户-账户类型) */}
            {showGroupMenu && (
              <div className="absolute right-0 top-full mt-1.5 w-52 bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl shadow-xl py-1 z-50 animate-in fade-in zoom-in-95 duration-100">
                <div className="px-3 py-1.5 text-[11px] font-semibold text-zinc-400 uppercase tracking-wider">
                  {t('accounts.groupBy', tx("账户分组模式"))}
                </div>

                {/* 1. 按账户类型 */}
                <button
                  type="button"
                  data-testid="groupby-option-type"
                  onClick={() => {
                    setGroupBy('by_type');
                    localStorage.setItem('famledger_account_group_by', 'by_type');
                    setShowGroupMenu(false);
                  }}
                  className={`w-full flex items-center justify-between px-3 py-2 text-xs transition-colors ${
                    groupBy === 'by_type'
                      ? 'bg-zinc-50 dark:bg-zinc-700/60 font-semibold text-zinc-900 dark:text-white'
                      : 'text-zinc-600 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-700/40'
                  }`}
                >
                  <span>{tx("按账户类型")}</span>
                  {groupBy === 'by_type' && <Check className="w-3.5 h-3.5 text-zinc-900 dark:text-white" />}
                </button>

                {/* 2. 按金融机构 */}
                <button
                  type="button"
                  data-testid="groupby-option-institution"
                  onClick={() => {
                    setGroupBy('by_institution');
                    localStorage.setItem('famledger_account_group_by', 'by_institution');
                    setShowGroupMenu(false);
                  }}
                  className={`w-full flex items-center justify-between px-3 py-2 text-xs transition-colors ${
                    groupBy === 'by_institution'
                      ? 'bg-zinc-50 dark:bg-zinc-700/60 font-semibold text-zinc-900 dark:text-white'
                      : 'text-zinc-600 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-700/40'
                  }`}
                >
                  <span>{tx("按金融机构")}</span>
                  {groupBy === 'by_institution' && <Check className="w-3.5 h-3.5 text-zinc-900 dark:text-white" />}
                </button>

                {/* 3. 按用户 (带展开子项: 用户-金融机构 / 用户-账户类型) */}
                <div className="border-t border-zinc-100 dark:border-zinc-700/60 mt-1 pt-1">
                  <button
                    type="button"
                    data-testid="group-by-user-main"
                    onClick={() => {
                      if (!isOwnerMode) {
                        setGroupBy('owner_by_institution');
                        localStorage.setItem('famledger_account_group_by', 'owner_by_institution');
                      }
                      setShowUserSubmenu(true);
                    }}
                    className={`w-full flex items-center justify-between px-3 py-2 text-xs transition-colors ${
                      isOwnerMode
                        ? 'bg-zinc-50 dark:bg-zinc-700/60 font-semibold text-zinc-900 dark:text-white'
                        : 'text-zinc-600 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-700/40'
                    }`}
                  >
                    <span className="flex items-center gap-1.5">
                      <span>{tx("按用户")}</span>
                    </span>
                    <ChevronRight className={`w-3.5 h-3.5 text-zinc-400 transition-transform ${showUserSubmenu ? 'rotate-90' : ''}`} />
                  </button>

                  {/* 点击按用户之后显示二级子项 */}
                  {showUserSubmenu && (
                    <div className="pl-3 pr-1 py-1 space-y-0.5 bg-zinc-50/50 dark:bg-zinc-900/30">
                      <button
                        type="button"
                        data-testid="group-user-institution"
                        onClick={() => {
                          setGroupBy('owner_by_institution');
                          localStorage.setItem('famledger_account_group_by', 'owner_by_institution');
                          setShowGroupMenu(false);
                        }}
                        className={`w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg text-xs transition-colors cursor-pointer ${
                          groupBy === 'owner_by_institution'
                            ? 'font-semibold text-zinc-900 dark:text-white bg-zinc-100 dark:bg-zinc-700'
                            : 'text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 hover:bg-zinc-100/50'
                        }`}
                      >
                        <span>{tx("用户 - 金融机构")}</span>
                        {groupBy === 'owner_by_institution' && <Check className="w-3 h-3 text-zinc-900 dark:text-white" />}
                      </button>

                      <button
                        type="button"
                        data-testid="group-user-type"
                        onClick={() => {
                          setGroupBy('owner_by_type');
                          localStorage.setItem('famledger_account_group_by', 'owner_by_type');
                          setShowGroupMenu(false);
                        }}
                        className={`w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg text-xs transition-colors cursor-pointer ${
                          groupBy === 'owner_by_type'
                            ? 'font-semibold text-zinc-900 dark:text-white bg-zinc-100 dark:bg-zinc-700'
                            : 'text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 hover:bg-zinc-100/50'
                        }`}
                      >
                        <span>{tx("用户 - 账户类型")}</span>
                        {groupBy === 'owner_by_type' && <Check className="w-3 h-3 text-zinc-900 dark:text-white" />}
                      </button>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── 3. Accounts Hierarchy List (Exact Sure Style from 1.png) ── */}
      <div className={`flex-1 overflow-y-auto px-2 pt-1 ${isMobileDrawer ? 'pb-8' : 'pb-6'} space-y-2 custom-scrollbar overscroll-contain`}>
        {!loading && !accountsError && accountSearch.trim() && filteredAccounts.length === 0 && (
          <p role="status" className="px-3 py-6 text-center text-xs text-zinc-500 dark:text-zinc-400">
            {tx("没有匹配的账户")}
          </p>
        )}
        {/* Dynamic Hierarchical Tree Rendering */}
        {groupedTree.map((group, gIdx) => {
          const isExpanded = expandedGroups[group.id] !== false;

          return (
            <div key={group.id} className="space-y-1">
              {/* Level 1 Group Header */}
              <div
                onClick={() => toggleGroup(group.id)}
                className="flex items-center justify-between px-3 py-1.5 text-zinc-700 dark:text-zinc-300 hover:text-zinc-900 dark:hover:text-zinc-100 cursor-pointer rounded-lg hover:bg-zinc-50 dark:hover:bg-zinc-800/40"
              >
                <div className="flex items-center gap-1.5 min-w-0">
                  {isExpanded ? (
                    <ChevronDown className="w-3.5 h-3.5 shrink-0 text-zinc-400" />
                  ) : (
                    <ChevronRight className="w-3.5 h-3.5 shrink-0 text-zinc-400" />
                  )}
                  <span className="text-[14.5px] font-semibold text-zinc-900 dark:text-zinc-100 truncate">
                    {groupBy === 'by_type' ? tx(group.title) : group.title}
                  </span>
                  {isOwnerMode && (() => {
                    const isMe =
                      user?.username &&
                      (group.title.toLowerCase() === user.username.toLowerCase() ||
                        group.title === '我的' ||
                        group.title === user.displayName);
                    return isMe ? (
                      <span className="px-1.5 py-0.5 rounded text-[11px] font-semibold bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 shrink-0">{tx("本人")}</span>
                    ) : (
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] font-semibold bg-purple-50 dark:bg-purple-950/60 text-purple-600 dark:text-purple-400 border border-purple-200/60 dark:border-purple-800/60 shrink-0">
                        <Users className="w-2.5 h-2.5" /> {tx("家人共享")}</span>
                    );
                  })()}
                </div>

                <div className="flex flex-col items-end shrink-0 pl-2">
                  <span className="font-mono font-semibold text-zinc-900 dark:text-zinc-100 text-[14.5px]">
                    {fmt(group.total)}
                  </span>
                  {group.changePercent !== undefined && (
                    <span
                      className={`text-[11px] font-mono leading-none ${
                        group.changePercent < 0
                          ? 'text-emerald-600 dark:text-emerald-400'
                          : group.changePercent > 0
                          ? 'text-rose-600 dark:text-rose-400'
                          : 'text-zinc-400'
                      }`}
                    >
                      {group.changePercent > 0 ? `+${group.changePercent}%` : `${group.changePercent}%`}
                    </span>
                  )}
                </div>
              </div>

              {/* Level 1 Expanded Content */}
              {isExpanded && (
                <div className="space-y-0.5 pl-3">
                  {/* If has subgroups (e.g. owner_by_institution) */}
                  {group.subgroups ? (
                    group.subgroups.map((sub) => {
                      const isSubExpanded = expandedGroups[sub.id] !== false;
                      return (
                        <div key={sub.id} className="space-y-0.5">
                          {/* Subgroup Header */}
                          <div
                            onClick={() => toggleGroup(sub.id)}
                            className="flex items-center justify-between px-2.5 py-1.5 text-sm font-medium text-zinc-700 dark:text-zinc-300 hover:text-zinc-900 dark:hover:text-zinc-100 cursor-pointer rounded-lg hover:bg-zinc-50 dark:hover:bg-zinc-800/30"
                          >
                            <div className="flex items-center gap-1.5 min-w-0">
                              {sub.accounts && sub.accounts.length > 0 ? (
                                isSubExpanded ? (
                                  <ChevronDown className="w-3.5 h-3.5 shrink-0 text-zinc-400" />
                                ) : (
                                  <ChevronRight className="w-3.5 h-3.5 shrink-0 text-zinc-400" />
                                )
                              ) : (
                                <span className="w-3.5" />
                              )}
                              <span className="truncate font-bold text-[14.5px] text-zinc-850 dark:text-zinc-150" title={groupBy === 'owner_by_type' ? tx(sub.title) : sub.title}>{groupBy === 'owner_by_type' ? tx(sub.title) : sub.title}</span>
                            </div>

                            <div className="flex flex-col items-end shrink-0 pl-2">
                              <span className="font-mono text-zinc-900 dark:text-zinc-100 text-[14.5px] font-bold">
                                {fmt(sub.total)}
                              </span>
                              {sub.changePercent !== undefined && (
                                <span
                                  className={`text-[11px] font-mono leading-none ${
                                    sub.changePercent < 0
                                      ? 'text-emerald-600 dark:text-emerald-400'
                                      : 'text-zinc-400'
                                  }`}
                                >
                                  {sub.changePercent}%
                                </span>
                              )}
                            </div>
                          </div>

                          {/* Subgroup Accounts */}
                          {isSubExpanded && sub.accounts && (
                            <div className="space-y-0.5 pl-3">
                              {organizeAccountsWithSubAccounts(sub.accounts).map((acc) => {
                                const isCurrent =
                                  selectedAccountId === acc.id ||
                                  location.pathname === `/accounts/${acc.id}` ||
                                  location.search.includes("account_id={p0}");

                                return (
                                  <div
                                    key={acc.id}
                                    data-testid="account-item-link"
                                    data-account-id={acc.id}
                                    onClick={() => handleAccountClick(acc)}
                                    onTouchStart={(e) => handleTouchStart(acc, e)}
                                    onTouchMove={handleTouchMove}
                                    onTouchEnd={handleTouchEnd}
                                    onTouchCancel={handleTouchEnd}
                                    onContextMenu={(e) => {
                                      if (isMobileDrawer) e.preventDefault();
                                    }}
                                    title={acc.name || `*${acc.mask}`}
                                    className={`group flex items-center justify-between py-1.5 rounded-lg cursor-pointer transition-colors duration-150 text-xs select-none touch-manipulation ${
                                      acc.isChildInTree
                                        ? 'ml-2.5 pl-1.5 pr-2 border-l border-amber-300 dark:border-amber-600/50 bg-amber-50/20 dark:bg-amber-950/10'
                                        : 'px-2'
                                    } ${
                                      isCurrent
                                        ? 'bg-zinc-100 dark:bg-zinc-800 font-semibold'
                                        : 'hover:bg-zinc-50 dark:hover:bg-zinc-800/50'
                                    }`}
                                  >
                                    <div className="flex items-center gap-1.5 min-w-0 pr-1 flex-1">
                                      {acc.isChildInTree && (
                                        <span className="text-amber-500/80 dark:text-amber-400 font-mono text-[10px] select-none shrink-0 -mr-0.5" title={tx("附属卡 / 子账户")}>
                                          ↳
                                        </span>
                                      )}
                                      {renderAccountIcon(acc, isAccountShared(acc), masterAccountIdSet.has(acc.id) || Boolean(acc.has_sub_accounts))}
                                      {renderAccountDisplayName(acc, acc.isChildInTree)}
                                    </div>
                                    <div className="flex items-center gap-1 shrink-0">
                                      {!isMobileDrawer && (
                                        <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity duration-150">
                                          {acc.can_manage === true && (
                                            <button
                                              type="button"
                                              title={tx("编辑账户信息")}
                                              data-testid="edit-account-panel-btn"
                                              onClick={(e) => {
                                                e.stopPropagation();
                                                setEditingAccount(acc);
                                              }}
                                              className="p-1 rounded-md text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-700 transition-colors"
                                            >
                                              <Edit2 className="w-3 h-3" />
                                            </button>
                                          )}
                                          <button
                                            type="button"
                                            title={tx("配置共享权限")}
                                            onClick={(e) => {
                                              e.stopPropagation();
                                              setSharingModalAccountId(acc.id);
                                            }}
                                            className="p-1 rounded-md text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-700 transition-colors"
                                          >
                                            <Users className="w-3 h-3" />
                                          </button>
                                        </div>
                                      )}
                                      {(() => {
                                        const isSubCard = Boolean(acc.parent_account_id) || acc.isChildInTree;
                                        if (acc.classification === 'liability' && Number(acc.balance) < 0) {
                                          return (
                                            <div className="flex items-center gap-1" title={isSubCard ? tx("附属卡溢缴款（已合并入主卡统筹）") : tx("账户溢缴款")}>
                                              <span className={`rounded font-semibold bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800 leading-none ${acc.isChildInTree ? 'text-[10px] px-1 py-0.5' : 'text-[11px] px-1.5 py-0.5'}`}>{tx("溢")}</span>
                                              <span className={`font-mono text-emerald-600 dark:text-emerald-400 text-right font-medium ${acc.isChildInTree ? 'text-xs' : 'text-[13px]'}`}>
                                                {privacyMode ? "••••" : formatCurrency(acc.balance || 0, accountCurrencySymbols[acc.currency] || acc.currency)}
                                              </span>
                                            </div>
                                          );
                                        }
                                        if (isSubCard) {
                                          return (
                                            <div className="flex items-center gap-0.5" title={tx("附属卡/子账户金额（已合并入主账户统筹）")}>
                                              <span className="font-mono text-right text-xs text-zinc-500 dark:text-zinc-400">
                                                {privacyMode ? "••••" : formatCurrency(acc.balance || 0, accountCurrencySymbols[acc.currency] || acc.currency)}
                                              </span>
                                            </div>
                                          );
                                        }
                                        return (
                                          <span className="font-mono text-right text-[13px] text-zinc-700 dark:text-zinc-300 font-medium">
                                            {privacyMode ? "••••" : formatCurrency(acc.balance || 0, accountCurrencySymbols[acc.currency] || acc.currency)}
                                          </span>
                                        );
                                      })()}
                                    </div>
                                  </div>
                                );
                              })}
                            </div>
                          )}
                        </div>
                      );
                    })
                  ) : (
                    // Flat Accounts inside Group (e.g. by_type or by_institution)
                    group.accounts &&
                    organizeAccountsWithSubAccounts(group.accounts).map((acc) => {
                      const isCurrent =
                        selectedAccountId === acc.id ||
                        location.pathname === `/accounts/${acc.id}` ||
                        location.search.includes("account_id={p0}");

                      return (
                        <div
                          key={acc.id}
                          data-testid="account-item-link"
                          data-account-id={acc.id}
                          onClick={() => handleAccountClick(acc)}
                          onTouchStart={(e) => handleTouchStart(acc, e)}
                          onTouchMove={handleTouchMove}
                          onTouchEnd={handleTouchEnd}
                          onTouchCancel={handleTouchEnd}
                          onContextMenu={(e) => {
                            if (isMobileDrawer) e.preventDefault();
                          }}
                          title={acc.name || `*${acc.mask}`}
                          className={`group flex items-center justify-between py-1.5 rounded-lg cursor-pointer transition-colors duration-150 text-xs select-none touch-manipulation ${
                            acc.isChildInTree
                              ? 'ml-2.5 pl-1.5 pr-2 border-l border-amber-300 dark:border-amber-600/50 bg-amber-50/20 dark:bg-amber-950/10'
                              : 'px-2'
                          } ${
                            isCurrent
                              ? 'bg-zinc-100 dark:bg-zinc-800 font-semibold'
                              : 'hover:bg-zinc-50 dark:hover:bg-zinc-800/50'
                          }`}
                        >
                          <div className="flex items-center gap-1.5 min-w-0 pr-1 flex-1">
                            {acc.isChildInTree && (
                              <span className="text-amber-500/80 dark:text-amber-400 font-mono text-[10px] select-none shrink-0 -mr-0.5" title={tx("附属卡 / 子账户")}>
                                ↳
                              </span>
                            )}
                            {renderAccountIcon(acc, isAccountShared(acc), masterAccountIdSet.has(acc.id) || Boolean(acc.has_sub_accounts))}
                            {renderAccountDisplayName(acc, acc.isChildInTree)}
                          </div>
                          <div className="flex items-center gap-1 shrink-0">
                            {!isMobileDrawer && (
                              <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity duration-150">
                                {acc.can_manage === true && (
                                  <button
                                    type="button"
                                    title={tx("编辑账户信息")}
                                    data-testid="edit-account-panel-btn"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setEditingAccount(acc);
                                    }}
                                    className="p-1 rounded-md text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-700 transition-colors"
                                  >
                                    <Edit2 className="w-3 h-3" />
                                  </button>
                                )}
                                <button
                                  type="button"
                                  title={tx("配置共享权限")}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setSharingModalAccountId(acc.id);
                                  }}
                                  className="p-1 rounded-md text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-700 transition-colors"
                                >
                                  <Users className="w-3 h-3" />
                                </button>
                              </div>
                            )}
                            {(() => {
                              const isSubCard = Boolean(acc.parent_account_id) || acc.isChildInTree;
                              if (acc.classification === 'liability' && Number(acc.balance) < 0) {
                                return (
                                  <div className="flex items-center gap-1" title={isSubCard ? tx("附属卡溢缴款（已合并入主卡统筹）") : tx("账户溢缴款")}>
                                    <span className={`rounded font-semibold bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800 leading-none ${acc.isChildInTree ? 'text-[10px] px-1 py-0.5' : 'text-[11px] px-1.5 py-0.5'}`}>{tx("溢")}</span>
                                    <span className={`font-mono text-emerald-600 dark:text-emerald-400 text-right font-medium ${acc.isChildInTree ? 'text-xs' : 'text-[13px]'}`}>
                                      {privacyMode ? "••••" : formatCurrency(acc.balance || 0, accountCurrencySymbols[acc.currency] || acc.currency)}
                                    </span>
                                  </div>
                                );
                              }
                              if (isSubCard) {
                                return (
                                  <div className="flex items-center gap-0.5" title={tx("附属卡/子账户金额（已合并入主账户统筹）")}>
                                    <span className="font-mono text-right text-xs text-zinc-500 dark:text-zinc-400">
                                      {privacyMode ? "••••" : formatCurrency(acc.balance || 0, accountCurrencySymbols[acc.currency] || acc.currency)}
                                    </span>
                                  </div>
                                );
                              }
                              return (
                                <span className="font-mono text-right text-[13px] text-zinc-700 dark:text-zinc-300 font-medium">
                                  {privacyMode ? "••••" : formatCurrency(acc.balance || 0, accountCurrencySymbols[acc.currency] || acc.currency)}
                                </span>
                              );
                            })()}
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* ── Modal: Create Account ── */}
      <Modal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        title={activeTab === 'liability' ? tx("添加负债账户") : tx("添加账户")}
      >
        <form onSubmit={handleCreateAccount} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-zinc-600 dark:text-zinc-400 mb-1">{tx("账户名称 / 卡别名")}</label>
            <input
              type="text"
              required
              placeholder={tx("例如：招商银行 7931、建设银行 2342 或 工资卡")}
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              className="w-full px-3 py-2 text-xs bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none focus:border-zinc-900"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-zinc-600 dark:text-zinc-400 mb-1">{tx("金融机构 (Bank / Institution)")}</label>
            <input
              type="text"
              required
              placeholder={tx("例如：招商银行、中国银行、建设银行")}
              value={form.institution_name}
              onChange={(e) => setForm({ ...form, institution_name: e.target.value })}
              className="w-full px-3 py-2 text-xs bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none focus:border-zinc-900"
            />
          </div>

          <ExternalIdentifierField
            id="create-account-external-identifier"
            value={form.external_identifier}
            onChange={(value) => setForm({ ...form, external_identifier: value })}
          />

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-zinc-600 dark:text-zinc-400 mb-1">{tx("账户类别")}</label>
              <AccountTypeSelectDropdown
                name="account_type"
                value={form.account_type}
                onChange={(e) => {
                  const newType = e.target.value;
                  setForm({
                    ...form,
                    account_type: newType,
                    parent_account_id: newType === 'credit_card' ? form.parent_account_id : '',
                  });
                }}
                testId="create-account-type-select"
                useShortLabel
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-zinc-600 dark:text-zinc-400 mb-1">{tx("账户币种")}</label>
              <select
                value={form.currency || prefCurrency || 'CNY'}
                onChange={(e) => setForm({ ...form, currency: e.target.value })}
                className="w-full px-3 py-2 text-xs bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none focus:border-zinc-900 cursor-pointer"
              >
                {(currencies || []).map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.code} ({c.symbol}) - {c.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-zinc-600 dark:text-zinc-400 mb-1">{tx("初始金额")}</label>
            <div className="relative">
              <span className="absolute left-3 top-2 text-xs font-mono text-zinc-400 select-none">
                {currencies?.find((c) => c.code === (form.currency || prefCurrency))?.symbol || symbol || '¥'}
              </span>
              <input
                type="number"
                step="0.01"
                value={form.balance}
                onChange={(e) => setForm({ ...form, balance: e.target.value })}
                className="w-full pl-8 pr-3 py-2 text-xs bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none font-mono focus:border-zinc-900"
              />
            </div>
          </div>

          {form.account_type === 'credit_card' && (
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="block text-xs font-semibold text-zinc-600 dark:text-zinc-400">{tx("所属信用卡主卡 (可选)")}</label>
                {form.parent_account_id && (
                  <span className="text-[10px] font-semibold text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/60 px-1.5 py-0.5 rounded">{tx("附属卡")}</span>
                )}
              </div>
              <AccountSelectDropdown
                name="parent_account_id"
                value={form.parent_account_id || ''}
                onChange={(e) => setForm({ ...form, parent_account_id: e.target.value })}
                accounts={parentCandidates}
                emptyLabel={tx("无 (独立主卡)")}
                placeholder={tx("选择所属信用卡主卡")}
                testId="create-account-parent-select"
              />
              <p className="mt-1 text-[11px] text-zinc-400">{tx("不同拥有者的卡片，请先创建并共享给主卡所有者，再设置为副卡。")}</p>
            </div>
          )}

          {/* 实时效果预览（所见即所得） */}
          <div className="p-3 rounded-xl bg-zinc-50 dark:bg-zinc-800/60 border border-zinc-200/80 dark:border-zinc-700/80 text-xs space-y-1">
            <span className="text-[11px] text-zinc-400 font-medium block">{tx("卡片实时预览（所见即所得）")}</span>
            <div className="flex items-center justify-between py-1 px-1">
              <div className="flex items-center gap-2 min-w-0 pr-2">
                {renderAccountIcon({
                  account_type: form.account_type,
                  classification: activeTab,
                  parent_account_id: form.parent_account_id,
                })}
                <span className="font-semibold text-zinc-900 dark:text-zinc-100 truncate">
                  {form.name.trim() || tx("账户名称预览")}
                </span>
              </div>
              <span className="text-[11px] text-zinc-400 font-mono shrink-0">
                {form.institution_name.trim() || tx("金融机构")} · {form.currency || prefCurrency || 'CNY'}
              </span>
            </div>
          </div>

          <div className="pt-2 flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setModalOpen(false)}>{tx("取消")}</Button>
            <Button type="submit" variant="primary">{tx("确认添加")}</Button>
          </div>
        </form>
      </Modal>

      {/* ── Modal: Account Sharing Management ── */}
      <AccountSharingModal
        accountId={sharingModalAccountId}
        open={Boolean(sharingModalAccountId)}
        onClose={() => setSharingModalAccountId(null)}
        onUpdated={() => {
          // 重新拉取账户列表
          const event = new CustomEvent('accounts-updated');
          window.dispatchEvent(event);
        }}
      />

      {/* ── Modal: Edit Account Info ── */}
      <EditAccountModal
        isOpen={Boolean(editingAccount)}
        account={editingAccount}
        onClose={() => setEditingAccount(null)}
        onSuccess={() => {
          fetchAccounts();
          const event = new CustomEvent('accounts-updated');
          window.dispatchEvent(event);
        }}
      />

      {/* ── Mobile Action Sheet for Account Long-Press ── */}
      {actionSheetAccount && (
        <div
          data-testid="mobile-account-action-sheet"
          className="fixed inset-0 z-50 flex flex-col justify-end"
        >
          {/* Backdrop */}
          <div
            className="fixed inset-0 bg-black/50 backdrop-blur-xs transition-opacity duration-200"
            onClick={() => setActionSheetAccount(null)}
          />

          {/* Sheet Container */}
          <div className="relative z-10 w-full max-w-lg mx-auto bg-white dark:bg-zinc-900 rounded-t-2xl shadow-2xl p-4 pb-8 space-y-3 animate-in slide-in-from-bottom duration-200 border-t border-zinc-200/80 dark:border-zinc-800">
            {/* Grab handle indicator */}
            <div className="w-10 h-1 bg-zinc-300 dark:bg-zinc-700 rounded-full mx-auto -mt-1 mb-2" />

            {/* Account Info Header */}
            <div className="flex items-center justify-between pb-3 border-b border-zinc-100 dark:border-zinc-800/80">
              <div className="flex items-center gap-2.5 min-w-0">
                <div className="w-8 h-8 rounded-xl bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center shrink-0">
                  {renderAccountIcon(actionSheetAccount, isAccountShared(actionSheetAccount), masterAccountIdSet.has(actionSheetAccount?.id) || Boolean(actionSheetAccount?.has_sub_accounts))}
                </div>
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-zinc-900 dark:text-zinc-100 truncate">
                    {actionSheetAccount.name || `*${actionSheetAccount.mask}`}
                  </div>
                  <div className="text-[11px] text-zinc-500 dark:text-zinc-400 truncate flex items-center gap-1.5">
                    <span>{actionSheetAccount.institution_name || tx("金融机构")}</span>
                    <span>·</span>
                    <span>{normalizeAccountType(actionSheetAccount)}</span>
                    {isAccountShared(actionSheetAccount) && (
                      <span className="px-1 py-0.2 rounded text-[11px] bg-purple-50 dark:bg-purple-950/60 text-purple-600 dark:text-purple-300 border border-purple-200 dark:border-purple-800">
                        {actionSheetAccount.owner || tx("家人")} {tx("共享")}</span>
                    )}
                  </div>
                </div>
              </div>
              <div className="text-right shrink-0">
                <div className={`font-mono text-sm font-semibold ${
                  actionSheetAccount.classification === 'liability' && Number(actionSheetAccount.balance) < 0
                    ? 'text-emerald-600 dark:text-emerald-400'
                    : 'text-zinc-900 dark:text-zinc-100'
                }`}>
                  {privacyMode ? "••••" : formatCurrency(actionSheetAccount.balance || 0, accountCurrencySymbols[actionSheetAccount.currency] || actionSheetAccount.currency)}
                </div>
              </div>
            </div>

            {/* Action Buttons */}
            <div className="space-y-1.5">
              {/* 1. 编辑账户 */}
              {actionSheetAccount.can_manage === true && (
                <button
                  type="button"
                  data-testid="action-sheet-edit-btn"
                  onClick={() => {
                    const acc = actionSheetAccount;
                    setActionSheetAccount(null);
                    setEditingAccount(acc);
                  }}
                  className="w-full flex items-center justify-between px-3.5 py-3 rounded-xl bg-zinc-50 dark:bg-zinc-800/60 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-800 dark:text-zinc-200 transition-colors"
                >
                  <div className="flex items-center gap-2.5 text-xs font-medium">
                    <Edit2 className="w-4 h-4 text-zinc-500 dark:text-zinc-400" />
                    <span>{tx("编辑账户信息")}</span>
                  </div>
                  <ChevronRight className="w-3.5 h-3.5 text-zinc-400" />
                </button>
              )}

              {/* 3. 配置共享 */}
              <button
                type="button"
                data-testid="action-sheet-share-btn"
                onClick={() => {
                  const acc = actionSheetAccount;
                  setActionSheetAccount(null);
                  setSharingModalAccountId(acc.id);
                }}
                className="w-full flex items-center justify-between px-3.5 py-3 rounded-xl bg-zinc-50 dark:bg-zinc-800/60 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-800 dark:text-zinc-200 transition-colors"
              >
                <div className="flex items-center gap-2.5 text-xs font-medium">
                  <Users className="w-4 h-4 text-zinc-500 dark:text-zinc-400" />
                  <span>{actionSheetAccount.can_manage_shares ? tx("配置家庭共享权限") : tx("查看共享与个人统计设置")}</span>
                </div>
                <ChevronRight className="w-3.5 h-3.5 text-zinc-400" />
              </button>
            </div>

            {/* Cancel Button */}
            <button
              type="button"
              data-testid="action-sheet-cancel-btn"
              onClick={() => setActionSheetAccount(null)}
              className="w-full py-2.5 mt-2 rounded-xl bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 text-zinc-600 dark:text-zinc-300 text-xs font-semibold transition-colors"
            >{tx("取消")}</button>
          </div>
        </div>
      )}
    </div>
  );
}
