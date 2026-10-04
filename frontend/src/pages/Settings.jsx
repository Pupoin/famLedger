import { categoryLabel, tx, useLocale } from "../localization.js";
import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { ChevronLeft, Sliders, User, Shield, KeyRound, SlidersHorizontal, Database, Plus, Trash2, ExternalLink, CheckCircle2, XCircle, ArrowRight, ArrowRightLeft, Sparkles, Layers, Users, Edit2, Check, FolderTree, Tag as TagIcon, ChevronRight, Lock, MoreHorizontal, Building2, LogOut, Key, Copy, Terminal, UserPlus, Inbox, Send } from 'lucide-react';
import { useAuth } from '../auth/AuthContext';
import { useTheme } from '../ThemeContext';
import { useCurrency } from '../CurrencyContext';
import { useDateFormat } from '../DateFormatContext';
import { useToast } from '../ToastContext';
import { fetchWithAuth } from '../api/fetchWithAuth';
import { uploadAvatar } from '../api/client';
import { formatCurrency } from '../utils/currency';
import { getAccountTypeConfig } from '../utils/accountIcons';
import { formatDateTime } from '../utils/dates';
import Avatar from '../components/Avatar';
import AccountSharingModal from '../components/AccountSharingModal';
import {
  EditAccountModal,
  TransferOwnershipModal,
  DeleteAccountModal,
} from '../components/AccountModals';
import { API_BASE } from '../config';
import RulesPage from './RulesPage';
import CurrencyChangeAlertModal from '../components/CurrencyChangeAlertModal';

export default function Settings() {
  useLocale();
  const [searchParams, setSearchParams] = useSearchParams();
  const hasTab = Boolean(searchParams.get('tab'));
  const rawTab = searchParams.get('tab') || 'profile';
  const activeTab = rawTab === 'security' ? 'profile' : rawTab;
  const { t, i18n } = useTranslation();

  const tabTitles = {
    family: '家庭组与成员',
    accounts: '账户管理',
    preferences: t('settings.preferences', tx("偏好设置")),
    profile: t('settings.profile', tx("个人资料与安全")),
    categories: '分类体系管理',
    tags: '标签管理',
    rules: t('settings.rules', tx("规则与自动化")),
    oidc: t('settings.oidc', tx("单点登录 (OIDC/SSO)")),
    hosting: t('settings.hosting', tx("私有化与 AI 配置")),
    apikeys: 'API 密钥 (API Keys)',
    data: t('settings.data', tx("数据与备份")),
    system_users: '系统用户管理',
    system_families: '全局家庭组管理',
  };
  const currentTabTitle = tx(tabTitles[activeTab]) || t('settings.title', tx("Settings"));

  const handleBackToSettingsMenu = () => {
    const p = new URLSearchParams(searchParams);
    p.delete('tab');
    setSearchParams(p);
  };

  useEffect(() => {
    // 切换子页面时移动端平滑回到顶部
    window.scrollTo({ top: 0, behavior: 'instant' });
  }, [searchParams]);
  const { user, logout, refreshUser } = useAuth();
  const { themeMode, setThemeMode } = useTheme();
  const { currency, setCurrency, currencies, privacyMode, togglePrivacyMode, setLanguage } = useCurrency();
  const { dateFormat, setDateFormat } = useDateFormat();
  const { showToast } = useToast();

  const fileInputRef = useRef(null);
  const [avatarKey, setAvatarKey] = useState(0);

  // Profile Form States (名字、昵称、邮箱、密码、头像)
  const [profileUsername, setProfileUsername] = useState('');
  const [profileDisplayName, setProfileDisplayName] = useState('');
  const [profileEmail, setProfileEmail] = useState('');
  const [profileCurrentPassword, setProfileCurrentPassword] = useState('');
  const [profileNewPassword, setProfileNewPassword] = useState('');
  const [profileConfirmPassword, setProfileConfirmPassword] = useState('');
  const [profileLoading, setProfileLoading] = useState(false);

  // Sync profile values when user loads or activeTab === 'profile'
  useEffect(() => {
    if (user) {
      setProfileUsername(user.username || '');
      setProfileDisplayName(user.displayName || '');
      setProfileEmail(user.email || '');
    }
  }, [user, activeTab]);

  // SSO / OIDC Providers state
  const [ssoProviders, setSsoProviders] = useState([]);
  const [ssoLoading, setSsoLoading] = useState(false);
  const [showAddOidcModal, setShowAddOidcModal] = useState(false);
  const [editingOidcProvider, setEditingOidcProvider] = useState(null); // null for create, object for edit
  const [oidcForm, setOidcForm] = useState({
    name: 'authentik',
    label: 'Authentik SSO',
    issuer: 'https://auth.example.lan/application/o/famledger',
    client_id: '',
    client_secret: '',
    enabled: true,
    allow_jit: true,
    allowed_domains: '',
  });

  // API Keys state
  const [apiKeys, setApiKeys] = useState([]);
  const [apiKeysLoading, setApiKeysLoading] = useState(false);
  const [showCreateApiKeyModal, setShowCreateApiKeyModal] = useState(false);
  const [apiKeyName, setApiKeyName] = useState('');
  const [apiKeyExpiresDays, setApiKeyExpiresDays] = useState('365');
  const [createApiKeyLoading, setCreateApiKeyLoading] = useState(false);
  const [newlyCreatedKey, setNewlyCreatedKey] = useState(null); // { raw_key, name, key_prefix }
  const [copiedKey, setCopiedKey] = useState(false);
  const [deletingKeyId, setDeletingKeyId] = useState(null);

  // Preferences extras
  const [timezone, setTimezone] = useState(() => localStorage.getItem('famledger_tz') || 'Asia/Shanghai');
  const [accountOrder, setAccountOrder] = useState(() => localStorage.getItem('famledger_acc_order') || 'name_asc');

  // Hosting / AI settings
  const [aiProvider, setAiProvider] = useState(() => localStorage.getItem('famledger_ai_provider') || 'openai');
  const [aiKey, setAiKey] = useState(() => localStorage.getItem('famledger_ai_key') || '');
  const [aiBaseUrl, setAiBaseUrl] = useState(() => localStorage.getItem('famledger_ai_base') || 'https://api.openai.com/v1');
  const [aiModel, setAiModel] = useState(() => localStorage.getItem('famledger_ai_model') || 'gpt-4o-mini');

  // Automations state
  const [autoTransfer, setAutoTransfer] = useState(true);
  const [autoRefund, setAutoRefund] = useState(true);

  // 家庭组与成员管理状态
  const [currentFamily, setCurrentFamily] = useState(null);
  const [familyLoading, setFamilyLoading] = useState(false);
  const [availableFamilies, setAvailableFamilies] = useState([]);
  const [renameMode, setRenameMode] = useState(false);
  const [renameValue, setRenameValue] = useState('');
  const [renameLoading, setRenameLoading] = useState(false);

  // 系统管理员：删除用户弹窗
  const [deletingMember, setDeletingMember] = useState(null); // 要删除的用户对象
  const [deleteAdminPassword, setDeleteAdminPassword] = useState('');
  const [deleteMemberLoading, setDeleteMemberLoading] = useState(false);

  const isSuperAdmin = Boolean(currentFamily?.is_super_admin || user?.role === 'admin');

  // 系统管理员：重置用户密码弹窗
  const [resetPasswordMember, setResetPasswordMember] = useState(null); // 要重置密码的用户
  const [resetNewPassword, setResetNewPassword] = useState('');
  const [resetConfirmPassword, setResetConfirmPassword] = useState('');
  const [resetPasswordLoading, setResetPasswordLoading] = useState(false);
  const [memberMenuOpenId, setMemberMenuOpenId] = useState(null); // 控制三点菜单展开
  const [kickingMember, setKickingMember] = useState(null); // 要踢出的成员
  const [kickMemberLoading, setKickMemberLoading] = useState(false);

  // 新建家庭组状态
  const [showCreateFamilyModal, setShowCreateFamilyModal] = useState(false);
  const [createFamilyName, setCreateFamilyName] = useState('');
  const [createFamilyCurrency, setCreateFamilyCurrency] = useState('CNY');
  const [createFamilyLoading, setCreateFamilyLoading] = useState(false);

  // 解散/删除家庭组状态
  const [showDeleteFamilyModal, setShowDeleteFamilyModal] = useState(false);
  const [deleteFamilyLoading, setDeleteFamilyLoading] = useState(false);

  // 退出家庭组状态
  const [showLeaveFamilyModal, setShowLeaveFamilyModal] = useState(false);
  const [showLeaveOwnerWarningModal, setShowLeaveOwnerWarningModal] = useState(false);
  const [leaveFamilyLoading, setLeaveFamilyLoading] = useState(false);

  // ── 家庭组入组邀请状态 ──
  const [receivedInvitations, setReceivedInvitations] = useState([]);
  const [sentInvitations, setSentInvitations] = useState([]);
  const [invitationsLoading, setInvitationsLoading] = useState(false);
  const [showInviteModal, setShowInviteModal] = useState(false);
  const [inviteForm, setInviteForm] = useState({ username: '', message: '' });
  const [inviteLoading, setInviteLoading] = useState(false);
  const [invitationProcessingId, setInvitationProcessingId] = useState(null);
  const [showSentInvitations, setShowSentInvitations] = useState(false);
  const [currencyChangeModal, setCurrencyChangeModal] = useState({ open: false, data: {} });

  // 账户手动编辑状态
  const [editingAccount, setEditingAccount] = useState(null);

  // ── 分类体系管理状态 ──
  // ── 分类体系管理状态 ──
  const [categories, setCategories] = useState([]);
  const [categoriesLoading, setCategoriesLoading] = useState(false);
  const [categoryFilterType, setCategoryFilterType] = useState('expense'); // 'expense' | 'income' | 'all'
  const [showCategoryModal, setShowCategoryModal] = useState(false);
  const [categoryModalMode, setCategoryModalMode] = useState('create'); // 'create' | 'edit'
  const [categoryForm, setCategoryForm] = useState({ id: '', name: '', icon: '🍽️', color: '#6366f1', category_type: 'expense' });
  const [categorySaving, setCategorySaving] = useState(false);
  const [deletingCategory, setDeletingCategory] = useState(null);

  // ── 标签体系管理状态 ──
  const [tagsList, setTagsList] = useState([]);
  const [tagsLoading, setTagsLoading] = useState(false);
  const [newTagName, setNewTagName] = useState('');
  const [newTagColor, setNewTagColor] = useState('#71717a');
  const [creatingTag, setCreatingTag] = useState(false);
  const [editingTag, setEditingTag] = useState(null);
  const [editTagName, setEditTagName] = useState('');
  const [editTagColor, setEditTagColor] = useState('#71717a');
  const [deletingTag, setDeletingTag] = useState(null);

  const fetchCategories = async () => {
    try {
      setCategoriesLoading(true);
      const res = await fetchWithAuth('/api/v1/categories');
      if (res.ok) {
        const data = await res.json();
        setCategories(data.categories || data.items || []);
      }
    } catch {
      showToast(tx("获取分类列表失败"), 'error');
    } finally {
      setCategoriesLoading(false);
    }
  };

  const filteredCategories = useMemo(() => {
    if (categoryFilterType === 'all') return categories;
    return categories.filter((c) => (c.category_type || 'expense') === categoryFilterType);
  }, [categories, categoryFilterType]);

  const expenseCategoryCount = useMemo(
    () => categories.filter((c) => (c.category_type || 'expense') === 'expense').length,
    [categories]
  );
  const incomeCategoryCount = useMemo(
    () => categories.filter((c) => (c.category_type || 'expense') === 'income').length,
    [categories]
  );

  const fetchTags = async () => {
    try {
      setTagsLoading(true);
      const res = await fetchWithAuth('/api/v1/tags');
      if (res.ok) {
        const data = await res.json();
        setTagsList(data.tags || data.items || []);
      }
    } catch {
      showToast(tx("获取标签列表失败"), 'error');
    } finally {
      setTagsLoading(false);
    }
  };

  const handleOpenCreateCategory = () => {
    setCategoryModalMode('create');
    const defaultType = categoryFilterType === 'income' ? 'income' : 'expense';
    setCategoryForm({
      id: '',
      name: '',
      icon: defaultType === 'income' ? '💰' : '🍽️',
      color: defaultType === 'income' ? '#10b981' : '#6366f1',
      category_type: defaultType,
    });
    setShowCategoryModal(true);
  };

  const handleOpenEditCategory = (cat) => {
    setCategoryModalMode('edit');
    setCategoryForm({
      id: cat.id,
      name: cat.name,
      icon: cat.icon || '📦',
      color: cat.color || '#6366f1',
      category_type: cat.category_type || 'expense',
    });
    setShowCategoryModal(true);
  };

  const handleSaveCategory = async (e) => {
    e?.preventDefault();
    if (!categoryForm.name.trim()) {
      showToast(tx("请输入分类名称"), 'error');
      return;
    }
    try {
      setCategorySaving(true);
      const url = categoryModalMode === 'create'
        ? '/api/v1/categories'
        : `/api/v1/categories/${categoryForm.id}`;
      const method = categoryModalMode === 'create' ? 'POST' : 'PUT';
      const res = await fetchWithAuth(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: categoryForm.name.trim(),
          icon: categoryForm.icon,
          color: categoryForm.color,
          category_type: categoryForm.category_type || 'expense',
        }),
      });
      if (res.ok) {
        showToast(tx(categoryModalMode === 'create' ? '分类创建成功' : '分类已更新'), 'success');
        setShowCategoryModal(false);
        fetchCategories();
      } else {
        const err = await res.json().catch(() => ({}));
        showToast(tx(err.detail || '保存分类失败'), 'error');
      }
    } catch {
      showToast(tx("网络错误，请稍后重试"), 'error');
    } finally {
      setCategorySaving(false);
    }
  };

  const handleDeleteCategory = async () => {
    if (!deletingCategory) return;
    try {
      const res = await fetchWithAuth(`/api/v1/categories/${deletingCategory.id}`, {
        method: 'DELETE',
      });
      if (res.ok) {
        showToast(tx("分类已删除"), 'success');
        setDeletingCategory(null);
        fetchCategories();
      } else {
        const err = await res.json().catch(() => ({}));
        showToast(tx(err.detail || '删除失败'), 'error');
      }
    } catch {
      showToast(tx("网络错误"), 'error');
    }
  };

  const handleCreateTag = async (e) => {
    e?.preventDefault();
    const cleanName = newTagName.trim();
    if (!cleanName) {
      showToast(tx("请输入标签名称"), 'error');
      return;
    }
    try {
      setCreatingTag(true);
      const res = await fetchWithAuth('/api/v1/tags', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: cleanName, color: newTagColor }),
      });
      if (res.ok) {
        showToast(tx("标签「{p0}」已添加", {p0: (cleanName)}), 'success');
        setNewTagName('');
        fetchTags();
      } else {
        const err = await res.json().catch(() => ({}));
        showToast(tx(err.detail || '添加标签失败'), 'error');
      }
    } catch {
      showToast(tx("网络错误"), 'error');
    } finally {
      setCreatingTag(false);
    }
  };

  const handleUpdateTag = async (e) => {
    e?.preventDefault();
    if (!editingTag || !editTagName.trim()) return;
    try {
      const res = await fetchWithAuth(`/api/v1/tags/${editingTag.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: editTagName.trim(), color: editTagColor }),
      });
      if (res.ok) {
        showToast(tx("标签已更新"), 'success');
        setEditingTag(null);
        fetchTags();
      } else {
        const err = await res.json().catch(() => ({}));
        showToast(tx(err.detail || '更新失败'), 'error');
      }
    } catch {
      showToast(tx("网络错误"), 'error');
    }
  };

  const handleDeleteTag = async () => {
    if (!deletingTag) return;
    try {
      const res = await fetchWithAuth(`/api/v1/tags/${deletingTag.id}`, {
        method: 'DELETE',
      });
      if (res.ok) {
        showToast(tx("标签「{p0}」已删除", {p0: (deletingTag.name)}), 'success');
        setDeletingTag(null);
        fetchTags();
      } else {
        const err = await res.json().catch(() => ({}));
        showToast(tx(err.detail || '删除标签失败'), 'error');
      }
    } catch {
      showToast(tx("网络错误"), 'error');
    }
  };

  const fetchFamilyInfo = async () => {
    try {
      setFamilyLoading(true);
      const [resCurrent, resList] = await Promise.all([
        fetchWithAuth('/api/v1/family/current'),
        fetchWithAuth('/api/v1/family/list'),
      ]);
      if (resCurrent.ok) {
        const json = await resCurrent.json();
        setCurrentFamily(json);
        setRenameValue(json.name || '');
      }
      if (resList.ok) {
        const json = await resList.json();
        setAvailableFamilies(json.families || []);
      }
      fetchInvitations();
    } catch {
      showToast(tx("获取家庭组信息失败"), 'error');
    } finally {
      setFamilyLoading(false);
    }
  };

  const handleCreateFamily = async (e) => {
    if (e) e.preventDefault();
    const name = createFamilyName.trim();
    if (!name) {
      showToast(tx("请输入新家庭组名称"), 'error');
      return;
    }
    try {
      setCreateFamilyLoading(true);
      const res = await fetchWithAuth('/api/v1/family/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, currency: createFamilyCurrency }),
      });
      const data = await res.json();
      if (res.ok) {
        showToast(tx(data.message || '家庭组创建成功'), 'success');
        setShowCreateFamilyModal(false);
        setCreateFamilyName('');
        await fetchFamilyInfo();
        if (refreshUser) await refreshUser();
        window.dispatchEvent(new CustomEvent('accounts-updated'));
      } else {
        showToast(tx(data.detail || '创建家庭组失败'), 'error');
      }
    } catch {
      showToast(tx("网络错误，请稍后重试"), 'error');
    } finally {
      setCreateFamilyLoading(false);
    }
  };

  const handleDeleteFamily = async () => {
    try {
      setDeleteFamilyLoading(true);
      const res = await fetchWithAuth('/api/v1/family/current', {
        method: 'DELETE',
      });
      const data = await res.json();
      if (res.ok) {
        showToast(tx(data.message || '家庭组已成功解散'), 'success');
        setShowDeleteFamilyModal(false);
        await fetchFamilyInfo();
        if (refreshUser) await refreshUser();
        window.dispatchEvent(new CustomEvent('accounts-updated'));
      } else {
        showToast(tx(data.detail || '解散家庭组失败'), 'error');
      }
    } catch {
      showToast(tx("网络错误，请稍后重试"), 'error');
    } finally {
      setDeleteFamilyLoading(false);
    }
  };

  const handleLeaveFamily = async () => {
    try {
      setLeaveFamilyLoading(true);
      const res = await fetchWithAuth('/api/v1/family/leave', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      const data = await res.json();
      if (res.ok) {
        showToast(tx(data.message || '已成功退出家庭组'), 'success');
        setShowLeaveFamilyModal(false);
        await fetchFamilyInfo();
        if (refreshUser) await refreshUser();
        window.dispatchEvent(new CustomEvent('accounts-updated'));
        window.dispatchEvent(new CustomEvent('preferences-updated'));
      } else {
        showToast(tx(data.detail || '退出家庭组失败'), 'error');
      }
    } catch {
      showToast(tx("网络错误，请稍后重试"), 'error');
    } finally {
      setLeaveFamilyLoading(false);
    }
  };

  const handleOpenLeaveFamily = () => {
    // 优先采用后端下发的权威 can_leave 判定
    if (currentFamily?.can_leave === false && currentFamily?.is_owner) {
      setShowLeaveOwnerWarningModal(true);
      return;
    }

    // 兼容前端兜底统计除自己外的其他管理员
    const otherAdminsCount = currentFamily?.other_admins_count ?? (currentFamily?.members || []).filter(
      (m) => !m.is_current_user && (m.role === 'owner' || m.role === 'admin' || m.role === 'family_admin' || m.role === 'super_admin')
    ).length;
    const hasOtherMembers = (currentFamily?.members || []).filter((m) => !m.is_current_user).length > 0;

    // 仅当当前用户是管理员，且组内还有其他普通成员，但组内没有其他任何管理员时，才拦截引导转让
    if (currentFamily?.is_owner && hasOtherMembers && otherAdminsCount === 0) {
      setShowLeaveOwnerWarningModal(true);
    } else {
      setShowLeaveFamilyModal(true);
    }
  };


  const handleRenameFamily = async (e) => {
    if (e) e.preventDefault();
    const name = renameValue.trim();
    if (!name) return;
    try {
      setRenameLoading(true);
      const res = await fetchWithAuth('/api/v1/family/rename', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      const data = await res.json();
      if (res.ok) {
        showToast(tx("家庭组名称修改成功"), 'success');
        setRenameMode(false);
        await fetchFamilyInfo();
      } else {
        showToast(tx(data.detail || '修改失败'), 'error');
      }
    } catch {
      showToast(tx("网络错误"), 'error');
    } finally {
      setRenameLoading(false);
    }
  };

  // ── 家庭组入组邀请接口操作 ──
  const fetchInvitations = async () => {
    try {
      setInvitationsLoading(true);
      const resReceived = await fetchWithAuth('/api/v1/family/invitations/received');
      if (resReceived.ok) {
        const data = await resReceived.json();
        setReceivedInvitations(data.invitations || []);
      }
      const resSent = await fetchWithAuth('/api/v1/family/invitations/sent');
      if (resSent.ok) {
        const data = await resSent.json();
        setSentInvitations(data.invitations || []);
      }
    } catch (e) {
      console.error('拉取邀请列表失败', e);
    } finally {
      setInvitationsLoading(false);
    }
  };

  const handleSendInvitation = async (e) => {
    if (e) e.preventDefault();
    const username = inviteForm.username.trim();
    if (!username) {
      showToast(tx("请输入被邀请人的用户名"), 'error');
      return;
    }
    try {
      setInviteLoading(true);
      const res = await fetchWithAuth('/api/v1/family/invitations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username,
          message: inviteForm.message.trim() || undefined,
        }),
      });
      const data = await res.json();
      if (res.ok) {
        showToast(tx(data.message || '邀请已成功发出'), 'success');
        setShowInviteModal(false);
        setInviteForm({ username: '', message: '' });
        await fetchInvitations();
      } else {
        showToast(tx(data.detail || '发送邀请失败'), 'error');
      }
    } catch {
      showToast(tx("网络错误，请稍后重试"), 'error');
    } finally {
      setInviteLoading(false);
    }
  };

  const handleAcceptInvitation = async (invitationId) => {
    try {
      setInvitationProcessingId(invitationId);
      const res = await fetchWithAuth(`/api/v1/family/invitations/${invitationId}/accept`, {
        method: 'POST',
      });
      const data = await res.json();
      if (res.ok) {
        await fetchFamilyInfo();
        await fetchInvitations();
        if (refreshUser) await refreshUser();
        window.dispatchEvent(new CustomEvent('accounts-updated'));
        window.dispatchEvent(new CustomEvent('preferences-updated'));

        if (data.currency_change?.changed) {
          setCurrencyChangeModal({
            open: true,
            data: {
              familyName: data.family?.name || '家庭组',
              previous_currency: data.currency_change.previous_currency,
              new_currency: data.currency_change.new_currency,
            },
          });
        } else {
          showToast(tx(data.message || '已成功加入家庭组！'), 'success');
        }
      } else {
        showToast(tx(data.detail || '接受邀请失败'), 'error');
      }
    } catch {
      showToast(tx("网络错误，请稍后重试"), 'error');
    } finally {
      setInvitationProcessingId(null);
    }
  };

  const handleRejectInvitation = async (invitationId) => {
    try {
      setInvitationProcessingId(invitationId);
      const res = await fetchWithAuth(`/api/v1/family/invitations/${invitationId}/reject`, {
        method: 'POST',
      });
      const data = await res.json();
      if (res.ok) {
        showToast(tx(data.message || '已谢绝该入组邀请'), 'info');
        await fetchInvitations();
      } else {
        showToast(tx(data.detail || '处理失败'), 'error');
      }
    } catch {
      showToast(tx("网络错误，请稍后重试"), 'error');
    } finally {
      setInvitationProcessingId(null);
    }
  };

  const handleCancelInvitation = async (invitationId) => {
    try {
      setInvitationProcessingId(invitationId);
      const res = await fetchWithAuth(`/api/v1/family/invitations/${invitationId}`, {
        method: 'DELETE',
      });
      const data = await res.json();
      if (res.ok) {
        showToast(tx(data.message || '邀请已成功撤回'), 'success');
        await fetchInvitations();
      } else {
        showToast(tx(data.detail || '撤回失败'), 'error');
      }
    } catch {
      showToast(tx("网络错误，请稍后重试"), 'error');
    } finally {
      setInvitationProcessingId(null);
    }
  };

  // 账户共享矩阵状态
  const [sharesMatrix, setSharesMatrix] = useState(null);
  const [matrixLoading, setMatrixLoading] = useState(true);
  const [selectedShareAccountId, setSelectedShareAccountId] = useState(null);
  const [openAccountMenuId, setOpenAccountMenuId] = useState(null);
  const [transferringAccount, setTransferringAccount] = useState(null);
  const [deletingAccount, setDeletingAccount] = useState(null);

  // 新增家庭成员弹窗状态
  const [showAddMemberModal, setShowAddMemberModal] = useState(false);
  const [newMemberForm, setNewMemberForm] = useState({
    username: '',
    display_name: '',
    password: '',
    role: 'member',
  });
  const [addMemberLoading, setAddMemberLoading] = useState(false);

  // 系统全部家庭组（系统管理员）
  const [systemFamilies, setSystemFamilies] = useState([]);
  const [systemFamiliesLoading, setSystemFamiliesLoading] = useState(false);
  const [deletingSystemFamily, setDeletingSystemFamily] = useState(null);

  // 系统全部用户（系统管理员专享）
  const [systemUsers, setSystemUsers] = useState([]);
  const [systemUsersLoading, setSystemUsersLoading] = useState(false);

  const fetchSystemFamilies = async () => {
    try {
      setSystemFamiliesLoading(true);
      const res = await fetchWithAuth('/api/v1/family/system/all');
      if (res.ok) {
        const data = await res.json();
        setSystemFamilies(data.families || []);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setSystemFamiliesLoading(false);
    }
  };

  const fetchSystemUsers = async () => {
    try {
      setSystemUsersLoading(true);
      const res = await fetchWithAuth('/api/v1/family/system/users');
      if (res.ok) {
        const data = await res.json();
        setSystemUsers(data.users || []);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setSystemUsersLoading(false);
    }
  };

  const handleCreateMember = async (e) => {
    e.preventDefault();
    if (!newMemberForm.username.trim() || !newMemberForm.password) {
      showToast(tx("请完整填写用户名和密码"), 'error');
      return;
    }
    try {
      setAddMemberLoading(true);
      const res = await fetchWithAuth('/api/v1/family/members/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newMemberForm),
      });
      const data = await res.json();
      if (res.ok) {
        showToast(tx(data.message || '成功新增家庭成员'), 'success');
        setShowAddMemberModal(false);
        setNewMemberForm({ username: '', display_name: '', password: '', role: 'member' });
        fetchFamilyInfo();
        fetchSharesMatrix();
      } else {
        showToast(tx(data.detail || '新增成员失败'), 'error');
      }
    } catch {
      showToast(tx("网络错误，请稍后重试"), 'error');
    } finally {
      setAddMemberLoading(false);
    }
  };

  // 家庭组管理员：踢出成员
  const handleKickMember = async () => {
    if (!kickingMember) return;
    try {
      setKickMemberLoading(true);
      const res = await fetchWithAuth(`/api/v1/family/members/${kickingMember.id}/kick`, {
        method: 'POST',
      });
      const data = await res.json();
      if (res.ok) {
        showToast(tx(data.message || '成员已移出家庭组'), 'success');
        setKickingMember(null);
        fetchFamilyInfo();
        fetchSharesMatrix();
      } else {
        showToast(tx(data.detail || '操作失败'), 'error');
      }
    } catch {
      showToast(tx("网络错误，请稍后重试"), 'error');
    } finally {
      setKickMemberLoading(false);
    }
  };

  // 设置或取消家庭组管理员 (仅限具体家庭组内)
  const handleToggleMemberAdmin = async (member) => {
    const isOwner = member.role === 'owner' || member.role === 'family_admin';
    const nextRole = isOwner ? 'member' : 'owner';
    const actionDesc = isOwner ? '取消家庭组管理员' : '设为家庭组管理员';
    try {
      const res = await fetchWithAuth(`/api/v1/family/members/${member.id}/role`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role: nextRole }),
      });
      const data = await res.json();
      if (res.ok) {
        showToast(tx(data.message || `已成功${actionDesc}`), 'success');
        fetchFamilyInfo();
        fetchSystemUsers();
        fetchSharesMatrix();
      } else {
        showToast(tx(data.detail || `${actionDesc}失败`), 'error');
      }
    } catch {
      showToast(tx("网络错误，请稍后重试"), 'error');
    }
  };

  // 系统管理员专享：设置或取消用户的全局系统管理员 (admin) 权限
  const handleToggleSystemAdmin = async (targetUser) => {
    const isCurrentlyAdmin = targetUser.role === 'admin';
    const nextRole = isCurrentlyAdmin ? 'member' : 'admin';
    const actionDesc = isCurrentlyAdmin ? '取消系统管理员' : '设为系统管理员';
    try {
      const res = await fetchWithAuth(`/api/v1/family/members/${targetUser.id}/role`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role: nextRole }),
      });
      const data = await res.json();
      if (res.ok) {
        showToast(tx(data.message || `已成功${actionDesc}`), 'success');
        fetchSystemUsers();
        fetchFamilyInfo();
      } else {
        showToast(tx(data.detail || `${actionDesc}失败`), 'error');
      }
    } catch {
      showToast(tx("网络错误，请稍后重试"), 'error');
    }
  };

  // 系统管理员：删除用户
  const handleDeleteMember = async () => {
    if (!deletingMember || !deleteAdminPassword) {
      showToast(tx("请输入管理员密码"), 'error');
      return;
    }
    try {
      setDeleteMemberLoading(true);
      const res = await fetchWithAuth(`/api/v1/family/members/${deletingMember.id}`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ admin_password: deleteAdminPassword }),
      });
      const data = await res.json();
      if (res.ok) {
        showToast(tx(data.message || '用户已删除'), 'success');
        setDeletingMember(null);
        setDeleteAdminPassword('');
        fetchFamilyInfo();
        fetchSystemUsers();
        fetchSystemFamilies();
        fetchSharesMatrix();
      } else {
        showToast(tx(data.detail || '删除失败'), 'error');
      }
    } catch {
      showToast(tx("网络错误，请稍后重试"), 'error');
    } finally {
      setDeleteMemberLoading(false);
    }
  };

  // 系统管理员：重置用户密码
  const handleResetMemberPassword = async (e) => {
    e.preventDefault();
    if (!resetPasswordMember) return;
    if (resetNewPassword.length < 6) {
      showToast(tx("新密码至少需要6位"), 'error');
      return;
    }
    if (resetNewPassword !== resetConfirmPassword) {
      showToast(tx("两次输入的密码不一致"), 'error');
      return;
    }
    try {
      setResetPasswordLoading(true);
      const res = await fetchWithAuth(`/api/v1/family/members/${resetPasswordMember.id}/reset-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_password: resetNewPassword }),
      });
      const data = await res.json();
      if (res.ok) {
        showToast(tx(data.message || '密码已重置'), 'success');
        setResetPasswordMember(null);
        setResetNewPassword('');
        setResetConfirmPassword('');
        fetchSystemUsers();
      } else {
        showToast(tx(data.detail || '重置失败'), 'error');
      }
    } catch {
      showToast(tx("网络错误，请稍后重试"), 'error');
    } finally {
      setResetPasswordLoading(false);
    }
  };

  const handleDeleteSystemFamily = async (famId) => {
    try {
      const res = await fetchWithAuth(`/api/v1/family/${famId}`, {
        method: 'DELETE',
      });
      const data = await res.json();
      if (res.ok) {
        showToast(tx(data.message || '家庭组已删除'), 'success');
        setDeletingSystemFamily(null);
        fetchSystemFamilies();
        fetchSystemUsers();
        fetchAvailableFamilies();
        fetchFamilyInfo();
      } else {
        showToast(tx(data.detail || '删除失败'), 'error');
      }
    } catch {
      showToast(tx("删除家庭组失败，请稍后重试"), 'error');
    }
  };

  const fetchSharesMatrix = async () => {
    try {
      setMatrixLoading(true);
      const res = await fetchWithAuth('/api/v1/accounts/shares/matrix');
      if (res.ok) {
        const json = await res.json();
        setSharesMatrix(json);
      }
    } catch {
      showToast(tx("获取账户共享矩阵失败"), 'error');
    } finally {
      setMatrixLoading(false);
    }
  };

  const setTab = (tab) => {
    const p = new URLSearchParams(searchParams);
    p.set('tab', tab);
    setSearchParams(p);
  };

  useEffect(() => {
    fetchFamilyInfo();
  }, [user]);

  useEffect(() => {
    if (activeTab === 'family') {
      fetchFamilyInfo();
    }
    if (activeTab === 'system_users') {
      fetchSystemUsers();
      fetchFamilyInfo();
    }
    if (activeTab === 'system_families') {
      fetchSystemFamilies();
      fetchFamilyInfo();
    }
    if (activeTab === 'accounts') {
      fetchSharesMatrix();
    }
    if (activeTab === 'categories') {
      fetchCategories();
    }
    if (activeTab === 'tags') {
      fetchTags();
    }
  }, [activeTab]);

  const handleUpdateMatrixShare = async (accountId, memberUserId, permission, shared) => {
    try {
      const res = await fetchWithAuth(`/api/v1/accounts/${accountId}/shares`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          members: [{
            user_id: memberUserId,
            permission,
            shared,
          }]
        }),
      });
      if (res.ok) {
        showToast(tx("共享权限已更新"), 'success');
        fetchSharesMatrix();
      } else {
        showToast(tx("更新失败"), 'error');
      }
    } catch {
      showToast(tx("网络错误"), 'error');
    }
  };

  // Fetch SSO Providers
  const fetchSsoProviders = async () => {
    setSsoLoading(true);
    try {
      const res = await fetchWithAuth('/api/v1/auth/sso/admin/providers');
      if (res.ok) {
        const data = await res.json();
        setSsoProviders(data.providers || []);
      }
    } catch (err) {
      console.error('Failed to fetch SSO providers', err);
    } finally {
      setSsoLoading(false);
    }
  };

  useEffect(() => {
    if (activeTab === 'oidc' && isSuperAdmin) {
      fetchSsoProviders();
    }
  }, [activeTab, isSuperAdmin]);

  // API Keys Actions
  const fetchApiKeys = async () => {
    setApiKeysLoading(true);
    try {
      const res = await fetchWithAuth('/api/v1/api-keys');
      if (res.ok) {
        const data = await res.json();
        setApiKeys(Array.isArray(data) ? data : []);
      }
    } catch (err) {
      console.error('Failed to fetch api keys', err);
      showToast(tx("获取 API 密钥列表失败"), 'error');
    } finally {
      setApiKeysLoading(false);
    }
  };

  useEffect(() => {
    if (activeTab === 'apikeys') {
      fetchApiKeys();
    }
  }, [activeTab]);

  const handleCreateApiKey = async (e) => {
    e.preventDefault();
    if (!apiKeyName.trim()) {
      showToast(tx("请输入密钥用途描述"), 'warning');
      return;
    }
    setCreateApiKeyLoading(true);
    try {
      const body = {
        name: apiKeyName.trim(),
        expires_in_days: apiKeyExpiresDays === 'forever' ? null : parseInt(apiKeyExpiresDays, 10),
      };
      const res = await fetchWithAuth('/api/v1/api-keys', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        const data = await res.json();
        setNewlyCreatedKey(data);
        showToast(tx("API Key 创建成功！请妥善保存"), 'success');
        setApiKeyName('');
        setApiKeyExpiresDays('365');
        fetchApiKeys();
      } else {
        const err = await res.json().catch(() => ({}));
        showToast(tx(err.detail || '创建 API Key 失败'), 'error');
      }
    } catch {
      showToast(tx("网络请求异常"), 'error');
    } finally {
      setCreateApiKeyLoading(false);
    }
  };

  const handleDeleteApiKey = async (keyId) => {
    if (!window.confirm(tx("确定要撤销并删除此 API Key 吗？删除后所有使用该密钥的自动化脚本与快捷指令将立即失效！"))) {
      return;
    }
    setDeletingKeyId(keyId);
    try {
      const res = await fetchWithAuth(`/api/v1/api-keys/${keyId}`, {
        method: 'DELETE',
      });
      if (res.ok) {
        showToast(tx("API Key 已成功撤销"), 'success');
        fetchApiKeys();
      } else {
        showToast(tx("撤销失败"), 'error');
      }
    } catch {
      showToast(tx("网络错误"), 'error');
    } finally {
      setDeletingKeyId(null);
    }
  };

  // Language change
  const handleLanguageChange = async (lang) => {
    try {
      await setLanguage(lang);
      showToast(tx(lang === 'zh' ? '语言已切换为简体中文' : 'Language set to English'), 'success');
    } catch { showToast(tx("Could not save your language. Please try again."), 'error'); }
  };

  // Avatar upload
  const handleAvatarUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      await uploadAvatar(file);
      setAvatarKey((k) => k + 1);
      if (refreshUser) await refreshUser();
      showToast(tx("头像已成功更新！"), 'success');
    } catch (err) {
      showToast(tx(err.message), 'error');
    }
  };

  // Profile update (名字、昵称、邮箱、密码)
  const handleUpdateProfile = async (e) => {
    e.preventDefault();
    if (profileNewPassword && profileNewPassword !== profileConfirmPassword) {
      showToast(tx("两次输入的新密码不一致"), 'error');
      return;
    }
    if (profileNewPassword && !profileCurrentPassword) {
      showToast(tx("修改密码时必须输入当前原密码"), 'error');
      return;
    }

    setProfileLoading(true);
    try {
      const payload = {
        username: profileUsername.trim(),
        display_name: profileDisplayName.trim(),
        email: profileEmail.trim(),
      };
      if (profileNewPassword) {
        payload.current_password = profileCurrentPassword;
        payload.new_password = profileNewPassword;
      }

      const res = await fetchWithAuth(`${API_BASE}/auth/profile`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        showToast(tx("个人资料已成功保存！"), 'success');
        if (refreshUser) await refreshUser();
        setProfileCurrentPassword('');
        setProfileNewPassword('');
        setProfileConfirmPassword('');
      } else {
        const err = await res.json().catch(() => ({}));
        showToast(tx(err.detail || '保存个人资料失败'), 'error');
      }
    } catch (err) {
      console.error('Failed to update profile', err);
      showToast(tx("网络请求错误，请稍后重试"), 'error');
    } finally {
      setProfileLoading(false);
    }
  };

  // Open modal for creating new OIDC Provider
  const handleOpenCreateOidc = () => {
    setEditingOidcProvider(null);
    setOidcForm({
      name: '',
      label: '',
      issuer: '',
      client_id: '',
      client_secret: '',
      enabled: true,
      allow_jit: true,
      allowed_domains: '',
    });
    setShowAddOidcModal(true);
  };

  // Open modal for editing existing OIDC Provider
  const handleOpenEditOidc = (provider) => {
    setEditingOidcProvider(provider);
    const domains = (provider.settings?.allowed_domains || []).join(', ');
    setOidcForm({
      name: provider.name,
      label: provider.label,
      issuer: provider.issuer,
      client_id: provider.client_id,
      client_secret: '', // 留空代表不修改原密钥
      enabled: provider.enabled !== false,
      allow_jit: provider.settings?.allow_jit !== false,
      allowed_domains: domains,
    });
    setShowAddOidcModal(true);
  };

  // Toggle OIDC Provider enabled/disabled
  const handleToggleOidcEnabled = async (provider) => {
    try {
      const newEnabled = !provider.enabled;
      const res = await fetchWithAuth(`/api/v1/auth/sso/providers/${provider.name}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: newEnabled }),
      });
      if (res.ok) {
        showToast(tx("提供商 \"{p0}\" 已{p1}", {p0: (provider.label), p1: (newEnabled ? '启用' : '禁用')}), 'success');
        fetchSsoProviders();
      } else {
        showToast(tx("状态更新失败"), 'error');
      }
    } catch {
      showToast(tx("网络请求失败"), 'error');
    }
  };

  // Save (Create or Update) OIDC Provider
  const handleSaveOidcProvider = async (e) => {
    e.preventDefault();
    try {
      const domains = oidcForm.allowed_domains
        .split(',')
        .map((d) => d.trim())
        .filter(Boolean);

      const isEdit = Boolean(editingOidcProvider);
      const url = isEdit
        ? `/api/v1/auth/sso/providers/${editingOidcProvider.name}`
        : '/api/v1/auth/sso/providers';
      const method = isEdit ? 'PUT' : 'POST';

      const payload = {
        name: oidcForm.name.toLowerCase().trim(),
        label: oidcForm.label.trim(),
        issuer: oidcForm.issuer.trim(),
        client_id: oidcForm.client_id.trim(),
        enabled: oidcForm.enabled,
        settings: {
          button_text: oidcForm.label.trim(),
          allow_jit: oidcForm.allow_jit,
          allowed_domains: domains,
          default_role: 'member',
        },
      };

      if (oidcForm.client_secret && oidcForm.client_secret.trim()) {
        payload.client_secret = oidcForm.client_secret.trim();
      } else if (!isEdit) {
        showToast(tx("新建提供商必须填写 Client Secret"), 'error');
        return;
      }

      const res = await fetchWithAuth(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        showToast(tx(isEdit ? 'OIDC SSO 提供商已更新' : 'OIDC SSO 提供商已创建'), 'success');
        setShowAddOidcModal(false);
        setEditingOidcProvider(null);
        fetchSsoProviders();
      } else {
        const err = await res.json().catch(() => ({}));
        showToast(tx(err.detail || '保存失败'), 'error');
      }
    } catch {
      showToast(tx("请求失败，请检查参数"), 'error');
    }
  };

  // Delete OIDC Provider
  const handleDeleteOidc = async (name) => {
    if (!window.confirm(tx("确定要移除 SSO 提供商 \"{p0}\" 吗？", {p0: (name)}))) return;
    try {
      const res = await fetchWithAuth(`/api/v1/auth/sso/providers/${name}`, {
        method: 'DELETE',
      });
      if (res.ok) {
        showToast(tx("SSO 提供商已删除"), 'success');
        fetchSsoProviders();
      }
    } catch {
      showToast(tx("删除失败"), 'error');
    }
  };

  return (
    <div className="max-w-6xl mx-auto pb-12">
      {/* ── Top Header & Breadcrumb ── */}
      <div className="mb-6 flex items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-xs text-zinc-500 mb-1">
            <Link to="/" className="hover:text-zinc-900 dark:hover:text-white transition-colors">
              {t('nav.home', tx("Home"))}
            </Link>
            <span>/</span>
            {hasTab ? (
              <>
                <button
                  type="button"
                  onClick={handleBackToSettingsMenu}
                  className="hover:text-zinc-900 dark:hover:text-white transition-colors cursor-pointer"
                >
                  {t('settings.title', tx("Settings"))}
                </button>
                <span>/</span>
                <span className="font-semibold text-zinc-900 dark:text-zinc-100">
                  {currentTabTitle}
                </span>
              </>
            ) : (
              <span className="font-semibold text-zinc-900 dark:text-zinc-100">
                {t('settings.title', tx("Settings"))}
              </span>
            )}
          </div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
            <span className="hidden lg:inline">{t('settings.title', tx("Settings"))}</span>
            <span className="lg:hidden">{hasTab ? currentTabTitle : t('settings.title', tx("Settings"))}</span>
          </h1>
        </div>

        <div className="flex items-center gap-2">
          {/* 移动端子页面时专属的“返回”按钮 */}
          {hasTab && (
            <button
              type="button"
              onClick={handleBackToSettingsMenu}
              className="lg:hidden inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-zinc-100 hover:bg-zinc-200 dark:bg-zinc-800 dark:hover:bg-zinc-700 text-zinc-700 dark:text-zinc-200 transition-colors cursor-pointer shadow-2xs"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
              <span>{tx("返回")}</span>
            </button>
          )}

          {/* 桌面端始终显示返回看板；移动端仅在主目录时显示返回看板 */}
          <Link
            to="/"
            className={`${hasTab ? 'hidden lg:inline-flex' : 'inline-flex'} items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-zinc-100 hover:bg-zinc-200 dark:bg-zinc-800 dark:hover:bg-zinc-700 text-zinc-700 dark:text-zinc-200 transition-colors shadow-2xs`}
          >
            <ChevronLeft className="w-3.5 h-3.5" />
            <span>{t('settings.back', tx("Back"))}</span>
            <kbd className="hidden sm:inline-block ml-1 px-1.5 py-0.5 text-[11px] font-mono bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded shadow-2xs">
              ESC
            </kbd>
          </Link>
        </div>
      </div>

      {/* ── Main Two-Column Layout (Sure Style) ── */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-8 items-start">
        {/* Left Sub-Sidebar (Sure Exact Settings Menu) */}
        <aside className={`${hasTab ? 'hidden lg:block' : 'block'} lg:col-span-1 space-y-6`}>
          {/* General Section */}
          <div className="space-y-1">
            <span className="text-xs font-bold text-zinc-400 dark:text-zinc-500 tracking-wider uppercase px-3 block">
              {t('settings.general', tx("General"))}
            </span>
            {[
              { id: 'profile', label: t('settings.profile', tx("Profile Info")), icon: User },
              { id: 'preferences', label: t('settings.preferences', tx("Preferences")), icon: Sliders },
              { id: 'accounts', label: '账户管理', icon: Layers },
              { id: 'family', label: '家庭组与成员', icon: Users },
            ].map((tab) => {
              const Icon = tab.icon;
              const isCurrent = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setTab(tab.id)}
                  className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-xl text-sm font-medium transition-all cursor-pointer ${
                    isCurrent
                      ? 'lg:bg-zinc-100 lg:dark:bg-zinc-800 lg:text-zinc-900 lg:dark:text-white lg:font-semibold lg:shadow-xs text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800/50'
                      : 'text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800/50 hover:text-zinc-900 dark:hover:text-zinc-200'
                  }`}
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <Icon className={`w-4.5 h-4.5 ${isCurrent ? 'lg:text-zinc-900 lg:dark:text-white text-zinc-500 dark:text-zinc-400' : 'text-zinc-400'}`} />
                    <span className="truncate">{tx(tab.label)}</span>
                  </div>
                  <ChevronRight className="w-4.5 h-4.5 text-zinc-400 shrink-0 lg:hidden" />
                </button>
              );
            })}
          </div>

          {/* Categories & Tags Section */}
          <div className="space-y-1">
            <span className="text-xs font-bold text-zinc-400 dark:text-zinc-500 tracking-wider uppercase px-3 block">{tx("记账与分类体系")}</span>
            <button
              data-testid="tab-categories"
              onClick={() => setTab('categories')}
              className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-xl text-sm font-medium transition-all cursor-pointer ${
                activeTab === 'categories'
                  ? 'lg:bg-zinc-100 lg:dark:bg-zinc-800 lg:text-zinc-900 lg:dark:text-white lg:font-semibold lg:shadow-xs text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800/50'
                  : 'text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800/50 hover:text-zinc-900 dark:hover:text-zinc-200'
              }`}
            >
              <div className="flex items-center gap-2.5 min-w-0">
                <FolderTree className={`w-4.5 h-4.5 ${activeTab === 'categories' ? 'lg:text-zinc-900 lg:dark:text-white text-zinc-500 dark:text-zinc-400' : 'text-zinc-400'}`} />
                <span className="truncate">{tx("分类管理")}</span>
              </div>
              <ChevronRight className="w-4.5 h-4.5 text-zinc-400 shrink-0 lg:hidden" />
            </button>
            <button
              data-testid="tab-tags"
              onClick={() => setTab('tags')}
              className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-xl text-sm font-medium transition-all cursor-pointer ${
                activeTab === 'tags'
                  ? 'lg:bg-zinc-100 lg:dark:bg-zinc-800 lg:text-zinc-900 lg:dark:text-white lg:font-semibold lg:shadow-xs text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800/50'
                  : 'text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800/50 hover:text-zinc-900 dark:hover:text-zinc-200'
              }`}
            >
              <div className="flex items-center gap-2.5 min-w-0">
                <TagIcon className={`w-4.5 h-4.5 ${activeTab === 'tags' ? 'lg:text-zinc-900 lg:dark:text-white text-zinc-500 dark:text-zinc-400' : 'text-zinc-400'}`} />
                <span className="truncate">{tx("标签管理")}</span>
              </div>
              <ChevronRight className="w-4.5 h-4.5 text-zinc-400 shrink-0 lg:hidden" />
            </button>
          </div>

          {/* Automations & Rules Section */}
          <div className="space-y-1">
            <span className="text-xs font-bold text-zinc-400 dark:text-zinc-500 tracking-wider uppercase px-3 block">
              {t('settings.rules', tx("Rules & Automations"))}
            </span>
            <button
              onClick={() => setTab('rules')}
              className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-xl text-sm font-medium transition-all cursor-pointer ${
                activeTab === 'rules'
                  ? 'lg:bg-zinc-100 lg:dark:bg-zinc-800 lg:text-zinc-900 lg:dark:text-white lg:font-semibold lg:shadow-xs text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800/50'
                  : 'text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800/50 hover:text-zinc-900 dark:hover:text-zinc-200'
              }`}
            >
              <div className="flex items-center gap-2.5 min-w-0">
                <SlidersHorizontal className={`w-4.5 h-4.5 ${activeTab === 'rules' ? 'lg:text-zinc-900 lg:dark:text-white text-zinc-500 dark:text-zinc-400' : 'text-zinc-400'}`} />
                <span className="truncate">{t('settings.rules', tx("Rules & Automations"))}</span>
              </div>
              <ChevronRight className="w-4.5 h-4.5 text-zinc-400 shrink-0 lg:hidden" />
            </button>
          </div>

          {/* Advanced Section */}
          <div className="space-y-1">
            <span className="text-xs font-bold text-zinc-400 dark:text-zinc-500 tracking-wider uppercase px-3 block">
              {t('settings.advanced', tx("高级设置"))}
            </span>
            <button
              onClick={() => setTab('hosting')}
              className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-xl text-sm font-medium transition-all cursor-pointer ${
                activeTab === 'hosting'
                  ? 'lg:bg-zinc-100 lg:dark:bg-zinc-800 lg:text-zinc-900 lg:dark:text-white lg:font-semibold lg:shadow-xs text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800/50'
                  : 'text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800/50 hover:text-zinc-900 dark:hover:text-zinc-200'
              }`}
            >
              <div className="flex items-center gap-2.5 min-w-0">
                <Sparkles className={`w-4.5 h-4.5 ${activeTab === 'hosting' ? 'lg:text-zinc-900 lg:dark:text-white text-zinc-500 dark:text-zinc-400' : 'text-zinc-400'}`} />
                <span className="truncate">{t('settings.hosting', tx("Self-Hosting & AI"))}</span>
              </div>
              <ChevronRight className="w-4.5 h-4.5 text-zinc-400 shrink-0 lg:hidden" />
            </button>
            <button
              data-testid="tab-apikeys"
              onClick={() => setTab('apikeys')}
              className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-xl text-sm font-medium transition-all cursor-pointer ${
                activeTab === 'apikeys'
                  ? 'lg:bg-zinc-100 lg:dark:bg-zinc-800 lg:text-zinc-900 lg:dark:text-white lg:font-semibold lg:shadow-xs text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800/50'
                  : 'text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800/50 hover:text-zinc-900 dark:hover:text-zinc-200'
              }`}
            >
              <div className="flex items-center gap-2.5 min-w-0">
                <Key className={`w-4.5 h-4.5 ${activeTab === 'apikeys' ? 'lg:text-zinc-900 lg:dark:text-white text-zinc-500 dark:text-zinc-400' : 'text-zinc-400'}`} />
                <span className="truncate">{tx("API 密钥 (API Keys)")}</span>
              </div>
              <ChevronRight className="w-4.5 h-4.5 text-zinc-400 shrink-0 lg:hidden" />
            </button>
            <button
              onClick={() => setTab('data')}
              className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-xl text-sm font-medium transition-all cursor-pointer ${
                activeTab === 'data'
                  ? 'lg:bg-zinc-100 lg:dark:bg-zinc-800 lg:text-zinc-900 lg:dark:text-white lg:font-semibold lg:shadow-xs text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800/50'
                  : 'text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800/50 hover:text-zinc-900 dark:hover:text-zinc-200'
              }`}
            >
              <div className="flex items-center gap-2.5 min-w-0">
                <Database className={`w-4.5 h-4.5 ${activeTab === 'data' ? 'lg:text-zinc-900 lg:dark:text-white text-zinc-500 dark:text-zinc-400' : 'text-zinc-400'}`} />
                <span className="truncate">{t('settings.data', tx("Data & Backup"))}</span>
              </div>
              <ChevronRight className="w-4.5 h-4.5 text-zinc-400 shrink-0 lg:hidden" />
            </button>
          </div>

          {/* 超级管理员专属系统管理分组 */}
          {isSuperAdmin && (
            <div className="space-y-1 pt-3 border-t border-purple-100 dark:border-purple-900/40">
              <span className="text-xs font-bold text-purple-700 dark:text-purple-400 tracking-wider uppercase px-3 block flex items-center gap-1.5">
                <Shield className="w-4 h-4 text-purple-600 dark:text-purple-400" /> {tx("系统管理 (管理员专享)")}</span>
              <button
                data-testid="tab-system-users"
                onClick={() => setTab('system_users')}
                className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-xl text-sm font-medium transition-all cursor-pointer ${
                  activeTab === 'system_users'
                    ? 'lg:bg-purple-100 lg:dark:bg-purple-950/70 lg:text-purple-950 lg:dark:text-purple-100 lg:font-semibold lg:shadow-xs lg:border lg:border-purple-200 lg:dark:border-purple-800 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800/50'
                    : 'text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800/50 hover:text-zinc-900 dark:hover:text-zinc-200'
                }`}
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <Users className={`w-4.5 h-4.5 ${activeTab === 'system_users' ? 'lg:text-purple-600 lg:dark:text-purple-300 text-zinc-400' : 'text-zinc-400'}`} />
                  <span className="truncate">{tx("系统用户管理")}</span>
                </div>
                <ChevronRight className="w-4.5 h-4.5 text-purple-400 shrink-0 lg:hidden" />
              </button>
              <button
                data-testid="tab-system-families"
                onClick={() => setTab('system_families')}
                className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-xl text-sm font-medium transition-all cursor-pointer ${
                  activeTab === 'system_families'
                    ? 'lg:bg-purple-100 lg:dark:bg-purple-950/70 lg:text-purple-950 lg:dark:text-purple-100 lg:font-semibold lg:shadow-xs lg:border lg:border-purple-200 lg:dark:border-purple-800 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800/50'
                    : 'text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800/50 hover:text-zinc-900 dark:hover:text-zinc-200'
                }`}
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <Building2 className={`w-4.5 h-4.5 ${activeTab === 'system_families' ? 'lg:text-purple-600 lg:dark:text-purple-300 text-zinc-400' : 'text-zinc-400'}`} />
                  <span className="truncate">{tx("全局家庭组管理")}</span>
                </div>
                <ChevronRight className="w-4.5 h-4.5 text-purple-400 shrink-0 lg:hidden" />
              </button>
              <button
                data-testid="tab-oidc"
                onClick={() => setTab('oidc')}
                className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-xl text-sm font-medium transition-all cursor-pointer ${
                  activeTab === 'oidc'
                    ? 'lg:bg-purple-100 lg:dark:bg-purple-950/70 lg:text-purple-950 lg:dark:text-purple-100 lg:font-semibold lg:shadow-xs lg:border lg:border-purple-200 lg:dark:border-purple-800 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800/50'
                    : 'text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800/50 hover:text-zinc-900 dark:hover:text-zinc-200'
                }`}
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <KeyRound className={`w-4.5 h-4.5 ${activeTab === 'oidc' ? 'lg:text-purple-600 lg:dark:text-purple-300 text-zinc-400' : 'text-zinc-400'}`} />
                  <span className="truncate">{t('settings.oidc', tx("单点登录 (OIDC/SSO)"))}</span>
                </div>
                <ChevronRight className="w-4.5 h-4.5 text-purple-400 shrink-0 lg:hidden" />
              </button>
            </div>
          )}

          {/* 退出登录操作项 */}
          <div className="pt-3 border-t border-zinc-200/80 dark:border-zinc-800">
            <button
              type="button"
              data-testid="settings-sidebar-logout-btn"
              onClick={() => {
                logout();
                showToast(tx("已安全退出登录"), 'info');
              }}
              className="w-full flex items-center gap-2.5 px-3.5 py-2.5 rounded-xl text-sm font-semibold text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/40 transition-colors cursor-pointer"
            >
              <LogOut className="w-4.5 h-4.5" />
              <span>{tx("退出登录")}</span>
            </button>
          </div>
        </aside>

        {/* Right Main Content Pane (Sure Card Sections) */}
        <main className={`${!hasTab ? 'hidden lg:block' : 'block'} lg:col-span-3 space-y-6`}>
          {/* ══════════════════════════════════════════════════════════════ */}
          {/* TAB: CATEGORIES (交易分类管理体系)                             */}
          {/* ══════════════════════════════════════════════════════════════ */}
          {activeTab === 'categories' && (
            <div className="space-y-4 sm:space-y-6">
              <div className="bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 rounded-2xl p-3.5 sm:p-6 shadow-xs space-y-4 sm:space-y-6">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-zinc-100 dark:border-zinc-800 gap-3">
                  <div>
                    <h2 className="text-base font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
                      <FolderTree className="w-5 h-5 text-indigo-500" />
                      <span>{tx("交易分类管理")}</span>
                    </h2>
                    <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">{tx("维护家庭记账核心分类体系。每笔交易仅归属一个核心分类。")}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      data-testid="create-category-btn"
                      onClick={handleOpenCreateCategory}
                      className="px-3.5 py-1.5 rounded-lg bg-zinc-900 hover:bg-zinc-800 dark:bg-white dark:hover:bg-zinc-100 text-white dark:text-zinc-900 text-xs font-bold transition shadow-2xs flex items-center gap-1.5 cursor-pointer"
                    >
                      <Plus className="w-3.5 h-3.5" />
                      <span>{tx("新建分类")}</span>
                    </button>
                    <button
                      type="button"
                      onClick={fetchCategories}
                      disabled={categoriesLoading}
                      className="px-3 py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-700 text-xs font-semibold text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition shadow-2xs cursor-pointer"
                    >
                      {categoriesLoading ? tx("刷新中...") : tx("刷新")}
                    </button>
                  </div>
                </div>

                {/* 支出分类 / 收入分类 / 全部 切换 Pill */}
                <div className="flex items-center gap-1.5 p-1 bg-zinc-100 dark:bg-zinc-800/80 rounded-xl w-fit">
                  <button
                    type="button"
                    onClick={() => setCategoryFilterType('expense')}
                    className={`px-3 py-1.5 rounded-lg text-xs font-bold transition cursor-pointer flex items-center gap-1.5 ${
                      categoryFilterType === 'expense'
                        ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-2xs'
                        : 'text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300'
                    }`}
                  >
                    <span>{tx("支出分类")}</span>
                    <span className="text-[11px] px-1.5 py-0.5 rounded-full bg-zinc-200/70 dark:bg-zinc-600">
                      {expenseCategoryCount}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setCategoryFilterType('income')}
                    className={`px-3 py-1.5 rounded-lg text-xs font-bold transition cursor-pointer flex items-center gap-1.5 ${
                      categoryFilterType === 'income'
                        ? 'bg-white dark:bg-zinc-700 text-emerald-600 dark:text-emerald-400 shadow-2xs'
                        : 'text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300'
                    }`}
                  >
                    <span>{tx("收入分类")}</span>
                    <span className="text-[11px] px-1.5 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300">
                      {incomeCategoryCount}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setCategoryFilterType('all')}
                    className={`px-3 py-1.5 rounded-lg text-xs font-bold transition cursor-pointer flex items-center gap-1.5 ${
                      categoryFilterType === 'all'
                        ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-2xs'
                        : 'text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300'
                    }`}
                  >
                    <span>{tx("全部")}</span>
                    <span className="text-[11px] px-1.5 py-0.5 rounded-full bg-zinc-200/70 dark:bg-zinc-600">
                      {categories.length}
                    </span>
                  </button>
                </div>

                {categoriesLoading && categories.length === 0 ? (
                  <div className="py-12 text-center text-xs text-zinc-400 flex items-center justify-center gap-2">
                    <div className="w-5 h-5 border-2 border-zinc-900 dark:border-white border-t-transparent rounded-full animate-spin" />
                    <span>{tx("正在拉取分类列表...")}</span>
                  </div>
                ) : filteredCategories.length === 0 ? (
                  <div className="py-12 text-center text-xs text-zinc-400">{tx("该分类类型下暂无分类，可点击右上角新建")}</div>
                ) : (
                  <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
                    {filteredCategories.map((c) => (
                      <div
                        key={c.id}
                        data-testid={`category-card-${c.id}`}
                        className="group flex items-center justify-between p-3.5 rounded-xl border border-zinc-200/80 dark:border-zinc-800 bg-zinc-50/60 dark:bg-zinc-800/40 hover:border-zinc-300 dark:hover:border-zinc-700 transition"
                      >
                        <div className="flex items-center gap-3 min-w-0">
                          <span className="w-9 h-9 rounded-xl flex items-center justify-center text-lg bg-white dark:bg-zinc-800 shadow-2xs border border-zinc-200/60 dark:border-zinc-700/60 shrink-0">
                            {c.icon || '📦'}
                          </span>
                          <div className="min-w-0">
                            <div className="flex items-center gap-1.5">
                              <span
                                className="w-2 h-2 rounded-full shrink-0"
                                style={{ backgroundColor: c.color || '#6366f1' }}
                              />
                              <span className="text-xs font-bold text-zinc-900 dark:text-white truncate">
                                {categoryLabel(c.name)}
                              </span>
                              <span
                                className={`text-[11px] px-1.5 py-0.2 rounded font-medium ${
                                  c.category_type === 'income'
                                    ? 'bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400'
                                    : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-500 dark:text-zinc-400'
                                }`}
                              >
                                {c.category_type === 'income' ? tx("收入") : tx("支出")}
                              </span>
                            </div>
                            <span className="text-[11px] text-zinc-400 font-mono block mt-0.5">
                              {c.transaction_count || 0} {tx("笔交易")}</span>
                          </div>
                        </div>
                        <div className="flex items-center gap-1 opacity-80 group-hover:opacity-100 transition shrink-0 ml-2">
                          <button
                            type="button"
                            title={tx("编辑分类")}
                            data-testid={`edit-category-btn-${c.id}`}
                            onClick={() => handleOpenEditCategory(c)}
                            className="p-1.5 rounded-lg text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-200/60 dark:hover:bg-zinc-700/60 cursor-pointer"
                          >
                            <Edit2 className="w-3.5 h-3.5" />
                          </button>
                          <button
                            type="button"
                            title={tx("删除分类")}
                            data-testid={`delete-category-btn-${c.id}`}
                            onClick={() => setDeletingCategory(c)}
                            className="p-1.5 rounded-lg text-zinc-400 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/40 cursor-pointer"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ══════════════════════════════════════════════════════════════ */}
          {/* TAB: TAGS (交易多维标签管理体系)                               */}
          {/* ══════════════════════════════════════════════════════════════ */}
          {activeTab === 'tags' && (
            <div className="space-y-4 sm:space-y-6">
              <div className="bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 rounded-2xl p-3.5 sm:p-6 shadow-xs space-y-4 sm:space-y-6">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-zinc-100 dark:border-zinc-800 gap-3">
                  <div>
                    <h2 className="text-base font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
                      <TagIcon className="w-5 h-5 text-indigo-500" />
                      <span>{tx("交易标签管理")}</span>
                    </h2>
                    <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">{tx("多维度交叉标记账单（如出差、双十一、宝宝、装修）。每笔交易可标记多个标签。")}</p>
                  </div>
                  <button
                    type="button"
                    onClick={fetchTags}
                    disabled={tagsLoading}
                    className="self-start sm:self-auto px-3 py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-700 text-xs font-semibold text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition shadow-2xs cursor-pointer"
                  >
                    {tagsLoading ? tx("刷新中...") : tx("刷新")}
                  </button>
                </div>

                {/* 快速新增标签行 */}
                <form
                  onSubmit={handleCreateTag}
                  className="flex flex-wrap sm:flex-nowrap items-center gap-2.5 p-3 rounded-xl bg-zinc-50 dark:bg-zinc-800/40 border border-zinc-200/80 dark:border-zinc-700/60"
                >
                  <div className="relative flex-1 min-w-[180px]">
                    <span className="absolute left-3 top-1/2 -translate-y-1/2 text-xs text-zinc-400 font-bold">#</span>
                    <input
                      type="text"
                      required
                      data-testid="new-tag-input"
                      value={newTagName}
                      onChange={(e) => setNewTagName(e.target.value)}
                      placeholder={tx("新建标签名称，如：出差、双十一、母婴")}
                      className="w-full pl-7 pr-3 py-2 text-xs rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-zinc-900 dark:text-white outline-none focus:ring-1 focus:ring-zinc-900 dark:focus:ring-white"
                    />
                  </div>

                  {/* 颜色胶囊快速选择 */}
                  <div className="flex items-center gap-1.5 px-2 py-1 bg-white dark:bg-zinc-900 rounded-lg border border-zinc-200 dark:border-zinc-700">
                    {["#71717a", "#6366f1", "#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#ec4899"].map((col) => (
                      <button
                        key={col}
                        type="button"
                        onClick={() => setNewTagColor(col)}
                        style={{ backgroundColor: col }}
                        className={`w-4 h-4 rounded-full transition-transform cursor-pointer ${
                          newTagColor === col ? 'scale-125 ring-2 ring-zinc-900 dark:ring-white ring-offset-1' : 'opacity-70 hover:opacity-100'
                        }`}
                      />
                    ))}
                  </div>

                  <button
                    type="submit"
                    data-testid="create-tag-submit-btn"
                    disabled={creatingTag || !newTagName.trim()}
                    className="px-4 py-2 rounded-lg bg-zinc-900 hover:bg-zinc-800 dark:bg-white dark:hover:bg-zinc-100 text-white dark:text-zinc-900 text-xs font-bold transition shadow-xs disabled:opacity-50 flex items-center gap-1.5 shrink-0 cursor-pointer"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    <span>{creatingTag ? tx("添加中...") : tx("添加标签")}</span>
                  </button>
                </form>

                {/* 标签网格 */}
                {tagsLoading && tagsList.length === 0 ? (
                  <div className="py-12 text-center text-xs text-zinc-400 flex items-center justify-center gap-2">
                    <div className="w-5 h-5 border-2 border-zinc-900 dark:border-white border-t-transparent rounded-full animate-spin" />
                    <span>{tx("正在读取标签体系...")}</span>
                  </div>
                ) : tagsList.length === 0 ? (
                  <div className="py-12 text-center text-xs text-zinc-400">{tx("暂未创建任何标签，您可以通过上方输入框添加首个标签。")}</div>
                ) : (
                  <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
                    {tagsList.map((tag) => {
                      const isEditingThis = editingTag?.id === tag.id;
                      return (
                        <div
                          key={tag.id}
                          data-testid={`tag-card-${tag.id}`}
                          className="flex items-center justify-between p-3 rounded-xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 hover:shadow-2xs transition"
                        >
                          {isEditingThis ? (
                            <form onSubmit={handleUpdateTag} className="flex items-center gap-1.5 flex-1 min-w-0">
                              <input
                                type="text"
                                value={editTagName}
                                data-testid={`edit-tag-input-${tag.id}`}
                                onChange={(e) => setEditTagName(e.target.value)}
                                className="w-full px-2 py-1 text-xs rounded border border-zinc-300 dark:border-zinc-600 bg-zinc-50 dark:bg-zinc-800 text-zinc-900 dark:text-white"
                              />
                              <button
                                type="submit"
                                data-testid={`save-tag-btn-${tag.id}`}
                                className="p-1 rounded text-emerald-600 hover:bg-emerald-50 cursor-pointer"
                              >
                                <Check className="w-4 h-4" />
                              </button>
                              <button
                                type="button"
                                onClick={() => setEditingTag(null)}
                                className="p-1 rounded text-zinc-400 hover:bg-zinc-100 cursor-pointer"
                              >
                                ✕
                              </button>
                            </form>
                          ) : (
                            <>
                              <div className="flex items-center gap-2 min-w-0">
                                <span
                                  className="w-2.5 h-2.5 rounded-full shrink-0"
                                  style={{ backgroundColor: tag.color || '#71717a' }}
                                />
                                <span className="text-xs font-bold text-zinc-800 dark:text-zinc-200 truncate">
                                  #{tag.name}
                                </span>
                                <span className="text-[11px] text-zinc-400 font-mono px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 shrink-0">
                                  {tag.transaction_count || 0}
                                </span>
                              </div>
                              <div className="flex items-center gap-1 shrink-0 ml-2">
                                <button
                                  type="button"
                                  title={tx("编辑标签")}
                                  data-testid={`edit-tag-btn-${tag.id}`}
                                  onClick={() => {
                                    setEditingTag(tag);
                                    setEditTagName(tag.name);
                                    setEditTagColor(tag.color || '#71717a');
                                  }}
                                  className="p-1 text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 cursor-pointer"
                                >
                                  <Edit2 className="w-3.5 h-3.5" />
                                </button>
                                <button
                                  type="button"
                                  title={tx("删除标签")}
                                  data-testid={`delete-tag-btn-${tag.id}`}
                                  onClick={() => setDeletingTag(tag)}
                                  className="p-1 text-zinc-400 hover:text-red-600 dark:hover:text-red-400 rounded hover:bg-red-50 dark:hover:bg-red-950/40 cursor-pointer"
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                </button>
                              </div>
                            </>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ══════════════════════════════════════════════════════════════ */}
          {/* TAB: FAMILY & MEMBERS (加入特定名称家庭组与成员管理)              */}
          {/* ══════════════════════════════════════════════════════════════ */}
          {activeTab === 'family' && (
            <div className="space-y-4 sm:space-y-6">
              {/* 卡片 0: 待确认的家庭组入组邀请 (收件箱通知) */}
              {receivedInvitations.length > 0 && (
                <div className="bg-linear-to-r from-blue-50 to-indigo-50 dark:from-blue-950/40 dark:to-indigo-950/40 border border-blue-200 dark:border-blue-800 rounded-2xl p-4 sm:p-5 shadow-xs space-y-3">
                  <div className="flex items-center justify-between gap-3 border-b border-blue-100 dark:border-blue-900/40 pb-3">
                    <div className="flex items-center gap-2.5">
                      <div className="w-8 h-8 rounded-xl bg-blue-600 text-white flex items-center justify-center shrink-0 shadow-xs">
                        <Inbox className="w-4 h-4" />
                      </div>
                      <div>
                        <h3 className="text-sm font-bold text-blue-950 dark:text-blue-100 flex items-center gap-1.5">
                          <span>{tx("您收到")} {receivedInvitations.length} {tx("份家庭组入组邀请")}</span>
                          <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
                        </h3>
                        <p className="text-xs text-blue-600/80 dark:text-blue-300/80">{tx("同意加入后，您名下的账户和历史流水将平稳带入家庭账本中多人协同记账。")}</p>
                      </div>
                    </div>
                  </div>

                  <div className="space-y-2.5">
                    {receivedInvitations.map((inv) => (
                      <div
                        key={inv.id}
                        className="p-3.5 bg-white dark:bg-zinc-900/80 rounded-xl border border-blue-100 dark:border-blue-900/60 flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-2xs"
                      >
                        <div className="space-y-1 min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-bold text-sm text-zinc-900 dark:text-zinc-100">
                              {inv.family_name}
                            </span>
                            <span className="px-2 py-0.5 rounded-full text-[11px] font-bold bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300">{tx("邀请人：")} {inv.inviter_display_name || inv.inviter_username}
                            </span>
                            <span className="text-[11px] text-zinc-400">
                              ({inv.members_count} {tx("位成员 · 币种")} {inv.currency})
                            </span>
                          </div>
                          {inv.message && (
                            <p className="text-xs text-zinc-600 dark:text-zinc-300 italic">
                              “{tx(inv.message)}”
                            </p>
                          )}
                          <p className="text-[11px] text-zinc-400">{tx("邀请有效至：")} {inv.expires_at ? formatDateTime(inv.expires_at) : tx("长期有效")}
                          </p>
                        </div>

                        <div className="flex items-center gap-2 shrink-0 self-end sm:self-auto">
                          <button
                            type="button"
                            disabled={invitationProcessingId === inv.id}
                            onClick={() => handleAcceptInvitation(inv.id)}
                            className="px-3.5 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-bold transition shadow-2xs flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
                          >
                            <Check className="w-3.5 h-3.5" />
                            <span>{invitationProcessingId === inv.id ? tx("正在加入...") : tx("同意加入")}</span>
                          </button>
                          <button
                            type="button"
                            disabled={invitationProcessingId === inv.id}
                            onClick={() => handleRejectInvitation(inv.id)}
                            className="px-3 py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 text-xs font-semibold transition cursor-pointer disabled:opacity-50"
                          >{tx("婉言谢绝")}</button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* 卡片 1: 当前家庭组概览 */}
              <div className="bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 rounded-2xl p-3.5 sm:p-6 shadow-xs space-y-4 sm:space-y-6">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3.5 sm:pb-4 border-b border-zinc-100 dark:border-zinc-800">
                  <div>
                    <h2 className="text-base font-bold text-zinc-900 dark:text-zinc-100">{tx("当前家庭组")}</h2>
                    <p className="text-xs text-zinc-500 mt-0.5">{tx("您当前所在的多人家庭记账协作组及基本属性")}</p>
                  </div>
                  <div className="flex items-center gap-2 self-start sm:self-auto shrink-0 w-full sm:w-auto">
                    <button
                      type="button"
                      data-testid="create-family-open-btn"
                      onClick={() => setShowCreateFamilyModal(true)}
                      className="flex-1 sm:flex-initial px-3 py-1.5 rounded-lg bg-zinc-900 hover:bg-zinc-800 dark:bg-white dark:hover:bg-zinc-100 text-white dark:text-zinc-900 text-xs font-bold transition shadow-2xs flex items-center justify-center gap-1.5 cursor-pointer whitespace-nowrap"
                    >
                      <Plus className="w-3.5 h-3.5 shrink-0" />
                      <span>{tx("新建家庭组")}</span>
                    </button>
                    <button
                      onClick={fetchFamilyInfo}
                      disabled={familyLoading}
                      className="flex-1 sm:flex-initial px-3 py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-700 text-xs font-semibold text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition shadow-2xs cursor-pointer whitespace-nowrap text-center"
                    >
                      {familyLoading ? tx("正在刷新...") : tx("刷新状态")}
                    </button>
                  </div>
                </div>

                {familyLoading && !currentFamily ? (
                  <div className="py-12 text-center text-xs text-zinc-400 flex items-center justify-center gap-2">
                    <div className="w-5 h-5 border-2 border-zinc-900 dark:border-white border-t-transparent rounded-full animate-spin" />
                    <span>{tx("正在读取家庭组详情...")}</span>
                  </div>
                ) : (
                  <div className="space-y-4">
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-3.5 sm:p-4 rounded-xl bg-zinc-50 dark:bg-zinc-800/40 border border-zinc-200/80 dark:border-zinc-700/60">
                      <div className="space-y-1">
                        <div className="flex items-center gap-2">
                          {renameMode ? (
                            <form onSubmit={handleRenameFamily} className="flex items-center gap-2">
                              <input
                                type="text"
                                value={renameValue}
                                onChange={(e) => setRenameValue(e.target.value)}
                                className="px-2.5 py-1 text-sm font-bold rounded-lg border border-zinc-300 dark:border-zinc-600 bg-white dark:bg-zinc-800 outline-none"
                              />
                              <button
                                type="submit"
                                disabled={renameLoading}
                                className="p-1.5 rounded-lg bg-zinc-900 dark:bg-white text-white dark:text-zinc-900 text-xs font-semibold"
                              >
                                <Check className="w-3.5 h-3.5" />
                              </button>
                              <button
                                type="button"
                                onClick={() => setRenameMode(false)}
                                className="p-1.5 rounded-lg border border-zinc-200 dark:border-zinc-700 text-xs"
                              >{tx("取消")}</button>
                            </form>
                          ) : (
                            <>
                              <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-100" data-testid="current-family-name">
                                {currentFamily?.name || tx("我的家庭")}
                              </h3>
                              {currentFamily?.is_owner && (
                                <button
                                  type="button"
                                  onClick={() => setRenameMode(true)}
                                  title={tx("修改家庭组名称")}
                                  className="p-1 rounded-md text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 hover:bg-zinc-200 dark:hover:bg-zinc-700 transition"
                                >
                                  <Edit2 className="w-3.5 h-3.5" />
                                </button>
                              )}
                            </>
                          )}
                          <span className="px-2 py-0.5 rounded-full text-[11px] font-bold bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300">
                            {currentFamily?.is_solo
                              ? tx("个人独立空间")
                              : currentFamily?.is_owner
                              ? tx("所有者 (Owner)")
                              : tx("成员 (Member)")}
                          </span>
                        </div>
                        <p className="text-xs text-zinc-400">{tx("本家庭默认结算货币：")} <span className="font-semibold text-zinc-700 dark:text-zinc-300">{currentFamily?.currency || 'CNY'}</span>
                        </p>
                      </div>

                      <div className="flex items-center gap-3 text-xs w-full sm:w-auto">
                        <div className="flex-1 sm:flex-initial px-3 py-1.5 rounded-lg bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 text-center">
                          <span className="text-[11px] text-zinc-400 block">{tx("家庭成员")}</span>
                          <span className="font-bold text-zinc-900 dark:text-zinc-100">
                            {currentFamily?.is_solo ? tx("仅个人") : tx("{p0} 人", {p0: (currentFamily?.members?.length || 0)})}
                          </span>
                        </div>
                        <div className="flex-1 sm:flex-initial px-3 py-1.5 rounded-lg bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 text-center">
                          <span className="text-[11px] text-zinc-400 block">{tx("关联账户")}</span>
                          <span className="font-bold text-zinc-900 dark:text-zinc-100">{currentFamily?.accounts_count || 0} {tx("个")}</span>
                        </div>
                      </div>
                    </div>

                    {/* 真正的多人家庭组操作区（无论是 Owner 还是普通成员均清晰展现对应操作） */}
                    {!currentFamily?.is_solo && (
                      <div className="pt-3 border-t border-zinc-100 dark:border-zinc-800/80 flex flex-col sm:flex-row sm:items-center justify-between gap-2.5">
                        <div>
                          <span className="text-xs font-semibold text-zinc-800 dark:text-zinc-200 block">{tx("家庭组管理与退出")}</span>
                          <span className="text-[11px] text-zinc-400">
                            {currentFamily?.can_leave
                              ? (currentFamily?.is_owner && (currentFamily?.other_admins_count > 0 || (currentFamily?.members || []).filter(m => !m.is_current_user && (m.role === 'owner' || m.role === 'admin')).length > 0)
                                  ? tx("组内存在其他管理员协同掌管，您可直接主动退出家庭组。")
                                  : tx("退出后您将恢复专属个人独立记账空间，名下个人账户与交易数据完整保留。"))
                              : (currentFamily?.is_owner
                                  ? tx("您是当前家庭组唯一的管理员，可解散家庭组，或在将其他成员设为管理员后退出当前家庭。")
                                  : tx("退出后您将恢复专属个人独立记账空间。"))}
                          </span>
                        </div>
                        <div className="flex items-center gap-2 shrink-0 self-start sm:self-auto">
                          <button
                            type="button"
                            data-testid="leave-family-open-btn"
                            onClick={handleOpenLeaveFamily}
                            className="px-3 py-1.5 rounded-lg border border-amber-200 dark:border-amber-900/60 text-amber-700 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-950/40 text-xs font-semibold transition cursor-pointer flex items-center gap-1.5"
                          >
                            <LogOut className="w-3.5 h-3.5" />
                            <span>{tx("退出家庭组")}</span>
                          </button>

                          {currentFamily?.can_dissolve && (
                            <button
                              type="button"
                              data-testid="delete-family-open-btn"
                              onClick={() => setShowDeleteFamilyModal(true)}
                              className="px-3 py-1.5 rounded-lg border border-red-200 dark:border-red-900/60 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/40 text-xs font-semibold transition cursor-pointer flex items-center gap-1.5"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                              <span>{tx("解散家庭组")}</span>
                            </button>
                          )}
                        </div>
                      </div>
                    )}

                    {/* 个人独立记账空间提示 */}
                    {currentFamily?.is_solo && (
                      <div className="pt-3 border-t border-zinc-100 dark:border-zinc-800/80 flex items-center gap-2 text-xs text-zinc-500 dark:text-zinc-400 bg-zinc-50 dark:bg-zinc-800/40 p-2.5 rounded-xl">
                        <span className="font-semibold text-zinc-700 dark:text-zinc-300">{tx("💡 个人独立空间：")}</span>
                        <span>{tx("您当前未加入任何多人家庭组（属于单人独立记账状态，无需退出）。如需多人协作，请在下方加入或创建家庭组。")}</span>
                      </div>
                    )}
                  </div>
                )}
              </div>

              <div className="bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 rounded-2xl p-6 space-y-3">
                <h2 className="text-base font-bold">{tx("加入家庭组")}</h2>
                <p className="text-xs text-zinc-500">{tx("请联系家庭管理员向您的账号发送邀请，然后在邀请列表确认加入。")}</p>
                <button type="button" onClick={() => setShowCreateFamilyModal(true)} className="px-4 py-2 rounded-xl bg-zinc-900 text-white">{tx("创建新家庭组")}</button>
              </div>

              {/* 卡片 3: 当前家庭成员列表与新增用户 */}
              <div className="bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 rounded-2xl p-3.5 sm:p-6 shadow-xs space-y-4 sm:space-y-6">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 sm:pb-4 border-b border-zinc-100 dark:border-zinc-800">
                  <div>
                    <h2 className="text-base font-bold text-zinc-900 dark:text-zinc-100">{tx("家庭组成员")}</h2>
                    <p className="text-xs text-zinc-500 mt-0.5">{tx("管理当前家庭成员。系统支持三级权限划分：系统管理员、家庭组管理员（可新增用户、管理家庭）与普通家庭成员。")}</p>
                  </div>

                  {/* 家庭组管理员或系统管理员拥有邀请已有账号与新增成员权限（仅多人家庭组可用） */}
                  {(currentFamily?.is_family_admin || currentFamily?.is_super_admin) && !currentFamily?.is_solo && (
                    <div className="flex items-center gap-2 self-start sm:self-auto shrink-0 w-full sm:w-auto">
                      <button
                        type="button"
                        data-testid="open-invite-member-modal-btn"
                        onClick={() => setShowInviteModal(true)}
                        className="flex-1 sm:flex-initial px-3 py-1.5 rounded-xl border border-blue-200 dark:border-blue-900/60 bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300 hover:bg-blue-100 dark:hover:bg-blue-900/60 text-xs font-bold transition flex items-center justify-center gap-1.5 shadow-2xs cursor-pointer whitespace-nowrap"
                      >
                        <UserPlus className="w-3.5 h-3.5 shrink-0" />
                        <span>{tx("邀请已有账号")}</span>
                      </button>
                      <button
                        type="button"
                        data-testid="open-add-member-modal-btn"
                        onClick={() => setShowAddMemberModal(true)}
                        className="flex-1 sm:flex-initial px-3.5 py-1.5 rounded-xl bg-zinc-900 hover:bg-zinc-800 dark:bg-white dark:hover:bg-zinc-100 text-white dark:text-zinc-900 text-xs font-bold transition flex items-center justify-center gap-1.5 shadow-2xs cursor-pointer whitespace-nowrap"
                      >
                        <Plus className="w-3.5 h-3.5 shrink-0" />
                        <span>{tx("新建用户")}</span>
                      </button>
                    </div>
                  )}
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {currentFamily?.is_solo || (!currentFamily?.members || currentFamily.members.length === 0) ? (
                    <div className="col-span-full py-8 px-4 text-center bg-zinc-50/80 dark:bg-zinc-800/30 rounded-xl border border-dashed border-zinc-200 dark:border-zinc-800">
                      <Users className="w-8 h-8 text-zinc-400 mx-auto mb-2 opacity-60" />
                      <p className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">{tx("当前为个人独立记账空间，暂无家庭成员")}</p>
                      <p className="text-xs text-zinc-400 mt-1 max-w-md mx-auto">{tx("您的账本处于单人独立保护状态。如需多人协同记账，请使用上方「加入特定名称的家庭组」创建新组或接受他人发出的家庭组入组邀请。")}</p>
                    </div>
                  ) : (
                    currentFamily.members.map((m) => (
                    <div
                      key={m.id}
                      className="p-3.5 rounded-xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 flex items-center justify-between gap-3 shadow-2xs relative"
                    >
                      <div className="flex items-center gap-3 min-w-0">
                        <div className="w-9 h-9 rounded-full bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center font-bold text-sm text-zinc-700 dark:text-zinc-300 shrink-0">
                          {m.username.slice(0, 2).toUpperCase()}
                        </div>
                        <div className="min-w-0">
                          <div className="flex items-center gap-1.5">
                            <span className="font-bold text-sm text-zinc-900 dark:text-zinc-100 truncate">
                              {m.display_name}
                            </span>
                            {m.is_current_user && (
                              <span className="px-1.5 py-0.5 rounded text-xs font-bold bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400">{tx("我")}</span>
                            )}
                          </div>
                          <span className="text-xs text-zinc-400 block truncate">
                            @{m.username} {m.email ? `· ${m.email}` : ''}
                          </span>
                        </div>
                      </div>

                      <div className="flex items-center gap-2 shrink-0">
                        <span className={`px-2 py-0.5 rounded-full text-xs font-semibold shrink-0 ${
                          m.role === 'super_admin' || m.role === 'admin'
                            ? 'bg-purple-100 text-purple-800 dark:bg-purple-950 dark:text-purple-300 border border-purple-200 dark:border-purple-800'
                            : m.role === 'owner' || m.role === 'family_admin'
                            ? 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300 border border-amber-200 dark:border-amber-800'
                            : 'bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300'
                        }`}>
                          {m.role === 'super_admin' || m.role === 'admin'
                            ? tx("🛡️ 系统管理员")
                            : m.role === 'owner' || m.role === 'family_admin'
                            ? tx("👑 家庭组管理员")
                            : tx("👤 家庭成员")}
                        </span>


                        {/* 三点菜单：家庭组管理员可踢人，系统管理员还可重置密码/删除 */}
                        {currentFamily?.is_family_admin && !m.is_current_user && m.role !== 'super_admin' && m.role !== 'admin' && (
                          <div className="relative">
                            <button
                              type="button"
                              onClick={() => setMemberMenuOpenId(memberMenuOpenId === m.id ? null : m.id)}
                              className="p-1.5 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 transition cursor-pointer"
                              title={tx("管理此成员")}
                            >
                              <MoreHorizontal className="w-4 h-4" />
                            </button>
                            {memberMenuOpenId === m.id && (
                              <>
                                {/* 点击外部关闭 */}
                                <div
                                  className="fixed inset-0 z-40"
                                  onClick={() => setMemberMenuOpenId(null)}
                                />
                                <div className="absolute right-0 top-full mt-1 z-50 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-xl shadow-xl py-1 min-w-[140px]">
                                  {/* 系统管理员专属：重置密码 */}
                                  {isSuperAdmin && (
                                    <button
                                      type="button"
                                      onClick={() => {
                                        setMemberMenuOpenId(null);
                                        setResetPasswordMember(m);
                                        setResetNewPassword('');
                                        setResetConfirmPassword('');
                                      }}
                                      className="w-full flex items-center gap-2 px-3 py-2 text-xs text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition cursor-pointer"
                                    >
                                      <KeyRound className="w-3.5 h-3.5 text-blue-500" /> {tx("重置密码")}</button>
                                  )}
                                  {/* 设置或取消家庭组管理员 */}
                                  <button
                                    type="button"
                                    onClick={() => {
                                      setMemberMenuOpenId(null);
                                      handleToggleMemberAdmin(m);
                                    }}
                                    className="w-full flex items-center gap-2 px-3 py-2 text-xs text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-950/40 transition cursor-pointer"
                                  >
                                    <Shield className="w-3.5 h-3.5" />
                                    {m.role === 'owner' || m.role === 'family_admin' ? tx("取消家庭组管理员") : tx("设为家庭组管理员")}
                                  </button>
                                  {/* 家庭组管理员：移出家庭组 */}
                                  <button
                                    type="button"
                                    onClick={() => {
                                      setMemberMenuOpenId(null);
                                      setKickingMember(m);
                                    }}
                                    className="w-full flex items-center gap-2 px-3 py-2 text-xs text-orange-600 dark:text-orange-400 hover:bg-orange-50 dark:hover:bg-orange-950/40 transition cursor-pointer"
                                  >
                                    <ArrowRight className="w-3.5 h-3.5" /> {tx("移出家庭组")}</button>
                                </div>
                              </>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  )))}
                </div>

                {/* 管理员专属：已发出的入组邀请管理 */}
                {(currentFamily?.is_family_admin || currentFamily?.is_super_admin) && !currentFamily?.is_solo && sentInvitations.length > 0 && (
                  <div className="pt-4 border-t border-zinc-100 dark:border-zinc-800 space-y-2.5">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold text-zinc-700 dark:text-zinc-300 flex items-center gap-1.5">
                        <Send className="w-3.5 h-3.5 text-blue-500" />
                        <span>{tx("已发出的入组邀请（")} {sentInvitations.filter(i => i.status === 'pending').length} {tx("人待确认）")}</span>
                      </span>
                      <button
                        type="button"
                        onClick={() => setShowSentInvitations(!showSentInvitations)}
                        className="text-xs font-medium text-blue-600 dark:text-blue-400 hover:underline cursor-pointer"
                      >
                        {showSentInvitations ? tx("收起列表") : tx("展开查看")}
                      </button>
                    </div>

                    {showSentInvitations && (
                      <div className="space-y-2">
                        {sentInvitations.map((inv) => (
                          <div
                            key={inv.id}
                            className="p-3 bg-zinc-50 dark:bg-zinc-800/40 rounded-xl border border-zinc-200/60 dark:border-zinc-700/60 flex items-center justify-between gap-3 text-xs"
                          >
                            <div className="min-w-0 space-y-0.5">
                              <div className="flex flex-wrap items-center gap-2">
                                <span className="font-semibold text-zinc-800 dark:text-zinc-200">
                                  @{inv.invitee_username} ({inv.invitee_display_name})
                                </span>
                                <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${
                                  inv.status === 'pending'
                                    ? 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300'
                                    : inv.status === 'accepted'
                                    ? 'bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300'
                                    : inv.status === 'rejected'
                                    ? 'bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300'
                                    : 'bg-zinc-200 text-zinc-600 dark:bg-zinc-700 dark:text-zinc-400'
                                }`}>
                                  {inv.status === 'pending'
                                    ? tx("⏳ 等待确认")
                                    : inv.status === 'accepted'
                                    ? tx("✓ 已接受")
                                    : inv.status === 'rejected'
                                    ? tx("✕ 对方婉拒")
                                    : tx("已撤回/过期")}
                                </span>
                              </div>
                              {inv.message && (
                                <p className="text-[11px] text-zinc-400 truncate">{tx("附言：")} {tx(inv.message)}</p>
                              )}
                              <p className="text-[10px] text-zinc-400">{tx("发出时间：")} {inv.created_at ? formatDateTime(inv.created_at) : '-'}
                              </p>
                            </div>

                            {inv.status === 'pending' && (
                              <button
                                type="button"
                                disabled={invitationProcessingId === inv.id}
                                onClick={() => handleCancelInvitation(inv.id)}
                                className="px-2.5 py-1 rounded-lg border border-red-200 dark:border-red-900/60 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/40 text-xs font-semibold cursor-pointer disabled:opacity-50 shrink-0"
                              >
                                {invitationProcessingId === inv.id ? tx("撤回中...") : tx("撤回邀请")}
                              </button>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ══════════════════════════════════════════════════════════════ */}
          {/* TAB: SYSTEM USERS (系统所有用户管理 - 系统管理员专享)              */}
          {/* ══════════════════════════════════════════════════════════════ */}
          {activeTab === 'system_users' && (
            <div className="space-y-4 sm:space-y-6">
              <div className="bg-white dark:bg-zinc-900 border border-purple-200 dark:border-purple-900/60 rounded-2xl p-3.5 sm:p-6 shadow-xs space-y-4 sm:space-y-6">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-purple-100 dark:border-purple-900/40 gap-4">
                  <div>
                    <h2 className="text-base font-bold text-purple-950 dark:text-purple-200 flex items-center gap-2">
                      <Users className="w-5 h-5 text-purple-600 dark:text-purple-400" />
                      <span>{tx("系统用户管理")}</span>
                      <span className="px-2 py-0.5 rounded-full text-[11px] font-bold bg-purple-100 dark:bg-purple-950 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800">{tx("系统管理员专享")}</span>
                    </h2>
                    <p className="text-xs text-zinc-500 mt-1">{tx("集中管控全系统所有注册用户及其资产归属，支持查看所属家庭、分配与收回家庭组管理员权限、强制重置用户密码及级联删除用户。")}</p>
                  </div>
                  <button
                    type="button"
                    onClick={fetchSystemUsers}
                    disabled={systemUsersLoading}
                    className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-purple-600 hover:bg-purple-700 text-white text-xs font-semibold shadow-xs transition cursor-pointer self-start sm:self-auto shrink-0 disabled:opacity-50"
                  >
                    <Users className="w-3.5 h-3.5" />
                    <span>{systemUsersLoading ? tx("正在刷新...") : tx("刷新用户列表")}</span>
                  </button>
                </div>

                {/* 概览统计指标条 */}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  <div className="p-3.5 rounded-xl bg-purple-50/50 dark:bg-purple-950/20 border border-purple-100 dark:border-purple-900/30">
                    <span className="text-[11px] text-zinc-500 block">{tx("注册用户总数")}</span>
                    <span className="text-lg font-bold text-purple-950 dark:text-purple-200 mt-0.5 block">{systemUsers.length} {tx("位")}</span>
                  </div>
                  <div className="p-3.5 rounded-xl bg-blue-50/50 dark:bg-blue-950/20 border border-blue-100 dark:border-blue-900/30">
                    <span className="text-[11px] text-zinc-500 block">{tx("系统管理员")}</span>
                    <span className="text-lg font-bold text-blue-950 dark:text-blue-200 mt-0.5 block">
                      {systemUsers.filter(u => u.is_admin).length} {tx("位")}</span>
                  </div>
                  <div className="p-3.5 rounded-xl bg-amber-50/50 dark:bg-amber-950/20 border border-amber-100 dark:border-amber-900/30">
                    <span className="text-[11px] text-zinc-500 block">{tx("家庭组主管 / 成员")}</span>
                    <span className="text-lg font-bold text-amber-950 dark:text-amber-200 mt-0.5 block">
                      {systemUsers.filter(u => !u.is_admin).length} {tx("位")}</span>
                  </div>
                </div>

                {/* 用户列表 */}
                <div className="grid grid-cols-1 divide-y divide-zinc-100 dark:divide-zinc-800 border border-zinc-200 dark:border-zinc-800 rounded-xl overflow-hidden">
                  {systemUsers.map((u) => (
                    <div
                      key={u.id}
                      className="p-4 flex flex-col md:flex-row md:items-center justify-between gap-4 bg-white dark:bg-zinc-900 hover:bg-zinc-50/60 dark:hover:bg-zinc-800/40 transition"
                    >
                      <div className="flex items-center gap-3.5 min-w-0">
                        <div className="w-10 h-10 rounded-full bg-purple-100 dark:bg-purple-950/80 border border-purple-200 dark:border-purple-900/60 flex items-center justify-center font-bold text-xs text-purple-700 dark:text-purple-300 shrink-0 shadow-xs">
                          {u.username.slice(0, 2).toUpperCase()}
                        </div>
                        <div className="min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="font-bold text-xs text-zinc-900 dark:text-zinc-100">
                              {u.display_name}
                            </span>
                            {u.is_current_user && (
                              <span className="px-1.5 py-0.5 rounded text-[11px] font-bold bg-blue-100 dark:bg-blue-950 text-blue-700 dark:text-blue-300">{tx("当前登录")}</span>
                            )}
                            <span className={`px-2 py-0.5 rounded-full text-[11px] font-bold shrink-0 ${
                              u.role === 'admin'
                                ? 'bg-purple-100 text-purple-800 dark:bg-purple-950 dark:text-purple-300 border border-purple-200 dark:border-purple-800'
                                : u.role === 'owner'
                                ? 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300 border border-amber-200 dark:border-amber-800'
                                : 'bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300'
                            }`}>
                              {tx(u.role_label)}
                            </span>
                          </div>
                          <span className="text-[11px] text-zinc-400 block mt-1">
                            @{u.username} {u.email ? `· ${u.email}` : ''} {tx("· 所属家庭:")} <strong className="text-zinc-600 dark:text-zinc-300 font-medium">{u.family_name}</strong> · {u.accounts_count} {tx("个账户")}</span>
                        </div>
                      </div>

                      <div className="flex items-center gap-2 shrink-0 self-end md:self-auto flex-wrap">
                        <button
                          type="button"
                          data-testid={`system-user-reset-pwd-${u.id}`}
                          onClick={() => {
                            setResetPasswordMember(u);
                            setResetNewPassword('');
                            setResetConfirmPassword('');
                          }}
                          className="px-2.5 py-1.5 rounded-lg border border-blue-200 dark:border-blue-900/60 text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-950/40 text-xs font-semibold transition cursor-pointer flex items-center gap-1.5"
                          title={tx("重置该用户登录密码")}
                        >
                          <KeyRound className="w-3.5 h-3.5" />
                          <span>{tx("重置密码")}</span>
                        </button>

                        {!u.is_current_user && (
                          <button
                            type="button"
                            data-testid={`system-user-toggle-admin-${u.id}`}
                            onClick={() => handleToggleSystemAdmin(u)}
                            className={`px-2.5 py-1.5 rounded-lg border text-xs font-semibold transition cursor-pointer flex items-center gap-1.5 ${
                              u.role === 'admin'
                                ? 'border-amber-200 dark:border-amber-900/60 text-amber-700 dark:text-amber-300 hover:bg-amber-50 dark:hover:bg-amber-950/40'
                                : 'border-purple-200 dark:border-purple-900/60 text-purple-700 dark:text-purple-300 hover:bg-purple-50 dark:hover:bg-purple-950/40'
                            }`}
                            title={u.role === 'admin' ? tx("取消其全局系统管理员权限") : tx("将其设为全局系统管理员")}
                          >
                            <Shield className="w-3.5 h-3.5" />
                            <span>{u.role === 'admin' ? tx("取消系统管理员") : tx("设为系统管理员")}</span>
                          </button>
                        )}

                        {!u.is_current_user && !u.is_admin && (
                          <button
                            type="button"
                            data-testid={`system-user-delete-${u.id}`}
                            onClick={() => {
                              setDeletingMember(u);
                              setDeleteAdminPassword('');
                            }}
                            className="px-2.5 py-1.5 rounded-lg border border-red-200 dark:border-red-900/60 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/40 text-xs font-semibold transition cursor-pointer flex items-center gap-1.5"
                            title={tx("系统管理员强制删除此用户及其所有数据")}
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                            <span>{tx("删除用户")}</span>
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* ══════════════════════════════════════════════════════════════ */}
          {/* TAB: SYSTEM FAMILIES (系统所有家庭组管理 - 系统管理员专享)          */}
          {/* ══════════════════════════════════════════════════════════════ */}
          {activeTab === 'system_families' && (
            <div className="space-y-4 sm:space-y-6">
              <div className="bg-white dark:bg-zinc-900 border border-purple-200 dark:border-purple-900/60 rounded-2xl p-3.5 sm:p-6 shadow-xs space-y-4 sm:space-y-6">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-purple-100 dark:border-purple-900/40 gap-4">
                  <div>
                    <h2 className="text-base font-bold text-purple-950 dark:text-purple-200 flex items-center gap-2">
                      <Building2 className="w-5 h-5 text-purple-600 dark:text-purple-400" />
                      <span>{tx("全局家庭组管理")}</span>
                      <span className="px-2 py-0.5 rounded-full text-[11px] font-bold bg-purple-100 dark:bg-purple-950 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800">{tx("系统管理员专享")}</span>
                    </h2>
                    <p className="text-xs text-zinc-500 mt-1">{tx("查看所有家庭组及其归档状态。解散后，成员恢复个人独立空间，账户与历史账务完整保留。")}</p>
                  </div>
                  <button
                    type="button"
                    onClick={fetchSystemFamilies}
                    disabled={systemFamiliesLoading}
                    className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-purple-600 hover:bg-purple-700 text-white text-xs font-semibold shadow-xs transition cursor-pointer self-start sm:self-auto shrink-0 disabled:opacity-50"
                  >
                    <Building2 className="w-3.5 h-3.5" />
                    <span>{systemFamiliesLoading ? tx("正在刷新...") : tx("刷新家庭组列表")}</span>
                  </button>
                </div>

                {/* 统计指标条 */}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  <div className="p-3.5 rounded-xl bg-purple-50/50 dark:bg-purple-950/20 border border-purple-100 dark:border-purple-900/30">
                    <span className="text-[11px] text-zinc-500 block">{tx("家庭组总数")}</span>
                    <span className="text-lg font-bold text-purple-950 dark:text-purple-200 mt-0.5 block">{systemFamilies.length} {tx("个")}</span>
                  </div>
                  <div className="p-3.5 rounded-xl bg-blue-50/50 dark:bg-blue-950/20 border border-blue-100 dark:border-blue-900/30">
                    <span className="text-[11px] text-zinc-500 block">{tx("覆盖成员总人次")}</span>
                    <span className="text-lg font-bold text-blue-950 dark:text-blue-200 mt-0.5 block">
                      {systemFamilies.reduce((acc, f) => acc + (f.members_count || 0), 0)} {tx("人")}</span>
                  </div>
                  <div className="p-3.5 rounded-xl bg-emerald-50/50 dark:bg-emerald-950/20 border border-emerald-100 dark:border-emerald-900/30">
                    <span className="text-[11px] text-zinc-500 block">{tx("托管资产账户")}</span>
                    <span className="text-lg font-bold text-emerald-950 dark:text-emerald-200 mt-0.5 block">
                      {systemFamilies.reduce((acc, f) => acc + (f.accounts_count || 0), 0)} {tx("个")}</span>
                  </div>
                </div>

                {/* 家庭组列表 */}
                <div className="grid grid-cols-1 divide-y divide-zinc-100 dark:divide-zinc-800 border border-zinc-200 dark:border-zinc-800 rounded-xl overflow-hidden">
                  {systemFamilies.map((fam) => (
                    <div
                      key={fam.id}
                      className="p-4 flex flex-col md:flex-row md:items-center justify-between gap-4 bg-white dark:bg-zinc-900 hover:bg-zinc-50/60 dark:hover:bg-zinc-800/40 transition"
                    >
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-xs text-zinc-900 dark:text-zinc-100">
                            {fam.name}
                          </span>
                          {fam.is_current && (
                            <span className="px-1.5 py-0.5 rounded text-[11px] font-bold bg-blue-100 dark:bg-blue-950 text-blue-700 dark:text-blue-300">{tx("当前所在")}</span>
                          )}
                          {fam.status === 'dissolved' && (
                            <span className="px-1.5 py-0.5 rounded text-[11px] font-bold bg-zinc-100 dark:bg-zinc-800 text-zinc-500">{tx("已解散归档")}</span>
                          )}
                          <span className="px-2 py-0.5 rounded-full text-[11px] font-bold bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400">{tx("货币:")} {fam.currency || 'CNY'}
                          </span>
                        </div>
                        <span className="text-[11px] text-zinc-400 block mt-1">{tx("管理员:")} <strong className="text-zinc-600 dark:text-zinc-300 font-medium">{fam.members_count ? fam.admin_name : tx("无")}</strong> {tx("· 成员:")} {fam.members_count} {tx("位 · 关联账户:")} {fam.accounts_count} {tx("个")}</span>
                      </div>

                      <div className="flex items-center gap-2 shrink-0 self-end md:self-auto">
                        <button
                          type="button"
                          data-testid={`system-delete-family-${fam.id}`}
                          disabled={!fam.can_dissolve}
                          onClick={() => handleDeleteSystemFamily(fam.id)}
                          className="px-3 py-1.5 rounded-lg border border-red-200 dark:border-red-900/60 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/40 text-xs font-semibold transition cursor-pointer flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
                          title={fam.status === 'dissolved' ? tx("该家庭组已解散归档") : fam.kind === 'personal' || !fam.can_dissolve ? tx("个人独立空间不能解散") : tx("解散家庭组并保留历史账务")}
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                          <span>{fam.status === 'dissolved' ? tx("已解散归档") : tx("解散家庭组")}</span>
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* ══════════════════════════════════════════════════════════════ */}
          {/* TAB 0: ACCOUNTS & SHARING (Sure Style Accounts & Sharing)      */}
          {/* ══════════════════════════════════════════════════════════════ */}
          {activeTab === 'accounts' && (
            <div className="space-y-6">
              <div className="bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 rounded-2xl p-3.5 sm:p-6 shadow-xs space-y-4 sm:space-y-6">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 sm:pb-4 border-b border-zinc-100 dark:border-zinc-800">
                  <div>
                    <h2 className="text-base font-bold text-zinc-900 dark:text-zinc-100">{tx("账户管理")}</h2>
                    <p className="text-xs text-zinc-500 mt-0.5">{tx("管理家庭各资产账户：支持编辑账户、转移所有权给其他成员、删除账户，并细粒度共享给家庭组中的成员。")}</p>
                  </div>
                  <button
                    onClick={fetchSharesMatrix}
                    disabled={matrixLoading}
                    className="self-end sm:self-auto px-3 py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-700 text-xs font-semibold text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition shadow-2xs cursor-pointer whitespace-nowrap shrink-0"
                  >
                    {matrixLoading ? tx("正在刷新...") : tx("刷新状态")}
                  </button>
                </div>

                {matrixLoading ? (
                  <div className="py-16 text-center text-xs text-zinc-400 flex items-center justify-center gap-2">
                    <div className="w-5 h-5 border-2 border-zinc-900 dark:border-white border-t-transparent rounded-full animate-spin" />
                    <span>{tx("正在读取家庭账户管理数据...")}</span>
                  </div>
                ) : !sharesMatrix || sharesMatrix.accounts?.length === 0 ? (
                  <div className="py-12 text-center text-xs text-zinc-400">{tx("暂未发现家庭账户数据")}</div>
                ) : (
                  <div className="space-y-4">
                    <div className="divide-y divide-zinc-100 dark:divide-zinc-800 border border-zinc-200/80 dark:border-zinc-800 rounded-xl bg-white dark:bg-zinc-900 shadow-2xs">
                      {sharesMatrix.accounts.map((acc) => {
                        const sharedCount = acc.members?.filter((m) => !m.is_owner && m.shared).length || 0;
                        const isMenuOpen = openAccountMenuId === acc.account_id;
                        const cfg = getAccountTypeConfig(acc);
                        const AccLogoIcon = cfg.icon;

                        return (
                          <div
                            key={acc.account_id}
                            data-testid={`settings-account-row-${acc.account_id}`}
                            onClick={() => setOpenAccountMenuId(isMenuOpen ? null : acc.account_id)}
                            className="group p-2.5 sm:p-4 flex items-center justify-between gap-2.5 sm:gap-4 hover:bg-zinc-50/70 dark:hover:bg-zinc-800/40 transition-colors cursor-pointer relative"
                          >
                            {/* 列 1：账户专属分类 Logo 与完整信息 */}
                            <div className="flex items-center gap-2.5 sm:gap-3.5 min-w-0 flex-1">
                              <div className={`w-8 h-8 sm:w-10 sm:h-10 rounded-xl border flex items-center justify-center shrink-0 group-hover:scale-105 transition-all shadow-2xs ${cfg.bgColor} ${cfg.borderColor}`}>
                                <AccLogoIcon className={`w-4 h-4 sm:w-5 sm:h-5 ${cfg.color}`} />
                              </div>
                              <div className="min-w-0 flex-1">
                                <div className="flex items-center gap-2 min-w-0">
                                  <h4 className="text-sm font-bold text-zinc-900 dark:text-zinc-100 truncate" title={acc.account_name}>
                                    {acc.account_name}
                                  </h4>
                                  <span className={`hidden sm:inline-flex px-2 py-0.5 rounded-full text-[11px] font-semibold border shrink-0 whitespace-nowrap ${cfg.badgeClass}`}>
                                    {tx(cfg.label)}
                                  </span>
                                </div>
                                <div className="flex items-center gap-1.5 sm:gap-2 text-xs text-zinc-500 dark:text-zinc-400 mt-0.5 truncate">
                                  <span className={`sm:hidden px-1.5 py-0.2 rounded text-[10px] font-medium border shrink-0 ${cfg.badgeClass}`}>
                                    {tx(cfg.label)}
                                  </span>
                                  <span className="truncate">{acc.institution_name || tx("中国招商银行")}</span>
                                  <span>·</span>
                                  <span className="font-mono shrink-0">{tx("余额:")} {formatCurrency(acc.balance ?? 0, '¥')}
                                  </span>
                                </div>
                              </div>
                            </div>

                            {/* 列 2：所有者与共享状态摘要 */}
                            <div className="hidden sm:flex items-center gap-2 shrink-0">
                              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 border border-zinc-200/60 dark:border-zinc-700/60 shrink-0 whitespace-nowrap">
                                👑 <strong className="font-semibold truncate max-w-[100px]">{acc.owner_name || tx("我")}</strong>
                              </span>

                              {sharedCount > 0 ? (
                                <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300 border border-blue-200/60 dark:border-blue-800/60 shrink-0 whitespace-nowrap">
                                  <Users className="w-3 h-3 text-blue-500" />
                                  <span>{tx("已共享")} {sharedCount} {tx("人")}</span>
                                </span>
                              ) : (
                                <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-zinc-50 dark:bg-zinc-850 text-zinc-500 dark:text-zinc-400 border border-zinc-200/50 dark:border-zinc-700/50 shrink-0 whitespace-nowrap">
                                  <Lock className="w-3 h-3 text-zinc-400" />
                                  <span>{tx("私密")}</span>
                                </span>
                              )}
                            </div>

                            {/* 列 3：三个点操作菜单 */}
                            <div className="relative shrink-0">
                              <button
                                type="button"
                                data-testid={`settings-account-menu-btn-${acc.account_id}`}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setOpenAccountMenuId(isMenuOpen ? null : acc.account_id);
                                }}
                                className={`p-2 rounded-xl transition-all cursor-pointer ${
                                  isMenuOpen
                                    ? 'bg-zinc-200 dark:bg-zinc-700 text-zinc-900 dark:text-zinc-100'
                                    : 'text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800'
                                }`}
                                title={tx("点击显示编辑/共享设置/转移/删除")}
                              >
                                <MoreHorizontal className="w-5 h-5" />
                              </button>

                              {isMenuOpen && (
                                <>
                                  <div
                                    className="fixed inset-0 z-30"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setOpenAccountMenuId(null);
                                    }}
                                  />
                                  <div
                                    data-testid={`settings-account-menu-dropdown-${acc.account_id}`}
                                    className="absolute right-0 top-full mt-1.5 w-44 rounded-xl bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 shadow-xl py-1.5 z-40 text-xs animate-in fade-in zoom-in-95 duration-100 divide-y divide-zinc-100 dark:divide-zinc-700/60"
                                    onClick={(e) => e.stopPropagation()}
                                  >
                                    <div className="px-3 py-1.5 text-[11px] font-semibold text-zinc-400 dark:text-zinc-500 truncate">
                                      {acc.account_name}
                                    </div>
                                    <div className="py-1">
                                      {acc.can_manage === true && (
                                      <button
                                        type="button"
                                        data-testid="settings-edit-account-btn"
                                        onClick={() => {
                                          setOpenAccountMenuId(null);
                                          setEditingAccount({
                                            id: acc.account_id,
                                            name: acc.account_name,
                                            institution_name: acc.institution_name,
                                            account_type: acc.account_type || 'checking',
                                            balance: acc.balance || 0,
                                            can_manage: acc.can_manage,
                                            parent_account_id: acc.parent_account_id,
                                            parent_account: acc.parent_account,
                                          });
                                        }}
                                        className="w-full text-left px-3 py-2 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-700/60 flex items-center gap-2.5 cursor-pointer transition-colors"
                                      >
                                        <Edit2 className="w-3.5 h-3.5 text-zinc-500" />
                                        <span>{tx("编辑账户")}</span>
                                      </button>
                                      )}

                                      <button
                                        type="button"
                                        data-testid="settings-share-account-btn"
                                        onClick={() => {
                                          setOpenAccountMenuId(null);
                                          setSelectedShareAccountId(acc.account_id);
                                        }}
                                        className="w-full text-left px-3 py-2 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-700/60 flex items-center gap-2.5 cursor-pointer transition-colors"
                                      >
                                        <Users className="w-3.5 h-3.5 text-indigo-500" />
                                        <span>{acc.can_manage_shares ? tx("共享设置") : tx("查看共享与个人统计设置")}</span>
                                      </button>

                                      {acc.can_manage_shares === true && (
                                      <button
                                        type="button"
                                        data-testid="settings-transfer-account-btn"
                                        onClick={() => {
                                          setOpenAccountMenuId(null);
                                          setTransferringAccount({
                                            id: acc.account_id,
                                            name: acc.account_name,
                                            owner: acc.owner_name,
                                            owner_id: acc.owner_id,
                                            can_manage_shares: acc.can_manage_shares,
                                          });
                                        }}
                                        className="w-full text-left px-3 py-2 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-700/60 flex items-center gap-2.5 cursor-pointer transition-colors"
                                      >
                                        <ArrowRightLeft className="w-3.5 h-3.5 text-blue-500" />
                                        <span>{tx("转移所有权")}</span>
                                      </button>
                                      )}
                                    </div>

                                    {acc.can_manage === true && (
                                    <div className="pt-1">
                                      <button
                                        type="button"
                                        data-testid="settings-delete-account-btn"
                                        onClick={() => {
                                          setOpenAccountMenuId(null);
                                          setDeletingAccount({
                                            id: acc.account_id,
                                            name: acc.account_name,
                                          });
                                        }}
                                        className="w-full text-left px-3 py-2 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/40 flex items-center gap-2.5 cursor-pointer transition-colors"
                                      >
                                        <Trash2 className="w-3.5 h-3.5 text-red-500" />
                                        <span>{tx("删除账户")}</span>
                                      </button>
                                    </div>
                                    )}
                                  </div>
                                </>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ══════════════════════════════════════════════════════════════ */}
          {/* TAB 1: PREFERENCES                                            */}
          {/* ══════════════════════════════════════════════════════════════ */}
          {activeTab === 'preferences' && (
            <div className="space-y-4 sm:space-y-6">
              {/* General Preferences Card */}
              <div className="bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 rounded-2xl p-3.5 sm:p-6 shadow-xs space-y-4 sm:space-y-5">
                <div>
                  <h2 className="text-base font-bold text-zinc-900 dark:text-zinc-100">
                    {t('settings.general', tx("General"))}
                  </h2>
                  <p className="text-xs text-zinc-500 mt-0.5">{tx("Configure your language, currency, and display settings")}</p>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  {/* Language Selector */}
                  <div className="space-y-1.5">
                    <label className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
                      {t('settings.language', tx("Language"))}
                    </label>
                    <select
                      value={i18n.language?.startsWith('en') ? 'en' : 'zh'}
                      onChange={(e) => handleLanguageChange(e.target.value)}
                      className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl text-sm font-medium text-zinc-900 dark:text-white outline-none focus:border-zinc-900 transition-colors"
                    >
                      <option value="zh">{tx("简体中文 (Chinese - zh)")}</option>
                      <option value="en">{tx("English (en)")}</option>
                    </select>
                  </div>

                  {/* Currency Selector */}
                  <div className="space-y-1.5">
                    <label className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
                      {t('settings.currency', tx("Family Base Currency"))}
                    </label>
                    <select
                      value={currency}
                      onChange={(e) => setCurrency(e.target.value)}
                      className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl text-sm font-medium text-zinc-900 dark:text-white outline-none focus:border-zinc-900 transition-colors"
                    >
                      {currencies.map((c) => (
                        <option key={c.code} value={c.code}>
                          {c.code} ({c.symbol})
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="space-y-1.5">
                    <label htmlFor="theme-mode" className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
                      {i18n.language?.startsWith('en') ? tx("Appearance") : tx("日间 / 夜间模式")}
                    </label>
                    <select
                      id="theme-mode"
                      data-testid="theme-mode-select"
                      value={themeMode}
                      onChange={(e) => setThemeMode(e.target.value)}
                      className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl text-sm font-medium text-zinc-900 dark:text-white outline-none focus:border-zinc-900 transition-colors"
                    >
                      <option value="light">{i18n.language?.startsWith('en') ? tx("Day (Light)") : tx("日间")}</option>
                      <option value="dark">{i18n.language?.startsWith('en') ? tx("Night (Dark)") : tx("夜间")}</option>
                      <option value="auto">{i18n.language?.startsWith('en') ? tx("Auto (System)") : tx("自动（跟随系统）")}</option>
                    </select>
                  </div>

                  {/* Date Format */}
                  <div className="space-y-1.5">
                    <label className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
                      {t('settings.dateFormat', tx("Date Format"))}
                    </label>
                    <select
                      value={dateFormat}
                      onChange={(e) => setDateFormat(e.target.value)}
                      className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl text-sm font-medium text-zinc-900 dark:text-white outline-none focus:border-zinc-900 transition-colors"
                    >
                      <option value="YYYY-MM-DD">{tx("YYYY-MM-DD (2026-09-27)")}</option>
                      <option value="MM/DD/YYYY">{tx("MM/DD/YYYY (09/27/2026)")}</option>
                      <option value="DD/MM/YYYY">{tx("DD/MM/YYYY (27/09/2026)")}</option>
                    </select>
                  </div>

                  {/* Budget Month Starts On */}
                  <div className="space-y-1.5">
                    <label className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
                      {t('settings.budgetStart', tx("Budget Month Starts On"))}
                    </label>
                    <select
                      defaultValue="1"
                      className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl text-sm font-medium text-zinc-900 dark:text-white outline-none focus:border-zinc-900 transition-colors"
                    >
                      <option value="1">{tx("1st of month")}</option>
                      <option value="5">{tx("5th of month")}</option>
                      <option value="10">{tx("10th of month (招行出账日)")}</option>
                      <option value="20">{tx("20th of month")}</option>
                      <option value="25">{tx("25th of month")}</option>
                    </select>
                  </div>

                  {/* Timezone */}
                  <div className="space-y-1.5">
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-1">
                      <label className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
                        {t('settings.timezone', tx("所在时区"))}
                      </label>
                      <span className="text-xs font-mono text-blue-600 dark:text-blue-400 font-medium">{tx("当前时区时间:")} {formatDateTime(new Date(), timezone)}
                      </span>
                    </div>
                    <select
                      value={timezone}
                      onChange={(e) => {
                        const val = e.target.value;
                        setTimezone(val);
                        localStorage.setItem('famledger_tz', val);
                        showToast(tx("已切换至时区: {p0}", {p0: (val)}), 'success');
                      }}
                      className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl text-sm font-medium text-zinc-900 dark:text-white outline-none focus:border-zinc-900 transition-colors"
                    >
                      <option value="Asia/Shanghai">{tx("(UTC+08:00) Asia/Shanghai (北京时间 / 上海)")}</option>
                      <option value="Asia/Hong_Kong">{tx("(UTC+08:00) Asia/Hong_Kong (中国香港)")}</option>
                      <option value="Asia/Taipei">{tx("(UTC+08:00) Asia/Taipei (中国台北)")}</option>
                      <option value="Asia/Singapore">{tx("(UTC+08:00) Asia/Singapore (新加坡)")}</option>
                      <option value="Asia/Tokyo">{tx("(UTC+09:00) Asia/Tokyo (东京 / 首尔)")}</option>
                      <option value="UTC">{tx("(UTC+00:00) UTC (协调世界时)")}</option>
                      <option value="Europe/London">{tx("(UTC+00:00) Europe/London (伦敦)")}</option>
                      <option value="Europe/Paris">{tx("(UTC+01:00) Europe/Paris (巴黎 / 柏林)")}</option>
                      <option value="America/New_York">{tx("(UTC-05:00) America/New_York (纽约 / 美东)")}</option>
                      <option value="America/Chicago">{tx("(UTC-06:00) America/Chicago (芝加哥 / 美中)")}</option>
                      <option value="America/Los_Angeles">{tx("(UTC-08:00) America/Los_Angeles (旧金山 / 洛杉矶)")}</option>
                      <option value="auto">{tx("🌐 自动检测系统时区 (")} {Intl.DateTimeFormat().resolvedOptions().timeZone})</option>
                    </select>
                    <p className="text-xs text-zinc-500 dark:text-zinc-400">{tx("系统数据库内所有交易时间戳均统一以 UTC+0 绝对时刻安全存储；在所有账单页面与明细中展示时，将精准按照此处选定之目标时区进行换算呈现。")}</p>
                  </div>

                  {/* Default Account Order */}
                  <div className="space-y-1.5">
                    <label className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
                      {t('settings.accountOrder', tx("Default Account Order"))}
                    </label>
                    <select
                      value={accountOrder}
                      onChange={(e) => {
                        setAccountOrder(e.target.value);
                        localStorage.setItem('famledger_acc_order', e.target.value);
                        showToast(tx("账户排序规则已更新"), 'info');
                      }}
                      className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl text-sm font-medium text-zinc-900 dark:text-white outline-none focus:border-zinc-900 transition-colors"
                    >
                      <option value="name_asc">{tx("Name (A-Z)")}</option>
                      <option value="balance_desc">{tx("Balance (High to Low)")}</option>
                      <option value="activity">{tx("Most Active")}</option>
                    </select>
                  </div>
                </div>

                {/* Privacy Mode Toggle */}
                <div className="pt-4 border-t border-zinc-100 dark:border-zinc-800 flex items-center justify-between">
                  <div>
                    <span className="text-sm font-bold text-zinc-900 dark:text-zinc-100 block">
                      {t('settings.privacyMode', tx("Privacy Mode"))}
                    </span>
                    <span className="text-xs text-zinc-500">
                      {t('settings.privacyModeDesc', tx("Blurs sensitive amounts across the interface"))}
                    </span>
                  </div>
                  <button
                    onClick={togglePrivacyMode}
                    className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                      privacyMode ? 'bg-zinc-900 dark:bg-emerald-600' : 'bg-zinc-200 dark:bg-zinc-700'
                    }`}
                  >
                    <span
                      className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                        privacyMode ? 'translate-x-6' : 'translate-x-1'
                      }`}
                    />
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* ══════════════════════════════════════════════════════════════ */}
          {/* TAB 2: OIDC / SSO (Blueprint Section 7)                       */}
          {/* ══════════════════════════════════════════════════════════════ */}
          {activeTab === 'oidc' && (
            !isSuperAdmin ? (
              <div className="bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 rounded-2xl p-6 sm:p-12 text-center space-y-4 shadow-xs animate-in fade-in duration-200">
                <div className="w-14 h-14 rounded-2xl bg-amber-50 dark:bg-amber-950/40 text-amber-600 dark:text-amber-400 flex items-center justify-center mx-auto border border-amber-200 dark:border-amber-800">
                  <Lock className="w-7 h-7" />
                </div>
                <div>
                  <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-100">{tx("权限不足：系统管理员专属功能")}</h3>
                  <p className="text-xs text-zinc-500 mt-1.5 max-w-md mx-auto leading-relaxed">{tx("OIDC / SSO 单点登录配置涉及全局身份接入与账户预配策略，仅限具备系统管理员（Admin）角色的成员查看与编辑。")}</p>
                </div>
                <div className="pt-2">
                  <button
                    onClick={() => setTab(null)}
                    className="px-4 py-2 text-xs font-semibold rounded-xl bg-zinc-900 hover:bg-zinc-800 text-white shadow-xs transition-colors"
                  >{tx("返回设置主页")}</button>
                </div>
              </div>
            ) : (
              <div className="space-y-4 sm:space-y-6">
                <div className="bg-white dark:bg-zinc-900 border border-purple-200 dark:border-purple-900/60 rounded-2xl p-3.5 sm:p-6 shadow-xs space-y-4 sm:space-y-6">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-purple-100 dark:border-purple-900/40 gap-4">
                    <div>
                      <h2 className="text-base font-bold text-purple-950 dark:text-purple-200 flex items-center gap-2">
                        <KeyRound className="w-5 h-5 text-purple-600 dark:text-purple-400" />
                        <span>{t('settings.oidc', tx("OIDC / SSO 单点登录"))}</span>
                        <span className="px-2 py-0.5 rounded-full text-[11px] font-bold bg-purple-100 dark:bg-purple-950 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800">{tx("系统管理员专享")}</span>
                      </h2>
                      <p className="text-xs text-zinc-500 mt-1">{tx("集成 Authelia、Authentik、Keycloak 等企业级 OIDC 身份提供商，支持单点登录与新用户 JIT 自动预配建号。")}</p>
                    </div>
                    <button
                      onClick={handleOpenCreateOidc}
                      className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-purple-600 hover:bg-purple-700 text-white text-xs font-semibold shadow-xs transition cursor-pointer self-start sm:self-auto shrink-0"
                    >
                      <Plus className="w-3.5 h-3.5" />
                      <span>{t('settings.addProvider', tx("添加 OIDC 提供商"))}</span>
                    </button>
                  </div>

                  {/* SSO Providers List */}
                  <div className="space-y-3">
                    {ssoLoading ? (
                      <div className="py-8 text-center text-xs text-zinc-400">{tx("Loading SSO providers...")}</div>
                    ) : ssoProviders.length === 0 ? (
                      <div className="p-4 sm:p-8 text-center border border-dashed border-zinc-200 dark:border-zinc-800 rounded-xl">
                        <KeyRound className="w-8 h-8 text-zinc-300 dark:text-zinc-600 mx-auto mb-2" />
                        <p className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
                          {t('settings.noProviders', tx("No SSO providers configured yet"))}
                        </p>
                        <p className="text-[11px] text-zinc-400 mt-1">{tx("Add Authentik, Keycloak, or Google OIDC to enable single sign-on for family members.")}</p>
                      </div>
                    ) : (
                      ssoProviders.map((p) => (
                        <div
                          key={p.name}
                          className="flex items-center justify-between p-3 sm:p-4 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-800/40"
                        >
                          <div className="flex items-center gap-3">
                            <div className="w-9 h-9 rounded-lg bg-zinc-900 text-white flex items-center justify-center font-bold text-xs uppercase">
                              {p.name.slice(0, 2)}
                            </div>
                            <div>
                              <span className="text-xs font-bold text-zinc-900 dark:text-zinc-100 block">
                                {tx(p.label)}
                              </span>
                              <span className="text-[11px] font-mono text-zinc-400 block truncate max-w-sm">
                                {p.issuer}
                              </span>
                            </div>
                          </div>

                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              onClick={() => handleToggleOidcEnabled(p)}
                              title={p.enabled ? tx("点击禁用此提供商") : tx("点击启用此提供商")}
                              className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold transition-colors ${
                                p.enabled
                                  ? 'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300 hover:bg-emerald-200 dark:hover:bg-emerald-900/60'
                                  : 'bg-zinc-200 dark:bg-zinc-700 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-300 dark:hover:bg-zinc-600'
                              }`}
                            >
                              {p.enabled ? <CheckCircle2 className="w-3 h-3" /> : <XCircle className="w-3 h-3" />}
                              {p.enabled ? tx("已启用") : tx("已禁用")}
                            </button>
                            <button
                              type="button"
                              onClick={() => handleOpenEditOidc(p)}
                              className="p-1.5 rounded-lg text-zinc-500 hover:text-zinc-900 dark:hover:text-white hover:bg-zinc-100 dark:hover:bg-zinc-700 transition-colors"
                              title={tx("编辑此提供商配置")}
                            >
                              <Edit2 className="w-4 h-4" />
                            </button>
                            <a
                              href={`/api/v1/auth/sso/${p.name}/authorize`}
                              className="p-1.5 rounded-lg text-zinc-500 hover:text-zinc-900 dark:hover:text-white hover:bg-zinc-100 dark:hover:bg-zinc-700 transition-colors"
                              title={tx("测试此 SSO 登录")}
                              target="_blank"
                              rel="noreferrer"
                            >
                              <ExternalLink className="w-4 h-4" />
                            </a>
                            <button
                              type="button"
                              onClick={() => handleDeleteOidc(p.name)}
                              className="p-1.5 rounded-lg text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-950/30 transition-colors"
                              title={tx("移除此提供商")}
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>
            )
          )}

          {/* ══════════════════════════════════════════════════════════════ */}
          {/* TAB 3: RULES & AUTOMATIONS (Blueprint Section 8 & 9)          */}
          {/* ══════════════════════════════════════════════════════════════ */}
          {activeTab === 'rules' && (
            <div className="space-y-4 sm:space-y-6">
              {/* Rules Pipeline embedded directly inside Settings without double borders */}
              <RulesPage embedded={true} />

              {/* Silent Automation Pipelines (Auto Transfer & Auto Refund) */}
              <div className="bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 rounded-2xl p-3.5 sm:p-6 shadow-xs space-y-4">
                <div>
                  <h2 className="text-base font-bold text-zinc-900 dark:text-zinc-100">{tx("智能自动化全局策略 (Global Automations)")}</h2>
                  <p className="text-xs text-zinc-500 mt-0.5">{tx("配置同额流水静默撮合与退款冲抵的全局行为")}</p>
                </div>

                <div className="space-y-4 pt-2 divide-y divide-zinc-100 dark:divide-zinc-800">
                  {/* Auto Transfer */}
                  <div className="pt-4 flex items-center justify-between gap-3">
                    <div className="min-w-0 pr-2">
                      <span className="text-xs font-bold text-zinc-900 dark:text-zinc-100 block">
                        {t('settings.autoTransfer', tx("Silent Auto-Transfer Matching (≤ 2 days)"))}
                      </span>
                      <span className="text-[11px] text-zinc-500 block mt-0.5 leading-relaxed">
                        {t('settings.autoTransferDesc', tx("Automatically combines matching outflow and inflow into a single transfer"))}
                      </span>
                    </div>
                    <button
                      onClick={() => setAutoTransfer(!autoTransfer)}
                      className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors ${
                        autoTransfer ? 'bg-zinc-900 dark:bg-emerald-600' : 'bg-zinc-200 dark:bg-zinc-700'
                      }`}
                    >
                      <span
                        className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                          autoTransfer ? 'translate-x-6' : 'translate-x-1'
                        }`}
                      />
                    </button>
                  </div>

                  {/* Auto Refund Allocation */}
                  <div className="pt-4 flex items-center justify-between gap-3">
                    <div className="min-w-0 pr-2">
                      <span className="text-xs font-bold text-zinc-900 dark:text-zinc-100 block">
                        {t('settings.autoRefund', tx("Smart Refund Allocation & Current Period Offsetting"))}
                      </span>
                      <span className="text-[11px] text-zinc-500 block mt-0.5 leading-relaxed">
                        {t('settings.autoRefundDesc', tx("Allocates refunds to offset current living expenses without altering past accounting months"))}
                      </span>
                    </div>
                    <button
                      onClick={() => setAutoRefund(!autoRefund)}
                      className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors ${
                        autoRefund ? 'bg-zinc-900 dark:bg-emerald-600' : 'bg-zinc-200 dark:bg-zinc-700'
                      }`}
                    >
                      <span
                        className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                          autoRefund ? 'translate-x-6' : 'translate-x-1'
                        }`}
                      />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ══════════════════════════════════════════════════════════════ */}
          {/* TAB: PROFILE (个人资料全面设置：名字、昵称、邮箱、密码、头像) */}
          {/* ══════════════════════════════════════════════════════════════ */}
          {activeTab === 'profile' && (
            <div className="bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 rounded-2xl p-3.5 sm:p-6 shadow-xs space-y-4 sm:space-y-6">
              <div>
                <h2 className="text-base font-bold text-zinc-900 dark:text-zinc-100">
                  {t('settings.profile', tx("个人资料与身份设置"))}
                </h2>
                <p className="text-xs text-zinc-500 mt-0.5">{tx("管理您的登录账号、家庭内昵称、安全绑定邮箱、登录密码及个人头像")}</p>
              </div>

              {/* 1. 头像设置区域 (Avatar Upload) */}
              <div className="p-3.5 sm:p-4 rounded-xl bg-zinc-50/70 dark:bg-zinc-800/40 border border-zinc-200/70 dark:border-zinc-800/80 flex flex-col sm:flex-row sm:items-center justify-between gap-3 sm:gap-4">
                <div className="flex items-center gap-3.5 sm:gap-4">
                  <div
                    key={avatarKey}
                    onClick={() => fileInputRef.current?.click()}
                    className="cursor-pointer group relative w-14 h-14 sm:w-16 sm:h-16 rounded-full overflow-hidden border-2 border-zinc-200 dark:border-zinc-700 shadow-xs shrink-0 flex items-center justify-center"
                    title={tx("点击更换头像")}
                  >
                    <Avatar user={profileDisplayName || user?.displayName || user?.username || 'QQ'} size="full" cacheBust={avatarKey} />
                    <div className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 flex flex-col items-center justify-center transition-opacity text-white text-[11px] font-semibold">
                      <span>{tx("更换")}</span>
                    </div>
                  </div>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="image/*"
                    onChange={handleAvatarUpload}
                    className="hidden"
                  />

                  <div>
                    <span className="text-sm font-bold text-zinc-900 dark:text-zinc-100 block">
                      {profileDisplayName || user?.displayName || user?.username || tx("用户")}
                    </span>
                    <span className="text-xs text-zinc-500 mt-0.5 block">{tx("支持 JPG、PNG、GIF、WebP 格式图片，文件大小限制在 2MB 以内")}</span>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className="px-3.5 py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 hover:bg-zinc-100 dark:hover:bg-zinc-700 text-xs font-semibold text-zinc-700 dark:text-zinc-200 transition-colors shadow-2xs shrink-0 cursor-pointer self-start sm:self-auto"
                >{tx("上传新头像")}</button>
              </div>

              {/* 2. 个人资料编辑表单 (改名字、改昵称、改邮箱、改密码) */}
              <form onSubmit={handleUpdateProfile} className="space-y-5">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  {/* 登录名 / 名字 (Username) */}
                  <div className="space-y-1.5">
                    <label className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 flex items-center justify-between">
                      <span>{tx("登录账号 / 名字 (Username)")}</span>
                      <span className="text-xs text-zinc-400 font-normal">{tx("支持英文字母、数字")}</span>
                    </label>
                    <input
                      type="text"
                      value={profileUsername}
                      onChange={(e) => setProfileUsername(e.target.value)}
                      required
                      placeholder={tx("登录用户名")}
                      className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl text-sm font-mono text-zinc-900 dark:text-zinc-100 outline-none focus:border-zinc-900 focus:ring-1 focus:ring-zinc-400 transition-colors"
                    />
                  </div>

                  {/* 显示昵称 (Display Name) */}
                  <div className="space-y-1.5">
                    <label className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 flex items-center justify-between">
                      <span>{tx("家庭显示昵称 (Display Name)")}</span>
                      <span className="text-xs text-zinc-400 font-normal">{tx("账单及家庭中显示的姓名")}</span>
                    </label>
                    <input
                      type="text"
                      value={profileDisplayName}
                      onChange={(e) => setProfileDisplayName(e.target.value)}
                      required
                      placeholder={tx("例如：阿龙 / 爸爸")}
                      className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl text-sm text-zinc-900 dark:text-zinc-100 outline-none focus:border-zinc-900 focus:ring-1 focus:ring-zinc-400 transition-colors"
                    />
                  </div>
                </div>

                {/* 电子邮箱 (Email) */}
                <div className="space-y-1.5">
                  <label className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 flex items-center justify-between">
                    <span>{tx("安全绑定邮箱 (Email Address)")}</span>
                    <span className="text-xs text-zinc-400 font-normal">{tx("用于接收账单解析通知与身份重置")}</span>
                  </label>
                  <input
                    type="email"
                    value={profileEmail}
                    onChange={(e) => setProfileEmail(e.target.value)}
                    placeholder="user@example.com"
                    className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl text-sm text-zinc-900 dark:text-zinc-100 outline-none focus:border-zinc-900 focus:ring-1 focus:ring-zinc-400 transition-colors"
                  />
                </div>

                {/* 修改密码可选折叠区 (Change Password) */}
                <div className="pt-3 border-t border-zinc-100 dark:border-zinc-800 space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-bold text-zinc-900 dark:text-zinc-100 block">{tx("修改登录密码 (可选)")}</span>
                    <span className="text-xs text-zinc-400">{tx("如不修改请留空以下字段")}</span>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <div className="space-y-1">
                      <label className="text-xs text-zinc-500 dark:text-zinc-400 font-medium block">{tx("当前原密码")}</label>
                      <input
                        type="password"
                        value={profileCurrentPassword}
                        onChange={(e) => setProfileCurrentPassword(e.target.value)}
                        placeholder={tx("修改密码时必填")}
                        className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl text-sm outline-none focus:border-zinc-900 transition-colors"
                      />
                    </div>

                    <div className="space-y-1">
                      <label className="text-xs text-zinc-500 dark:text-zinc-400 font-medium block">{tx("新密码")}</label>
                      <input
                        type="password"
                        value={profileNewPassword}
                        onChange={(e) => setProfileNewPassword(e.target.value)}
                        placeholder={tx("至少 6 位字符")}
                        className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl text-sm outline-none focus:border-zinc-900 transition-colors"
                      />
                    </div>

                    <div className="space-y-1">
                      <label className="text-xs text-zinc-500 dark:text-zinc-400 font-medium block">{tx("确认新密码")}</label>
                      <input
                        type="password"
                        value={profileConfirmPassword}
                        onChange={(e) => setProfileConfirmPassword(e.target.value)}
                        placeholder={tx("再次输入新密码")}
                        className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl text-sm outline-none focus:border-zinc-900 transition-colors"
                      />
                    </div>
                  </div>
                </div>

                {/* 提交保存与退出当前账号 */}
                <div className="pt-4 flex items-center justify-between border-t border-zinc-100 dark:border-zinc-800">
                  <button
                    type="button"
                    data-testid="profile-logout-btn"
                    onClick={() => {
                      logout();
                      showToast(tx("已安全退出登录"), 'info');
                    }}
                    className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-semibold rounded-xl text-red-600 dark:text-red-400 bg-red-50/70 hover:bg-red-100 dark:bg-red-950/30 dark:hover:bg-red-950/60 border border-red-200/80 dark:border-red-900/60 shadow-2xs transition-colors cursor-pointer"
                  >
                    <LogOut className="w-4 h-4" />
                    <span>{tx("退出当前账号")}</span>
                  </button>

                  <button
                    type="submit"
                    disabled={profileLoading}
                    className="inline-flex items-center justify-center px-5 py-2.5 text-sm font-bold rounded-xl bg-zinc-900 hover:bg-zinc-800 text-white dark:bg-white dark:text-zinc-900 dark:hover:bg-zinc-100 shadow-xs transition-colors cursor-pointer disabled:opacity-50"
                  >
                    {profileLoading ? tx("正在保存个人资料...") : tx("保存个人资料修改")}
                  </button>
                </div>
              </form>
            </div>
          )}

          {/* ══════════════════════════════════════════════════════════════ */}
          {/* TAB 6: DATA & BACKUP                                          */}
          {/* ══════════════════════════════════════════════════════════════ */}
          {activeTab === 'data' && (
            <div className="bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 rounded-2xl p-3.5 sm:p-6 shadow-xs space-y-4 sm:space-y-6">
              <div>
                <h2 className="text-base font-bold text-zinc-900 dark:text-zinc-100">
                  {t('settings.data', tx("Data & Backup"))}
                </h2>
                <p className="text-xs text-zinc-500 mt-0.5">{tx("Export financial archives, SQLite/PostgreSQL backups, and transaction history")}</p>
              </div>

              <div className="space-y-3">
                <a
                  href="/api/export/csv"
                  download
                  className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-800 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-700 transition-colors shadow-2xs"
                >
                  <Database className="w-4 h-4 text-zinc-500" />
                  <span>{tx("导出全部流水 (CSV)")}</span>
                </a>
              </div>
            </div>
          )}

          {/* ══════════════════════════════════════════════════════════════ */}
          {/* TAB 7: SELF-HOSTING & AI ASSISTANT                            */}
          {/* ══════════════════════════════════════════════════════════════ */}
          {activeTab === 'hosting' && (
            <div className="bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 rounded-2xl p-3.5 sm:p-6 shadow-xs space-y-4 sm:space-y-6">
              <div>
                <h2 className="text-base font-bold text-zinc-900 dark:text-zinc-100">
                  {t('settings.hosting', tx("Self-Hosting & AI"))}
                </h2>
                <p className="text-xs text-zinc-500 mt-0.5">
                  {t('settings.aiAssistant', tx("AI Assistant & LLM Configuration"))} {tx("(OpenAI, Anthropic Claude, Local Ollama)")}</p>
              </div>

              <div className="space-y-4 max-w-xl text-xs">
                {/* AI Provider */}
                <div className="space-y-1.5">
                  <label className="font-semibold text-zinc-700 dark:text-zinc-300">{tx("AI Provider")}</label>
                  <div className="grid grid-cols-2 gap-2">
                    {["openai", "anthropic"].map((p) => (
                      <button
                        key={p}
                        type="button"
                        onClick={() => {
                          setAiProvider(p);
                          localStorage.setItem('famledger_ai_provider', p);
                        }}
                        className={`py-2 px-3 rounded-xl border text-xs font-semibold capitalize transition-all ${
                          aiProvider === p
                            ? 'bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 border-transparent shadow-xs'
                            : 'border-zinc-200 dark:border-zinc-700 hover:bg-zinc-50 dark:hover:bg-zinc-800'
                        }`}
                      >
                        {p === 'openai' ? tx("OpenAI / Compatible") : tx("Anthropic (Claude)")}
                      </button>
                    ))}
                  </div>
                </div>

                {/* API Key */}
                <div className="space-y-1.5">
                  <label className="font-semibold text-zinc-700 dark:text-zinc-300">{tx("Access Token / API Key")}</label>
                  <input
                    type="password"
                    value={aiKey}
                    onChange={(e) => {
                      setAiKey(e.target.value);
                      localStorage.setItem('famledger_ai_key', e.target.value);
                    }}
                    placeholder="sk-••••••••••••••••"
                    className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none font-mono"
                  />
                </div>

                {/* Base URL */}
                <div className="space-y-1.5">
                  <label className="font-semibold text-zinc-700 dark:text-zinc-300">{tx("API Base URL (Optional)")}</label>
                  <input
                    type="text"
                    value={aiBaseUrl}
                    onChange={(e) => {
                      setAiBaseUrl(e.target.value);
                      localStorage.setItem('famledger_ai_base', e.target.value);
                    }}
                    placeholder="https://api.openai.com/v1"
                    className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none font-mono"
                  />
                </div>

                {/* Model */}
                <div className="space-y-1.5">
                  <label className="font-semibold text-zinc-700 dark:text-zinc-300">{tx("Default Model")}</label>
                  <input
                    type="text"
                    value={aiModel}
                    onChange={(e) => {
                      setAiModel(e.target.value);
                      localStorage.setItem('famledger_ai_model', e.target.value);
                    }}
                    placeholder="gpt-4o-mini"
                    className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none font-mono"
                  />
                </div>

                <button
                  type="button"
                  onClick={() => showToast(tx("AI 服务配置已持久化至本地环境"), 'success')}
                  className="mt-2 inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold rounded-lg bg-zinc-900 hover:bg-zinc-800 text-white shadow-xs transition-colors"
                >
                  <Sparkles className="w-3.5 h-3.5" />
                  <span>{tx("保存配置")}</span>
                </button>
              </div>
            </div>
          )}

          {/* ══════════════════════════════════════════════════════════════ */}
          {/* TAB: API KEYS & DEVELOPER ACCESS                             */}
          {/* ══════════════════════════════════════════════════════════════ */}
          {activeTab === 'apikeys' && (
            <div className="space-y-4 sm:space-y-6">
              {/* Header Card */}
              <div className="bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 rounded-2xl p-3.5 sm:p-6 shadow-xs space-y-4 sm:space-y-6">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-zinc-100 dark:border-zinc-800 gap-4">
                  <div>
                    <h2 className="text-base font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
                      <Key className="w-5 h-5 text-indigo-500" />
                      <span>{tx("API 密钥 (API Keys)")}</span>
                    </h2>
                    <p className="text-xs text-zinc-500 mt-1">{tx("创建专属密钥用于外部自动化记账脚本、iOS 快捷指令、Webhook 或第三方系统安全调用，替代高危明文密码。")}</p>
                  </div>
                  <button
                    type="button"
                    data-testid="create-api-key-btn"
                    onClick={() => {
                      setApiKeyName('');
                      setApiKeyExpiresDays('365');
                      setShowCreateApiKeyModal(true);
                    }}
                    className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-zinc-900 dark:bg-zinc-100 hover:bg-zinc-800 text-white dark:text-zinc-900 text-xs font-semibold shadow-xs transition cursor-pointer self-start sm:self-auto shrink-0"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    <span>{tx("生成新 API Key")}</span>
                  </button>
                </div>

                {/* API Keys List */}
                <div className="space-y-3">
                  {apiKeysLoading ? (
                    <div className="py-8 text-center text-xs text-zinc-400">{tx("正在加载 API Key 列表...")}</div>
                  ) : apiKeys.length === 0 ? (
                    <div className="py-10 text-center space-y-3 border border-dashed border-zinc-200 dark:border-zinc-800 rounded-xl bg-zinc-50/50 dark:bg-zinc-900/30">
                      <div className="w-10 h-10 rounded-full bg-zinc-100 dark:bg-zinc-800 text-zinc-400 flex items-center justify-center mx-auto">
                        <Key className="w-5 h-5" />
                      </div>
                      <div className="text-xs text-zinc-500">{tx("暂未创建任何 API 密钥。点击右上角“生成新 API Key”开始连接您的自动化脚本。")}</div>
                    </div>
                  ) : (
                    <div className="divide-y divide-zinc-100 dark:divide-zinc-800 border border-zinc-200 dark:border-zinc-800 rounded-xl overflow-hidden">
                      {apiKeys.map((k) => (
                        <div key={k.id} className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3 hover:bg-zinc-50/60 dark:hover:bg-zinc-800/40 transition">
                          <div className="space-y-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="font-semibold text-sm text-zinc-900 dark:text-zinc-100 truncate">{k.name}</span>
                              <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold tracking-normal whitespace-nowrap ${
                                k.is_revoked || (k.expires_at && new Date(k.expires_at) < new Date())
                                  ? 'bg-red-50 text-red-600 dark:bg-red-950/40 dark:text-red-400'
                                  : 'bg-emerald-50 text-emerald-600 dark:bg-emerald-950/40 dark:text-emerald-400'
                              }`}>
                                {k.is_revoked ? tx("已撤销") : (k.expires_at && new Date(k.expires_at) < new Date()) ? tx("已过期") : tx("正常活跃")}
                              </span>
                            </div>
                            <div className="flex items-center gap-2 text-xs font-mono text-zinc-500 dark:text-zinc-400">
                              <span>{tx("前缀:")}</span>
                              <span className="bg-zinc-100 dark:bg-zinc-800 px-1.5 py-0.5 rounded text-[11px] font-mono text-zinc-700 dark:text-zinc-300">
                                {k.key_prefix}••••••••••••••••
                              </span>
                            </div>
                            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-zinc-400 pt-0.5">
                              <span>{tx("创建于:")} {formatDateTime(k.created_at)}</span>
                              <span>{tx("过期时间:")} {k.expires_at ? formatDateTime(k.expires_at) : tx("永久有效")}</span>
                              <span>{tx("最后调用:")} {k.last_used_at ? formatDateTime(k.last_used_at) : tx("从未调用")}</span>
                            </div>
                          </div>
                          <div className="flex items-center gap-2 shrink-0">
                            <button
                              type="button"
                              onClick={() => handleDeleteApiKey(k.id)}
                              disabled={deletingKeyId === k.id}
                              className="px-3 py-1.5 rounded-lg text-xs font-medium text-red-600 hover:bg-red-50 dark:hover:bg-red-950/40 border border-red-200/60 dark:border-red-900/40 transition cursor-pointer flex items-center gap-1.5 whitespace-nowrap shrink-0"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                              <span>{deletingKeyId === k.id ? tx("撤销中...") : tx("撤销密钥")}</span>
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              {/* Developer Integration Quickstart Guide */}
              <div className="bg-zinc-50 dark:bg-zinc-900/60 border border-zinc-200/80 dark:border-zinc-800 rounded-2xl p-4 sm:p-6 shadow-xs space-y-3">
                <div className="flex items-center gap-2 text-zinc-900 dark:text-zinc-100 font-bold text-sm">
                  <Terminal className="w-4 h-4 text-emerald-500" />
                  <span>{tx("快捷调用指南 (cURL & iOS 快捷指令)")}</span>
                </div>
                <p className="text-xs text-zinc-500 leading-relaxed">{tx("在 HTTP 请求头中添加")} <code className="px-1.5 py-0.5 bg-zinc-200/60 dark:bg-zinc-800 rounded font-mono text-zinc-800 dark:text-zinc-200">Authorization: Bearer YOUR_API_KEY</code> {tx("或")} <code className="px-1.5 py-0.5 bg-zinc-200/60 dark:bg-zinc-800 rounded font-mono text-zinc-800 dark:text-zinc-200">X-Api-Key: YOUR_API_KEY</code> {tx("，即可完成鉴权。")}</p>
                <div className="bg-zinc-900 text-zinc-100 rounded-xl p-3.5 font-mono text-xs overflow-x-auto relative">
                  <pre className="text-[11px] leading-relaxed">
{tx("# 示例：通过 API Key 提交单笔交易 curl -X POST \"{p0}/api/v1/transactions\" \\ -H \"Authorization: Bearer flk_live_xxxxxxxxxxxx\" \\ -H \"Content-Type: application/json\" \\ -d '{ \"amount\": 25.5, \"narration\": \"瑞幸咖啡\", \"account\": \"default\" }'", {p0: (window.location.origin)})}
                  </pre>
                </div>
              </div>
            </div>
          )}
        </main>
      </div>

      {/* ── Add / Edit OIDC Modal ── */}
      {showAddOidcModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div
            className="fixed inset-0 bg-black/50 backdrop-blur-xs"
            onClick={() => {
              setShowAddOidcModal(false);
              setEditingOidcProvider(null);
            }}
          />
          <div className="relative w-full max-w-lg bg-white dark:bg-zinc-900 rounded-2xl border border-zinc-200 dark:border-zinc-800 p-4 sm:p-6 shadow-2xl z-10 space-y-4 sm:space-y-5 animate-in zoom-in-95 duration-150">
            <div>
              <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-100">
                {editingOidcProvider ? tx("编辑 OIDC / SSO 提供商") : t('settings.addProvider', tx("Add OIDC Provider"))}
              </h3>
              <p className="text-xs text-zinc-500 mt-1">
                {editingOidcProvider
                  ? tx("正在修改 {p0} 的配置。留空密钥将保留原有密钥。", {p0: (editingOidcProvider.label)})
                  : tx("配置第三方单点登录 Identity Provider。支持 Authelia、Authentik、Keycloak 等标准 OIDC。")}
              </p>
            </div>

            {/* Quick Preset Buttons (仅新建时显示) */}
            {!editingOidcProvider && (
              <div className="flex items-center gap-2 pb-1 overflow-x-auto">
                {[
                  { name: 'authelia', label: 'Sign in with Authelia', issuer: 'https://127.0.0.1:9091' },
                  { name: 'authentik', label: 'Sign in with Authentik', issuer: 'https://auth.example.lan/application/o/famledger' },
                  { name: 'keycloak', label: 'Sign in with Keycloak', issuer: 'https://keycloak.example.lan/realms/famrealm' },
                  { name: 'google', label: 'Sign in with Google', issuer: 'https://accounts.google.com' },
                  { name: 'custom', label: 'Sign in with SSO', issuer: 'https://oidc.example.com' },
                ].map((preset) => (
                  <button
                    key={preset.name}
                    type="button"
                    onClick={() => setOidcForm({
                      ...oidcForm,
                      name: preset.name,
                      label: preset.label,
                      issuer: preset.issuer,
                    })}
                    className="px-2.5 py-1 text-[11px] font-semibold rounded-lg bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 text-zinc-700 dark:text-zinc-300 transition-colors shrink-0"
                  >
                    + {tx(preset.label)}
                  </button>
                ))}
              </div>
            )}

            <form onSubmit={handleSaveOidcProvider} className="space-y-4 text-xs">
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="font-semibold text-zinc-700 dark:text-zinc-300">{tx("Provider Name (标识名)")}</label>
                  <input
                    type="text"
                    value={oidcForm.name}
                    onChange={(e) => setOidcForm({ ...oidcForm, name: e.target.value })}
                    placeholder="authelia"
                    required
                    disabled={Boolean(editingOidcProvider)}
                    className={`w-full px-3 py-2 border rounded-xl outline-none font-mono ${
                      editingOidcProvider
                        ? 'bg-zinc-100 dark:bg-zinc-800/80 text-zinc-500 dark:text-zinc-400 border-zinc-200 dark:border-zinc-800 cursor-not-allowed'
                        : 'bg-zinc-50 dark:bg-zinc-800 border-zinc-200 dark:border-zinc-700 text-zinc-900 dark:text-zinc-100'
                    }`}
                  />
                  {editingOidcProvider && (
                    <span className="text-[10px] text-zinc-400">{tx("唯一标识创建后不可修改")}</span>
                  )}
                </div>

                <div className="space-y-1">
                  <label className="font-semibold text-zinc-700 dark:text-zinc-300">{tx("登录按钮文字 (Button Text / Label)")}</label>
                  <input
                    type="text"
                    value={oidcForm.label}
                    onChange={(e) => setOidcForm({ ...oidcForm, label: e.target.value })}
                    placeholder={tx("Sign in with Authelia")}
                    required
                    className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none text-zinc-900 dark:text-zinc-100"
                  />
                  <span className="text-[10px] text-zinc-400 block">{tx("登录界面按钮将精确显示此文案（如：Sign in with Authelia）")}</span>
                </div>
              </div>

              <div className="space-y-1">
                <label className="font-semibold text-zinc-700 dark:text-zinc-300">{tx("Issuer URL (Discovery Endpoint)")}</label>
                <input
                  type="url"
                  value={oidcForm.issuer}
                  onChange={(e) => setOidcForm({ ...oidcForm, issuer: e.target.value })}
                  placeholder="https://127.0.0.1:9091"
                  required
                  className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none font-mono text-zinc-900 dark:text-zinc-100"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="font-semibold text-zinc-700 dark:text-zinc-300">{tx("Client ID")}</label>
                  <input
                    type="text"
                    value={oidcForm.client_id}
                    onChange={(e) => setOidcForm({ ...oidcForm, client_id: e.target.value })}
                    placeholder="famledger"
                    required
                    className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none font-mono text-zinc-900 dark:text-zinc-100"
                  />
                </div>

                <div className="space-y-1">
                  <label className="font-semibold text-zinc-700 dark:text-zinc-300">{tx("Client Secret")}</label>
                  <input
                    type="password"
                    value={oidcForm.client_secret}
                    onChange={(e) => setOidcForm({ ...oidcForm, client_secret: e.target.value })}
                    placeholder={editingOidcProvider ? tx("••••••••（留空保持原密钥）") : '••••••••••••'}
                    required={!editingOidcProvider}
                    className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none font-mono text-zinc-900 dark:text-zinc-100"
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label className="font-semibold text-zinc-700 dark:text-zinc-300">
                  {t('settings.allowedDomains', tx("Allowed Domains (comma-separated, optional)"))}
                </label>
                <input
                  type="text"
                  value={oidcForm.allowed_domains}
                  onChange={(e) => setOidcForm({ ...oidcForm, allowed_domains: e.target.value })}
                  placeholder="@family.lan, @gmail.com"
                  className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none text-zinc-900 dark:text-zinc-100"
                />
              </div>

              <div className="space-y-2 pt-1">
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="allow_jit"
                    checked={oidcForm.allow_jit}
                    onChange={(e) => setOidcForm({ ...oidcForm, allow_jit: e.target.checked })}
                    className="rounded text-zinc-900 dark:text-white"
                  />
                  <label htmlFor="allow_jit" className="font-medium text-zinc-700 dark:text-zinc-300 cursor-pointer">
                    {t('settings.allowJit', tx("Enable JIT User Creation on first login"))}
                  </label>
                </div>

                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="oidc_enabled"
                    checked={oidcForm.enabled}
                    onChange={(e) => setOidcForm({ ...oidcForm, enabled: e.target.checked })}
                    className="rounded text-zinc-900 dark:text-white"
                  />
                  <label htmlFor="oidc_enabled" className="font-medium text-zinc-700 dark:text-zinc-300 cursor-pointer">{tx("启用此 SSO 提供商 (Enabled)")}</label>
                </div>
              </div>

              <div className="pt-4 flex items-center justify-end gap-2 border-t border-zinc-100 dark:border-zinc-800">
                <button
                  type="button"
                  onClick={() => {
                    setShowAddOidcModal(false);
                    setEditingOidcProvider(null);
                  }}
                  className="px-3 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 font-medium"
                >
                  {t('common.cancel', tx("Cancel"))}
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 rounded-lg bg-zinc-900 hover:bg-zinc-800 text-white font-semibold shadow-xs"
                >
                  {editingOidcProvider ? tx("保存修改 (Save Changes)") : t('settings.saveProvider', tx("Save Provider"))}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 新建家庭组弹窗 */}
      {showCreateFamilyModal && (
        <div className="fixed inset-0 z-50 overflow-y-auto flex items-center justify-center p-4">
          <div className="fixed inset-0 bg-black/50 backdrop-blur-xs" onClick={() => setShowCreateFamilyModal(false)} />
          <div className="relative bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl w-full max-w-md border border-zinc-200 dark:border-zinc-800 overflow-hidden z-10 animate-in fade-in zoom-in-95 duration-150">
            <div className="px-4 sm:px-6 py-3.5 sm:py-4 border-b border-zinc-100 dark:border-zinc-800 flex items-center justify-between">
              <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
                <Users className="w-4 h-4 text-zinc-500" />
                <span>{tx("新建家庭组")}</span>
              </h3>
              <button
                type="button"
                onClick={() => setShowCreateFamilyModal(false)}
                className="p-1 rounded-lg text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800"
              >
                <CheckCircle2 className="w-4 h-4 opacity-0" />
                <span>✕</span>
              </button>
            </div>

            <form onSubmit={handleCreateFamily} className="p-4 sm:p-6 space-y-4 text-xs sm:text-sm">
              <div>
                <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300 mb-1">{tx("家庭组名称")} <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  required
                  data-testid="create-family-name-input"
                  value={createFamilyName}
                  onChange={(e) => setCreateFamilyName(e.target.value)}
                  placeholder={tx("例如：甜蜜之家、Sure小队")}
                  className="w-full px-3 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-white text-xs sm:text-sm focus:ring-2 focus:ring-zinc-900 outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300 mb-1">{tx("默认结算货币")}</label>
                <select
                  value={createFamilyCurrency}
                  onChange={(e) => setCreateFamilyCurrency(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-white text-xs sm:text-sm focus:ring-2 focus:ring-zinc-900 outline-none"
                >
                  <option value="CNY">{tx("CNY (人民币 ¥)")}</option>
                  <option value="USD">{tx("USD (美元 $)")}</option>
                  <option value="EUR">{tx("EUR (欧元 €)")}</option>
                  <option value="HKD">{tx("HKD (港币 HK$)")}</option>
                  <option value="JPY">{tx("JPY (日元 ¥)")}</option>
                </select>
              </div>

              <div className="pt-2 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setShowCreateFamilyModal(false)}
                  className="px-3.5 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-xs font-medium cursor-pointer"
                >{tx("取消")}</button>
                <button
                  type="submit"
                  data-testid="create-family-submit-btn"
                  disabled={createFamilyLoading || !createFamilyName.trim()}
                  className="px-4 py-2 rounded-lg bg-zinc-900 dark:bg-white text-white dark:text-zinc-900 hover:bg-zinc-800 dark:hover:bg-zinc-100 text-xs font-bold shadow-xs disabled:opacity-50 cursor-pointer"
                >
                  {createFamilyLoading ? tx("创建中...") : tx("确认创建并切换")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 解散家庭组确认弹窗 */}
      {showDeleteFamilyModal && (
        <div className="fixed inset-0 z-50 overflow-y-auto flex items-center justify-center p-4">
          <div className="fixed inset-0 bg-black/50 backdrop-blur-xs" onClick={() => setShowDeleteFamilyModal(false)} />
          <div className="relative bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl w-full max-w-md border border-red-200 dark:border-red-900/60 overflow-hidden z-10 animate-in fade-in zoom-in-95 duration-150">
            <div className="px-4 sm:px-6 py-3.5 sm:py-4 border-b border-zinc-100 dark:border-zinc-800 flex items-center justify-between">
              <h3 className="text-base font-bold text-red-600 dark:text-red-400 flex items-center gap-2">
                <Trash2 className="w-4 h-4" />
                <span>{tx("解散家庭组确认")}</span>
              </h3>
              <button
                type="button"
                onClick={() => setShowDeleteFamilyModal(false)}
                className="p-1 rounded-lg text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800"
              >
                ✕
              </button>
            </div>

            <div className="p-4 sm:p-6 space-y-4 text-xs sm:text-sm">
              <div className="p-3.5 rounded-xl bg-red-50 dark:bg-red-950/30 border border-red-200/80 dark:border-red-800/40 text-red-800 dark:text-red-300 space-y-1">
                <span className="font-bold block">{tx("⚠️ 危险操作提示")}</span>
                <p className="text-xs leading-relaxed">{tx("您即将解散家庭组「")} <strong>{currentFamily?.name}</strong> {tx("」。解散后：")}</p>
                <ul className="list-disc list-inside text-[11px] space-y-0.5 pt-1">
                  <li>{tx("家庭组成员将被迁出并恢复为各自独立的个人记账空间；")}</li>
                  <li>{tx("所有账户、账单流水与数据完整保留在各自名下；")}</li>
                  <li>{tx("此操作无法撤销。")}</li>
                </ul>
              </div>

              <div className="pt-2 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setShowDeleteFamilyModal(false)}
                  className="px-3.5 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-xs font-medium cursor-pointer"
                >{tx("取消")}</button>
                <button
                  type="button"
                  data-testid="delete-family-confirm-btn"
                  onClick={handleDeleteFamily}
                  disabled={deleteFamilyLoading}
                  className="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-700 text-white text-xs font-bold shadow-xs disabled:opacity-50 cursor-pointer"
                >
                  {deleteFamilyLoading ? tx("正在解散...") : tx("确认解散")}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 退出家庭组确认弹窗 */}
      {showLeaveFamilyModal && (
        <div className="fixed inset-0 z-50 overflow-y-auto flex items-center justify-center p-4">
          <div className="fixed inset-0 bg-black/50 backdrop-blur-xs" onClick={() => setShowLeaveFamilyModal(false)} />
          <div className="relative bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl w-full max-w-md border border-amber-200 dark:border-amber-900/60 overflow-hidden z-10 animate-in fade-in zoom-in-95 duration-150">
            <div className="px-4 sm:px-6 py-3.5 sm:py-4 border-b border-zinc-100 dark:border-zinc-800 flex items-center justify-between">
              <h3 className="text-base font-bold text-amber-700 dark:text-amber-400 flex items-center gap-2">
                <LogOut className="w-4 h-4" />
                <span>{tx("退出家庭组确认")}</span>
              </h3>
              <button
                type="button"
                onClick={() => setShowLeaveFamilyModal(false)}
                className="p-1 rounded-lg text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800"
              >
                ✕
              </button>
            </div>

            <div className="p-4 sm:p-6 space-y-4 text-xs sm:text-sm">
              <div className="p-3.5 rounded-xl bg-amber-50 dark:bg-amber-950/30 border border-amber-200/80 dark:border-amber-800/40 text-amber-800 dark:text-amber-300 space-y-1">
                <span className="font-bold block">{tx("⚠️ 退出家庭组提示")}</span>
                <p className="text-xs leading-relaxed">{tx("您即将退出家庭组「")} <strong>{currentFamily?.name}</strong> {tx("」。退出后：")}</p>
                <ul className="list-disc list-inside text-[11px] space-y-0.5 pt-1">
                  <li>{tx("您将自动切换至您的专属个人独立记账空间；")}</li>
                  <li>{tx("您名下的所有私有账户、账单流水与个人债务完整保留；")}</li>
                  <li>{tx("家庭组将由组内其余成员/管理员继续协同使用。")}</li>
                </ul>
              </div>

              <div className="pt-2 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setShowLeaveFamilyModal(false)}
                  className="px-3.5 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-xs font-medium cursor-pointer"
                >{tx("取消")}</button>
                <button
                  type="button"
                  data-testid="leave-family-confirm-btn"
                  onClick={handleLeaveFamily}
                  disabled={leaveFamilyLoading}
                  className="px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-700 text-white text-xs font-bold shadow-xs disabled:opacity-50 cursor-pointer"
                >
                  {leaveFamilyLoading ? tx("正在退出...") : tx("确认退出")}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 拥有者退出提示弹窗（家庭还有其他成员） */}
      {showLeaveOwnerWarningModal && (
        <div className="fixed inset-0 z-50 overflow-y-auto flex items-center justify-center p-4">
          <div className="fixed inset-0 bg-black/50 backdrop-blur-xs" onClick={() => setShowLeaveOwnerWarningModal(false)} />
          <div className="relative bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl w-full max-w-md border border-amber-200 dark:border-amber-900/60 overflow-hidden z-10 animate-in fade-in zoom-in-95 duration-150">
            <div className="px-4 sm:px-6 py-3.5 sm:py-4 border-b border-zinc-100 dark:border-zinc-800 flex items-center justify-between">
              <h3 className="text-base font-bold text-amber-700 dark:text-amber-400 flex items-center gap-2">
                <Shield className="w-4 h-4" />
                <span>{tx("拥有者退出提示")}</span>
              </h3>
              <button
                type="button"
                onClick={() => setShowLeaveOwnerWarningModal(false)}
                className="p-1 rounded-lg text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800"
              >
                ✕
              </button>
            </div>

            <div className="p-4 sm:p-6 space-y-4 text-xs sm:text-sm">
              <div className="p-3.5 rounded-xl bg-amber-50 dark:bg-amber-950/30 border border-amber-200/80 dark:border-amber-800/40 text-amber-800 dark:text-amber-300 space-y-2">
                <span className="font-bold block">{tx("⚠️ 您是当前家庭组唯一的管理员")}</span>
                <p className="text-xs leading-relaxed">{tx("当前家庭组「")} <strong>{currentFamily?.name}</strong> {tx("」内还有其他成员。为避免家庭账本失控，系统不允许唯一管理员直接离开家庭组。")}</p>
                <p className="text-xs leading-relaxed text-zinc-600 dark:text-zinc-400">{tx("如需退出，您可以：")}</p>
                <ul className="list-disc list-inside text-[11px] space-y-1 pt-0.5 text-zinc-600 dark:text-zinc-400">
                  <li>{tx("在下方家庭成员列表中将其他成员设置为管理员；")}</li>
                  <li>{tx("或者直接解散该家庭组，所有成员将各自安全转入个人独立记账空间。")}</li>
                </ul>
              </div>

              <div className="pt-2 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setShowLeaveOwnerWarningModal(false)}
                  className="px-3.5 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-xs font-medium cursor-pointer"
                >{tx("我知道了")}</button>
                <button
                  type="button"
                  onClick={() => {
                    setShowLeaveOwnerWarningModal(false);
                    setShowDeleteFamilyModal(true);
                  }}
                  className="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-700 text-white text-xs font-bold shadow-xs cursor-pointer"
                >{tx("去解散家庭组")}</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 新增 / 编辑分类模态框 */}
      {showCategoryModal && (
        <div className="fixed inset-0 z-50 overflow-y-auto flex items-center justify-center p-4">
          <div className="fixed inset-0 bg-black/50 backdrop-blur-xs" onClick={() => setShowCategoryModal(false)} />
          <div className="relative bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl w-full max-w-md border border-zinc-200 dark:border-zinc-800 overflow-hidden z-10 animate-in fade-in zoom-in-95 duration-150">
            <div className="px-4 sm:px-6 py-3.5 sm:py-4 border-b border-zinc-100 dark:border-zinc-800 flex items-center justify-between">
              <h3 className="text-base font-bold text-zinc-900 dark:text-white flex items-center gap-2">
                <FolderTree className="w-4 h-4 text-indigo-500" />
                <span>{categoryModalMode === 'create' ? tx("新建交易分类") : tx("编辑交易分类")}</span>
              </h3>
              <button
                type="button"
                onClick={() => setShowCategoryModal(false)}
                className="p-1 rounded-lg text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 cursor-pointer"
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleSaveCategory} className="p-4 sm:p-6 space-y-4">
              <div>
                <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300 mb-1.5">{tx("分类类型")} <span className="text-red-500">*</span>
                </label>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => setCategoryForm({ ...categoryForm, category_type: 'expense' })}
                    className={`px-3 py-2 rounded-lg text-xs font-bold border transition flex items-center justify-center gap-1.5 cursor-pointer ${
                      (categoryForm.category_type || 'expense') === 'expense'
                        ? 'bg-zinc-900 dark:bg-white text-white dark:text-zinc-900 border-transparent shadow-xs'
                        : 'border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800'
                    }`}
                  >
                    <span>{tx("支出分类")}</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setCategoryForm({ ...categoryForm, category_type: 'income' })}
                    className={`px-3 py-2 rounded-lg text-xs font-bold border transition flex items-center justify-center gap-1.5 cursor-pointer ${
                      categoryForm.category_type === 'income'
                        ? 'bg-emerald-600 text-white border-transparent shadow-xs'
                        : 'border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800'
                    }`}
                  >
                    <span>{tx("收入分类")}</span>
                  </button>
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300 mb-1">{tx("分类名称")} <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  required
                  data-testid="category-name-input"
                  value={categoryForm.name}
                  onChange={(e) => setCategoryForm({ ...categoryForm, name: e.target.value })}
                  placeholder={tx("如：咖啡下午茶、健身运动")}
                  className="w-full px-3 py-2 text-xs sm:text-sm rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-white outline-none focus:ring-1 focus:ring-zinc-900 dark:focus:ring-white"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300 mb-1.5">{tx("分类图标 (Emoji)")}</label>
                <div className="flex items-center gap-2 mb-2">
                  <span className="w-10 h-10 rounded-xl bg-zinc-100 dark:bg-zinc-800 text-2xl flex items-center justify-center shrink-0 border border-zinc-200 dark:border-zinc-700">
                    {categoryForm.icon || '📦'}
                  </span>
                  <input
                    type="text"
                    value={categoryForm.icon}
                    onChange={(e) => setCategoryForm({ ...categoryForm, icon: e.target.value })}
                    placeholder={tx("输入或点击下方选择")}
                    className="flex-1 px-3 py-2 text-xs rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-white outline-none"
                  />
                </div>
                <div className="flex flex-wrap gap-1.5 p-2 rounded-xl bg-zinc-50 dark:bg-zinc-800/40 border border-zinc-200/60 dark:border-zinc-700/60">
                  {['🍴', '🛒', '🛍️', '🚗', '⚡', '👤', '🎬', '💊', '✈️', '☕', '🏠', '🎁', '🐶', '📚', '💰', '🍪'].map((em) => (
                    <button
                      key={em}
                      type="button"
                      onClick={() => setCategoryForm({ ...categoryForm, icon: em })}
                      className={`w-7 h-7 rounded-lg text-sm flex items-center justify-center hover:bg-white dark:hover:bg-zinc-700 transition cursor-pointer ${
                        categoryForm.icon === em ? 'bg-white dark:bg-zinc-700 shadow-2xs font-bold scale-110' : ''
                      }`}
                    >
                      {em}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300 mb-1.5">{tx("主题颜色")}</label>
                <div className="flex items-center gap-2">
                  {["#6366f1", "#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#ec4899", "#8b5cf6", "#71717a"].map((col) => (
                    <button
                      key={col}
                      type="button"
                      onClick={() => setCategoryForm({ ...categoryForm, color: col })}
                      style={{ backgroundColor: col }}
                      className={`w-6 h-6 rounded-full transition cursor-pointer ${
                        categoryForm.color === col ? 'scale-115 ring-2 ring-zinc-900 dark:ring-white ring-offset-2' : 'opacity-70 hover:opacity-100'
                      }`}
                    />
                  ))}
                </div>
              </div>

              <div className="pt-3 flex justify-end gap-2 border-t border-zinc-100 dark:border-zinc-800">
                <button
                  type="button"
                  onClick={() => setShowCategoryModal(false)}
                  className="px-3.5 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-xs font-medium cursor-pointer"
                >{tx("取消")}</button>
                <button
                  type="submit"
                  data-testid="save-category-submit-btn"
                  disabled={categorySaving || !categoryForm.name.trim()}
                  className="px-4 py-2 rounded-lg bg-zinc-900 dark:bg-white text-white dark:text-zinc-900 hover:bg-zinc-800 dark:hover:bg-zinc-100 text-xs font-bold shadow-xs disabled:opacity-50 cursor-pointer"
                >
                  {categorySaving ? tx("保存中...") : tx("确认保存")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 删除分类二次确认弹窗 */}
      {deletingCategory && (
        <div className="fixed inset-0 z-50 overflow-y-auto flex items-center justify-center p-4">
          <div className="fixed inset-0 bg-black/50 backdrop-blur-xs" onClick={() => setDeletingCategory(null)} />
          <div className="relative bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl w-full max-w-md border border-red-200 dark:border-red-900/60 overflow-hidden z-10 animate-in fade-in zoom-in-95 duration-150">
            <div className="px-4 sm:px-6 py-3.5 sm:py-4 border-b border-zinc-100 dark:border-zinc-800 flex items-center justify-between">
              <h3 className="text-base font-bold text-red-600 dark:text-red-400 flex items-center gap-2">
                <Trash2 className="w-4 h-4" />
                <span>{tx("删除分类确认")}</span>
              </h3>
              <button
                type="button"
                onClick={() => setDeletingCategory(null)}
                className="p-1 rounded-lg text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 cursor-pointer"
              >
                ✕
              </button>
            </div>
            <div className="p-4 sm:p-6 space-y-4 text-xs sm:text-sm">
              <p className="text-zinc-700 dark:text-zinc-300">{tx("确定要删除分类「")} <strong>{deletingCategory.icon} {deletingCategory.name}</strong> {tx("」吗？")}</p>
              <div className="p-3 rounded-xl bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800/40 text-amber-800 dark:text-amber-300 text-xs leading-relaxed">{tx("提示：属于该分类的已有交易不会被删除，其分类将被自动重置为「")} <strong>{tx("未分类")}</strong>」。
              </div>
              <div className="pt-2 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setDeletingCategory(null)}
                  className="px-3.5 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-xs font-medium cursor-pointer"
                >{tx("取消")}</button>
                <button
                  type="button"
                  data-testid="confirm-delete-category-btn"
                  onClick={handleDeleteCategory}
                  className="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-700 text-white text-xs font-bold shadow-xs cursor-pointer"
                >{tx("确认删除")}</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 删除标签二次确认弹窗 */}
      {deletingTag && (
        <div className="fixed inset-0 z-50 overflow-y-auto flex items-center justify-center p-4">
          <div className="fixed inset-0 bg-black/50 backdrop-blur-xs" onClick={() => setDeletingTag(null)} />
          <div className="relative bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl w-full max-w-md border border-red-200 dark:border-red-900/60 overflow-hidden z-10 animate-in fade-in zoom-in-95 duration-150">
            <div className="px-4 sm:px-6 py-3.5 sm:py-4 border-b border-zinc-100 dark:border-zinc-800 flex items-center justify-between">
              <h3 className="text-base font-bold text-red-600 dark:text-red-400 flex items-center gap-2">
                <Trash2 className="w-4 h-4" />
                <span>{tx("删除标签确认")}</span>
              </h3>
              <button
                type="button"
                onClick={() => setDeletingTag(null)}
                className="p-1 rounded-lg text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 cursor-pointer"
              >
                ✕
              </button>
            </div>
            <div className="p-4 sm:p-6 space-y-4 text-xs sm:text-sm">
              <p className="text-zinc-700 dark:text-zinc-300">{tx("确定要删除标签「")} <strong>#{deletingTag.name}</strong> {tx("」吗？")}</p>
              <div className="p-3 rounded-xl bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800/40 text-amber-800 dark:text-amber-300 text-xs leading-relaxed">{tx("提示：该标签将从所有已标记的交易流水中移除，其他标签不受影响。")}</div>
              <div className="pt-2 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setDeletingTag(null)}
                  className="px-3.5 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-xs font-medium cursor-pointer"
                >{tx("取消")}</button>
                <button
                  type="button"
                  data-testid="confirm-delete-tag-btn"
                  onClick={handleDeleteTag}
                  className="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-700 text-white text-xs font-bold shadow-xs cursor-pointer"
                >{tx("确认删除")}</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Modals: 账户管理 (编辑/转移/删除/共享) ── */}
      <EditAccountModal
        isOpen={!!editingAccount}
        onClose={() => setEditingAccount(null)}
        account={editingAccount}
        onSuccess={() => {
          fetchSharesMatrix();
          window.dispatchEvent(new CustomEvent('accounts-updated'));
        }}
      />

      <TransferOwnershipModal
        isOpen={!!transferringAccount}
        onClose={() => setTransferringAccount(null)}
        account={transferringAccount}
        onSuccess={() => {
          fetchSharesMatrix();
          window.dispatchEvent(new CustomEvent('accounts-updated'));
        }}
      />

      <DeleteAccountModal
        isOpen={!!deletingAccount}
        onClose={() => setDeletingAccount(null)}
        account={deletingAccount}
        onSuccess={() => {
          fetchSharesMatrix();
          window.dispatchEvent(
            new CustomEvent('accounts-updated', {
              detail: { deletedAccountId: deletingAccount?.id },
            })
          );
        }}
      />

      <AccountSharingModal
        accountId={selectedShareAccountId}
        isOpen={!!selectedShareAccountId}
        onClose={() => setSelectedShareAccountId(null)}
        onSuccess={() => {
          fetchSharesMatrix();
          window.dispatchEvent(new CustomEvent('accounts-updated'));
        }}
        onEdit={(acc) => setEditingAccount(acc)}
        onTransfer={(acc) => setTransferringAccount(acc)}
        onDelete={(acc) => setDeletingAccount(acc)}
      />

      {/* ── Modal: 邀请已有账号加入家庭组 ── */}
      {showInviteModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="fixed inset-0 bg-black/50 backdrop-blur-xs" onClick={() => setShowInviteModal(false)} />
          <div className="relative bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl w-full max-w-md border border-zinc-200 dark:border-zinc-800 overflow-hidden z-10 animate-in fade-in zoom-in-95 duration-150">
            <div className="px-4 sm:px-6 py-3.5 sm:py-4 border-b border-zinc-100 dark:border-zinc-800 flex items-center justify-between">
              <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
                <UserPlus className="w-4 h-4 text-blue-500" />
                <span>{tx("邀请已有账号加入家庭组")}</span>
              </h3>
              <button
                type="button"
                onClick={() => setShowInviteModal(false)}
                className="p-1 rounded-lg text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 cursor-pointer"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleSendInvitation} className="p-4 sm:px-6 sm:py-5 space-y-4">
              <div>
                <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300 mb-1">{tx("被邀请人用户名 (Username)")} <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  required
                  data-testid="invite-member-username-input"
                  placeholder={tx("例如：alice, bob, zhangsan")}
                  value={inviteForm.username}
                  onChange={(e) => setInviteForm({ ...inviteForm, username: e.target.value })}
                  className="w-full px-3.5 py-2.5 text-xs bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none focus:ring-2 focus:ring-zinc-900 dark:focus:ring-white"
                />
                <p className="text-[11px] text-zinc-400 mt-1">{tx("对方须为系统中已注册的账号。发出邀请后，对方在「设置 → 家庭组」中确认同意后方可正式加入。")}</p>
              </div>
              <div>
                <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300 mb-1">{tx("邀请附言 / 留言 (选填)")}</label>
                <textarea
                  rows={3}
                  data-testid="invite-member-message-input"
                  placeholder={tx("例如：一起来共同记录我们的家庭收支吧！")}
                  value={inviteForm.message}
                  onChange={(e) => setInviteForm({ ...inviteForm, message: e.target.value })}
                  className="w-full px-3.5 py-2.5 text-xs bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none focus:ring-2 focus:ring-zinc-900 dark:focus:ring-white resize-none"
                />
              </div>

              <div className="pt-2 flex items-center justify-end gap-2.5">
                <button
                  type="button"
                  onClick={() => setShowInviteModal(false)}
                  className="px-4 py-2 text-xs font-semibold text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800 rounded-xl transition cursor-pointer"
                >{tx("取消")}</button>
                <button
                  type="submit"
                  disabled={inviteLoading || !inviteForm.username.trim()}
                  data-testid="submit-invite-member-btn"
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-xs font-bold rounded-xl shadow-xs transition disabled:opacity-50 cursor-pointer flex items-center gap-1.5"
                >
                  <Send className="w-3.5 h-3.5" />
                  <span>{inviteLoading ? tx("正在发送...") : tx("发送入组邀请")}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── Modal: 新增家庭成员（家庭组管理员/系统管理员） ── */}
      {showAddMemberModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="fixed inset-0 bg-black/50 backdrop-blur-xs" onClick={() => setShowAddMemberModal(false)} />
          <div className="relative bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl w-full max-w-md border border-zinc-200 dark:border-zinc-800 overflow-hidden z-10 animate-in fade-in zoom-in-95 duration-150">
            <div className="px-4 sm:px-6 py-3.5 sm:py-4 border-b border-zinc-100 dark:border-zinc-800 flex items-center justify-between">
              <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
                <Users className="w-4 h-4 text-blue-500" />
                <span>{tx("新增家庭成员")}</span>
              </h3>
              <button
                type="button"
                onClick={() => setShowAddMemberModal(false)}
                className="p-1 rounded-lg text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 cursor-pointer"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleCreateMember} className="p-4 sm:p-6 space-y-4">
              <div>
                <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300 mb-1">{tx("用户名")} <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  required
                  data-testid="new-member-username-input"
                  placeholder={tx("登录账号，例如：bob, zhangsan")}
                  value={newMemberForm.username}
                  onChange={(e) => setNewMemberForm({ ...newMemberForm, username: e.target.value })}
                  className="w-full px-3.5 py-2.5 text-xs bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none focus:ring-2 focus:ring-zinc-900 dark:focus:ring-white"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300 mb-1">{tx("显示名称 / 昵称")}</label>
                <input
                  type="text"
                  data-testid="new-member-name-input"
                  placeholder={tx("例如：张三、陈妈妈")}
                  value={newMemberForm.display_name}
                  onChange={(e) => setNewMemberForm({ ...newMemberForm, display_name: e.target.value })}
                  className="w-full px-3.5 py-2.5 text-xs bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none focus:ring-2 focus:ring-zinc-900 dark:focus:ring-white"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300 mb-1">{tx("初始密码")} <span className="text-red-500">*</span>
                </label>
                <input
                  type="password"
                  required
                  data-testid="new-member-password-input"
                  placeholder={tx("至少 4 位字符")}
                  value={newMemberForm.password}
                  onChange={(e) => setNewMemberForm({ ...newMemberForm, password: e.target.value })}
                  className="w-full px-3.5 py-2.5 text-xs bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none focus:ring-2 focus:ring-zinc-900 dark:focus:ring-white"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300 mb-1">{tx("角色权限分级")}</label>
                <select
                  value={newMemberForm.role}
                  data-testid="new-member-role-select"
                  onChange={(e) => setNewMemberForm({ ...newMemberForm, role: e.target.value })}
                  className="w-full px-3.5 py-2.5 text-xs bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none"
                >
                  <option value="member">{tx("👤 家庭成员（仅可记账与管理个人账户）")}</option>
                  <option value="family_admin">{tx("👑 家庭组管理员（可新增用户、管理家庭组）")}</option>
                </select>
              </div>

              <div className="pt-2 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setShowAddMemberModal(false)}
                  className="px-4 py-2 rounded-xl border border-zinc-200 dark:border-zinc-700 text-xs font-medium text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 cursor-pointer"
                >{tx("取消")}</button>
                <button
                  type="submit"
                  data-testid="confirm-add-member-btn"
                  disabled={addMemberLoading}
                  className="px-4 py-2 rounded-xl bg-zinc-900 hover:bg-zinc-800 dark:bg-white dark:hover:bg-zinc-100 text-white dark:text-zinc-900 text-xs font-bold shadow-xs cursor-pointer disabled:opacity-50"
                >
                  {addMemberLoading ? tx("正在创建...") : tx("确认新增")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
      {/* ── Modal: 移出家庭组确认 ── */}
      {kickingMember && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
          <div className="bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl w-full max-w-sm p-4 sm:p-6 space-y-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-orange-100 dark:bg-orange-950/60 flex items-center justify-center shrink-0">
                <ArrowRight className="w-5 h-5 text-orange-600 dark:text-orange-400" />
              </div>
              <div>
                <h3 className="font-bold text-sm text-zinc-900 dark:text-zinc-100">{tx("移出家庭组")}</h3>
                <p className="text-[11px] text-zinc-500 mt-0.5">{tx("将")} <span className="font-semibold text-zinc-800 dark:text-zinc-200">{kickingMember.display_name || kickingMember.username}</span> {tx("移出当前家庭组。")}</p>
              </div>
            </div>
            <div className="bg-orange-50 dark:bg-orange-950/30 border border-orange-200 dark:border-orange-900/50 rounded-xl p-3 text-[11px] text-orange-700 dark:text-orange-400">{tx("ℹ️ 移出后该成员的账户与交易数据将完整保留，但不再属于本家庭组，也无法访问家庭共享账户。")}</div>
            <div className="flex gap-2 pt-1">
              <button
                type="button"
                onClick={() => setKickingMember(null)}
                disabled={kickMemberLoading}
                className="flex-1 px-4 py-2 rounded-xl border border-zinc-200 dark:border-zinc-700 text-xs font-semibold text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition cursor-pointer disabled:opacity-50"
              >{tx("取消")}</button>
              <button
                type="button"
                onClick={handleKickMember}
                disabled={kickMemberLoading}
                className="flex-1 px-4 py-2 rounded-xl bg-orange-600 hover:bg-orange-700 text-white text-xs font-bold shadow-xs cursor-pointer disabled:opacity-50 transition"
              >
                {kickMemberLoading ? tx("正在移出...") : tx("确认移出")}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Modal: 系统管理员删除用户（需输入管理员密码） ── */}
      {deletingMember && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
          <div className="bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl w-full max-w-sm p-4 sm:p-6 space-y-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-red-100 dark:bg-red-950/60 flex items-center justify-center shrink-0">
                <Trash2 className="w-5 h-5 text-red-600 dark:text-red-400" />
              </div>
              <div>
                <h3 className="font-bold text-sm text-zinc-900 dark:text-zinc-100">{tx("删除用户")}</h3>
                <p className="text-[11px] text-zinc-500 mt-0.5">{tx("即将永久删除")} <span className="font-semibold text-zinc-800 dark:text-zinc-200">{deletingMember.display_name || deletingMember.username}</span> {tx("及其名下所有数据，此操作不可撤销。")}</p>
              </div>
            </div>

            <div className="bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900/50 rounded-xl p-3 text-[11px] text-red-700 dark:text-red-400">{tx("⚠️ 将同时删除：该用户的所有账户、全部交易记录、账户共享设置和登录会话。")}</div>

            <div>
              <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300 mb-1.5">{tx("请输入您的管理员密码以确认操作")}</label>
              <input
                type="password"
                autoFocus
                placeholder={tx("管理员密码")}
                value={deleteAdminPassword}
                onChange={(e) => setDeleteAdminPassword(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleDeleteMember()}
                className="w-full px-3.5 py-2.5 text-xs bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none focus:ring-2 focus:ring-red-500"
              />
            </div>

            <div className="flex gap-2 pt-1">
              <button
                type="button"
                onClick={() => { setDeletingMember(null); setDeleteAdminPassword(''); }}
                disabled={deleteMemberLoading}
                className="flex-1 px-4 py-2 rounded-xl border border-zinc-200 dark:border-zinc-700 text-xs font-semibold text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition cursor-pointer disabled:opacity-50"
              >{tx("取消")}</button>
              <button
                type="button"
                onClick={handleDeleteMember}
                disabled={deleteMemberLoading || !deleteAdminPassword}
                className="flex-1 px-4 py-2 rounded-xl bg-red-600 hover:bg-red-700 text-white text-xs font-bold shadow-xs cursor-pointer disabled:opacity-50 transition"
              >
                {deleteMemberLoading ? tx("正在删除...") : tx("确认删除")}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Modal: 系统管理员重置用户密码 ── */}
      {resetPasswordMember && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
          <div className="bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl w-full max-w-sm p-4 sm:p-6 space-y-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-blue-100 dark:bg-blue-950/60 flex items-center justify-center shrink-0">
                <KeyRound className="w-5 h-5 text-blue-600 dark:text-blue-400" />
              </div>
              <div>
                <h3 className="font-bold text-sm text-zinc-900 dark:text-zinc-100">{tx("重置用户密码")}</h3>
                <p className="text-[11px] text-zinc-500 mt-0.5">{tx("为")} <span className="font-semibold text-zinc-800 dark:text-zinc-200">{resetPasswordMember.display_name || resetPasswordMember.username}</span> {tx("设置新密码，重置后该用户所有在线设备将被强制退出。")}</p>
              </div>
            </div>

            <form onSubmit={handleResetMemberPassword} className="space-y-3">
              <div>
                <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300 mb-1.5">{tx("新密码（至少6位）")}</label>
                <input
                  type="password"
                  autoFocus
                  required
                  minLength={6}
                  placeholder={tx("请输入新密码")}
                  value={resetNewPassword}
                  onChange={(e) => setResetNewPassword(e.target.value)}
                  className="w-full px-3.5 py-2.5 text-xs bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300 mb-1.5">{tx("确认新密码")}</label>
                <input
                  type="password"
                  required
                  minLength={6}
                  placeholder={tx("再次输入新密码")}
                  value={resetConfirmPassword}
                  onChange={(e) => setResetConfirmPassword(e.target.value)}
                  className="w-full px-3.5 py-2.5 text-xs bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div className="flex gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => { setResetPasswordMember(null); setResetNewPassword(''); setResetConfirmPassword(''); }}
                  disabled={resetPasswordLoading}
                  className="flex-1 px-4 py-2 rounded-xl border border-zinc-200 dark:border-zinc-700 text-xs font-semibold text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition cursor-pointer disabled:opacity-50"
                >{tx("取消")}</button>
                <button
                  type="submit"
                  disabled={resetPasswordLoading || resetNewPassword.length < 6 || resetNewPassword !== resetConfirmPassword}
                  className="flex-1 px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-700 text-white text-xs font-bold shadow-xs cursor-pointer disabled:opacity-50 transition"
                >
                  {resetPasswordLoading ? tx("正在重置...") : tx("确认重置")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── Create API Key Modal ── */}
      {showCreateApiKeyModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div
            className="fixed inset-0 bg-black/50 backdrop-blur-xs"
            onClick={() => setShowCreateApiKeyModal(false)}
          />
          <div className="relative w-full max-w-md bg-white dark:bg-zinc-900 rounded-2xl border border-zinc-200 dark:border-zinc-800 p-4 sm:p-6 shadow-2xl z-10 space-y-4 animate-in zoom-in-95 duration-150">
            <div>
              <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
                <Key className="w-4.5 h-4.5 text-indigo-500" />
                <span>{tx("生成新 API 密钥")}</span>
              </h3>
              <p className="text-xs text-zinc-500 mt-1">{tx("为自动化记账脚本或快捷指令颁发独立令牌。")}</p>
            </div>

            <form onSubmit={handleCreateApiKey} className="space-y-4 text-xs">
              <div className="space-y-1">
                <label className="font-semibold text-zinc-700 dark:text-zinc-300">{tx("用途描述 (必填)")}</label>
                <input
                  type="text"
                  required
                  value={apiKeyName}
                  onChange={(e) => setApiKeyName(e.target.value)}
                  placeholder={tx("例如：iPhone 快捷指令自动记账、招行邮件爬虫")}
                  className="w-full px-3.5 py-2.5 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none text-zinc-900 dark:text-zinc-100 focus:ring-2 focus:ring-indigo-500"
                />
              </div>

              <div className="space-y-1">
                <label className="font-semibold text-zinc-700 dark:text-zinc-300">{tx("有效期")}</label>
                <select
                  value={apiKeyExpiresDays}
                  onChange={(e) => setApiKeyExpiresDays(e.target.value)}
                  className="w-full px-3.5 py-2.5 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none text-zinc-900 dark:text-zinc-100"
                >
                  <option value="30">{tx("30 天")}</option>
                  <option value="90">{tx("90 天")}</option>
                  <option value="180">{tx("180 天 (半年)")}</option>
                  <option value="365">{tx("365 天 (1年)")}</option>
                  <option value="forever">{tx("永久有效")}</option>
                </select>
              </div>

              <div className="flex gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowCreateApiKeyModal(false)}
                  disabled={createApiKeyLoading}
                  className="flex-1 px-4 py-2 rounded-xl border border-zinc-200 dark:border-zinc-700 text-xs font-semibold text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition cursor-pointer"
                >{tx("取消")}</button>
                <button
                  type="submit"
                  disabled={createApiKeyLoading || !apiKeyName.trim()}
                  className="flex-1 px-4 py-2 rounded-xl bg-zinc-900 dark:bg-zinc-100 hover:bg-zinc-800 text-white dark:text-zinc-900 text-xs font-bold shadow-xs cursor-pointer disabled:opacity-50 transition"
                >
                  {createApiKeyLoading ? tx("正在生成...") : tx("立即生成")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── API Key Created Success Modal (Only Shown Once) ── */}
      {newlyCreatedKey && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div
            className="fixed inset-0 bg-black/60 backdrop-blur-xs"
            onClick={() => setNewlyCreatedKey(null)}
          />
          <div className="relative w-full max-w-lg bg-white dark:bg-zinc-900 rounded-2xl border border-amber-200 dark:border-amber-900/60 p-5 sm:p-6 shadow-2xl z-10 space-y-4 animate-in zoom-in-95 duration-150">
            <div className="flex items-start gap-3">
              <div className="w-10 h-10 rounded-xl bg-amber-50 dark:bg-amber-950/40 text-amber-600 dark:text-amber-400 flex items-center justify-center shrink-0 border border-amber-200 dark:border-amber-800">
                <Key className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-100">{tx("API Key 生成成功！")}</h3>
                <p className="text-xs text-amber-600 dark:text-amber-400 font-semibold mt-0.5">{tx("⚠️ 请立即复制并妥善保存。出于安全原因，此完整密钥仅在本次弹窗展示一次！")}</p>
              </div>
            </div>

            <div className="space-y-1.5 pt-1">
              <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">{tx("密钥内容 (")} {newlyCreatedKey.name})
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  readOnly
                  value={newlyCreatedKey.raw_key}
                  className="w-full px-3 py-2.5 bg-zinc-100 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none font-mono text-xs text-zinc-900 dark:text-zinc-100 select-all"
                />
                <button
                  type="button"
                  onClick={() => {
                    navigator.clipboard.writeText(newlyCreatedKey.raw_key);
                    setCopiedKey(true);
                    showToast(tx("已复制 API Key 到剪贴板"), 'success');
                    setTimeout(() => setCopiedKey(false), 2000);
                  }}
                  className="px-3.5 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-xs font-semibold shadow-xs flex items-center gap-1.5 shrink-0 transition cursor-pointer"
                >
                  <Copy className="w-3.5 h-3.5" />
                  <span>{copiedKey ? tx("已复制!") : tx("复制")}</span>
                </button>
              </div>
            </div>

            <div className="bg-zinc-50 dark:bg-zinc-800/50 p-3 rounded-xl border border-zinc-200/80 dark:border-zinc-800 text-[11px] text-zinc-500 space-y-1 font-mono">
              <div className="font-semibold text-zinc-700 dark:text-zinc-300 font-sans">{tx("快捷使用示例：")}</div>
              <div className="text-zinc-600 dark:text-zinc-400 select-all">{tx("Authorization: Bearer")} {newlyCreatedKey.raw_key}
              </div>
            </div>

            <div className="pt-2">
              <button
                type="button"
                onClick={() => {
                  setNewlyCreatedKey(null);
                  setShowCreateApiKeyModal(false);
                }}
                className="w-full py-2.5 rounded-xl bg-zinc-900 dark:bg-zinc-100 hover:bg-zinc-800 text-white dark:text-zinc-900 text-xs font-bold shadow-xs transition cursor-pointer"
              >{tx("我已妥善保存，关闭弹窗")}</button>
            </div>
          </div>
        </div>
      )}

      {/* 结算币种对齐更换提示弹窗 */}
      <CurrencyChangeAlertModal
        isOpen={currencyChangeModal.open}
        data={currencyChangeModal.data}
        onClose={() => setCurrencyChangeModal({ open: false, data: {} })}
      />
    </div>
  );
}
