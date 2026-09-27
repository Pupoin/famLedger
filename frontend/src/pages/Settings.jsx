import React, { useState, useEffect, useRef } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  ChevronLeft,
  Settings as SettingsIcon,
  Sliders,
  User,
  Shield,
  KeyRound,
  SlidersHorizontal,
  Database,
  Globe,
  Plus,
  Trash2,
  ExternalLink,
  CheckCircle2,
  XCircle,
  Eye,
  EyeOff,
  Sun,
  Moon,
  Clock,
  ArrowRight,
  Sparkles,
} from 'lucide-react';
import { useAuth } from '../auth/AuthContext';
import { useTheme } from '../ThemeContext';
import { useCurrency } from '../CurrencyContext';
import { useDateFormat } from '../DateFormatContext';
import { useToast } from '../ToastContext';
import { fetchWithAuth } from '../api/fetchWithAuth';
import { uploadAvatar } from '../api/expenses';
import Avatar from '../components/Avatar';
import { API_BASE } from '../config';

export default function Settings() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = searchParams.get('tab') || 'preferences';
  const { t, i18n } = useTranslation();
  const { user, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const { currency, setCurrency, currencies, privacyMode, togglePrivacyMode } = useCurrency();
  const { dateFormat, setDateFormat } = useDateFormat();
  const { showToast } = useToast();

  const fileInputRef = useRef(null);
  const [avatarKey, setAvatarKey] = useState(0);

  // SSO / OIDC Providers state
  const [ssoProviders, setSsoProviders] = useState([]);
  const [ssoLoading, setSsoLoading] = useState(false);
  const [showAddOidcModal, setShowAddOidcModal] = useState(false);
  const [oidcForm, setOidcForm] = useState({
    name: 'authentik',
    label: 'Authentik SSO',
    issuer: 'https://auth.example.lan/application/o/famledger',
    client_id: '',
    client_secret: '',
    allow_jit: true,
    allowed_domains: '',
  });

  // Password & Security
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [passwordLoading, setPasswordLoading] = useState(false);
  const [staySignedIn, setStaySignedIn] = useState(true);

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

  const setTab = (tab) => {
    const p = new URLSearchParams(searchParams);
    p.set('tab', tab);
    setSearchParams(p);
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
    if (activeTab === 'oidc') {
      fetchSsoProviders();
    }
  }, [activeTab]);

  // Language change
  const handleLanguageChange = (lang) => {
    i18n.changeLanguage(lang);
    localStorage.setItem('famledger_lang', lang);
    showToast(lang === 'zh' ? '语言已切换为简体中文' : 'Language set to English', 'success');
  };

  // Avatar upload
  const handleAvatarUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      await uploadAvatar(file);
      setAvatarKey((k) => k + 1);
      showToast(t('common.success', '操作成功'), 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
  };

  // Password change
  const handleChangePassword = async (e) => {
    e.preventDefault();
    if (newPassword !== confirmPassword) {
      showToast('两次输入的新密码不一致', 'error');
      return;
    }
    setPasswordLoading(true);
    try {
      const res = await fetchWithAuth(`${API_BASE}/auth/change-password`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      });
      if (res.ok) {
        showToast('密码修改成功', 'success');
        setCurrentPassword('');
        setNewPassword('');
        setConfirmPassword('');
      } else {
        const err = await res.json().catch(() => ({}));
        showToast(err.detail || '密码修改失败', 'error');
      }
    } catch {
      showToast('网络错误，请稍后重试', 'error');
    } finally {
      setPasswordLoading(false);
    }
  };

  // Create OIDC Provider
  const handleCreateOidcProvider = async (e) => {
    e.preventDefault();
    try {
      const domains = oidcForm.allowed_domains
        .split(',')
        .map((d) => d.trim())
        .filter(Boolean);

      const res = await fetchWithAuth('/api/v1/auth/sso/providers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: oidcForm.name.toLowerCase().trim(),
          label: oidcForm.label.trim(),
          issuer: oidcForm.issuer.trim(),
          client_id: oidcForm.client_id.trim(),
          client_secret: oidcForm.client_secret.trim(),
          enabled: true,
          settings: {
            allow_jit: oidcForm.allow_jit,
            allowed_domains: domains,
            default_role: 'member',
          },
        }),
      });

      if (res.ok) {
        showToast('OIDC SSO 提供商配置已保存', 'success');
        setShowAddOidcModal(false);
        setOidcForm({
          name: '',
          label: '',
          issuer: '',
          client_id: '',
          client_secret: '',
          allow_jit: true,
          allowed_domains: '',
        });
        fetchSsoProviders();
      } else {
        const err = await res.json();
        showToast(err.detail || '保存失败', 'error');
      }
    } catch (err) {
      showToast('请求失败，请检查参数', 'error');
    }
  };

  // Delete OIDC Provider
  const handleDeleteOidc = async (name) => {
    if (!window.confirm(`确定要移除 SSO 提供商 "${name}" 吗？`)) return;
    try {
      const res = await fetchWithAuth(`/api/v1/auth/sso/providers/${name}`, {
        method: 'DELETE',
      });
      if (res.ok) {
        showToast('SSO 提供商已删除', 'success');
        fetchSsoProviders();
      }
    } catch {
      showToast('删除失败', 'error');
    }
  };

  return (
    <div className="max-w-6xl mx-auto pb-12">
      {/* ── Top Header & Breadcrumb ── */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2 text-xs text-zinc-500 mb-1">
            <Link to="/" className="hover:text-zinc-900 dark:hover:text-white transition-colors">
              Home
            </Link>
            <span>/</span>
            <span className="font-semibold text-zinc-900 dark:text-zinc-100">
              {t('settings.title', 'Settings')}
            </span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-zinc-900 dark:text-zinc-100">
            {t('settings.title', 'Settings')}
          </h1>
        </div>

        <Link
          to="/"
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-zinc-100 hover:bg-zinc-200 dark:bg-zinc-800 dark:hover:bg-zinc-700 text-zinc-700 dark:text-zinc-200 transition-colors"
        >
          <ChevronLeft className="w-3.5 h-3.5" />
          <span>{t('settings.back', 'Back')}</span>
          <kbd className="hidden sm:inline-block ml-1 px-1.5 py-0.5 text-[10px] font-mono bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded shadow-2xs">
            ESC
          </kbd>
        </Link>
      </div>

      {/* ── Main Two-Column Layout (Sure Style) ── */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-8 items-start">
        {/* Left Sub-Sidebar (Sure Exact Settings Menu) */}
        <aside className="lg:col-span-1 space-y-6">
          {/* General Section */}
          <div className="space-y-1">
            <span className="text-[11px] font-bold text-zinc-400 dark:text-zinc-500 tracking-wider uppercase px-3 block">
              {t('settings.general', 'General')}
            </span>
            {[
              { id: 'preferences', label: t('settings.preferences', 'Preferences'), icon: Sliders },
              { id: 'profile', label: t('settings.profile', 'Profile Info'), icon: User },
              { id: 'security', label: t('settings.security', 'Security'), icon: Shield },
            ].map((tab) => {
              const Icon = tab.icon;
              const isCurrent = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setTab(tab.id)}
                  className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-medium transition-all ${
                    isCurrent
                      ? 'bg-zinc-100 dark:bg-zinc-800 text-zinc-900 dark:text-white font-semibold shadow-xs'
                      : 'text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50 dark:hover:bg-zinc-800/50 hover:text-zinc-900 dark:hover:text-zinc-200'
                  }`}
                >
                  <Icon className={`w-4 h-4 ${isCurrent ? 'text-zinc-900 dark:text-white' : 'text-zinc-400'}`} />
                  <span>{tab.label}</span>
                </button>
              );
            })}
          </div>

          {/* Automations & Rules Section */}
          <div className="space-y-1">
            <span className="text-[11px] font-bold text-zinc-400 dark:text-zinc-500 tracking-wider uppercase px-3 block">
              {t('settings.rules', 'Rules & Automations')}
            </span>
            <button
              onClick={() => setTab('rules')}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-medium transition-all ${
                activeTab === 'rules'
                  ? 'bg-zinc-100 dark:bg-zinc-800 text-zinc-900 dark:text-white font-semibold shadow-xs'
                  : 'text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50 dark:hover:bg-zinc-800/50 hover:text-zinc-900 dark:hover:text-zinc-200'
              }`}
            >
              <SlidersHorizontal className={`w-4 h-4 ${activeTab === 'rules' ? 'text-zinc-900 dark:text-white' : 'text-zinc-400'}`} />
              <span>{t('settings.rules', 'Rules & Automations')}</span>
            </button>
          </div>

          {/* Advanced / OIDC Section */}
          <div className="space-y-1">
            <span className="text-[11px] font-bold text-zinc-400 dark:text-zinc-500 tracking-wider uppercase px-3 block">
              Advanced / SSO
            </span>
            <button
              onClick={() => setTab('oidc')}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-medium transition-all ${
                activeTab === 'oidc'
                  ? 'bg-zinc-100 dark:bg-zinc-800 text-zinc-900 dark:text-white font-semibold shadow-xs'
                  : 'text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50 dark:hover:bg-zinc-800/50 hover:text-zinc-900 dark:hover:text-zinc-200'
              }`}
            >
              <KeyRound className={`w-4 h-4 ${activeTab === 'oidc' ? 'text-zinc-900 dark:text-white' : 'text-zinc-400'}`} />
              <span>{t('settings.oidc', 'OIDC / SSO')}</span>
            </button>
            <button
              onClick={() => setTab('hosting')}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-medium transition-all ${
                activeTab === 'hosting'
                  ? 'bg-zinc-100 dark:bg-zinc-800 text-zinc-900 dark:text-white font-semibold shadow-xs'
                  : 'text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50 dark:hover:bg-zinc-800/50 hover:text-zinc-900 dark:hover:text-zinc-200'
              }`}
            >
              <Sparkles className={`w-4 h-4 ${activeTab === 'hosting' ? 'text-zinc-900 dark:text-white' : 'text-zinc-400'}`} />
              <span>{t('settings.hosting', 'Self-Hosting & AI')}</span>
            </button>
            <button
              onClick={() => setTab('data')}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-medium transition-all ${
                activeTab === 'data'
                  ? 'bg-zinc-100 dark:bg-zinc-800 text-zinc-900 dark:text-white font-semibold shadow-xs'
                  : 'text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50 dark:hover:bg-zinc-800/50 hover:text-zinc-900 dark:hover:text-zinc-200'
              }`}
            >
              <Database className={`w-4 h-4 ${activeTab === 'data' ? 'text-zinc-900 dark:text-white' : 'text-zinc-400'}`} />
              <span>{t('settings.data', 'Data & Backup')}</span>
            </button>
          </div>
        </aside>

        {/* Right Main Content Pane (Sure Card Sections) */}
        <main className="lg:col-span-3 space-y-6">
          {/* ══════════════════════════════════════════════════════════════ */}
          {/* TAB 1: PREFERENCES                                            */}
          {/* ══════════════════════════════════════════════════════════════ */}
          {activeTab === 'preferences' && (
            <div className="space-y-6">
              {/* General Preferences Card */}
              <div className="bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 rounded-2xl p-6 shadow-xs space-y-5">
                <div>
                  <h2 className="text-base font-bold text-zinc-900 dark:text-zinc-100">
                    {t('settings.general', 'General')}
                  </h2>
                  <p className="text-xs text-zinc-500 mt-0.5">
                    Configure your language, currency, and display settings
                  </p>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  {/* Language Selector */}
                  <div className="space-y-1.5">
                    <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                      {t('settings.language', 'Language')}
                    </label>
                    <select
                      value={i18n.language?.startsWith('en') ? 'en' : 'zh'}
                      onChange={(e) => handleLanguageChange(e.target.value)}
                      className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl text-xs font-medium text-zinc-900 dark:text-white outline-none focus:border-zinc-900 transition-colors"
                    >
                      <option value="zh">简体中文 (Chinese - zh)</option>
                      <option value="en">English (en)</option>
                    </select>
                  </div>

                  {/* Currency Selector */}
                  <div className="space-y-1.5">
                    <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                      {t('settings.currency', 'Family Base Currency')}
                    </label>
                    <select
                      value={currency}
                      onChange={(e) => setCurrency(e.target.value)}
                      className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl text-xs font-medium text-zinc-900 dark:text-white outline-none focus:border-zinc-900 transition-colors"
                    >
                      {currencies.map((c) => (
                        <option key={c.code} value={c.code}>
                          {c.code} ({c.symbol})
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* Date Format */}
                  <div className="space-y-1.5">
                    <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                      {t('settings.dateFormat', 'Date Format')}
                    </label>
                    <select
                      value={dateFormat}
                      onChange={(e) => setDateFormat(e.target.value)}
                      className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl text-xs font-medium text-zinc-900 dark:text-white outline-none focus:border-zinc-900 transition-colors"
                    >
                      <option value="YYYY-MM-DD">YYYY-MM-DD (2026-09-27)</option>
                      <option value="MM/DD/YYYY">MM/DD/YYYY (09/27/2026)</option>
                      <option value="DD/MM/YYYY">DD/MM/YYYY (27/09/2026)</option>
                    </select>
                  </div>

                  {/* Budget Month Starts On */}
                  <div className="space-y-1.5">
                    <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                      {t('settings.budgetStart', 'Budget Month Starts On')}
                    </label>
                    <select
                      defaultValue="1"
                      className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl text-xs font-medium text-zinc-900 dark:text-white outline-none focus:border-zinc-900 transition-colors"
                    >
                      <option value="1">1st of month</option>
                      <option value="5">5th of month</option>
                      <option value="10">10th of month (招行出账日)</option>
                      <option value="20">20th of month</option>
                      <option value="25">25th of month</option>
                    </select>
                  </div>

                  {/* Timezone */}
                  <div className="space-y-1.5">
                    <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                      {t('settings.timezone', 'Timezone')}
                    </label>
                    <select
                      value={timezone}
                      onChange={(e) => {
                        setTimezone(e.target.value);
                        localStorage.setItem('famledger_tz', e.target.value);
                        showToast('时区设置已保存', 'info');
                      }}
                      className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl text-xs font-medium text-zinc-900 dark:text-white outline-none focus:border-zinc-900 transition-colors"
                    >
                      <option value="Asia/Shanghai">(+08:00) Asia/Shanghai (北京时间)</option>
                      <option value="UTC">(+00:00) UTC (协调世界时)</option>
                      <option value="America/New_York">(-05:00) America/New_York (美东时间)</option>
                      <option value="Europe/London">(+00:00) Europe/London (伦敦)</option>
                      <option value="Asia/Tokyo">(+09:00) Asia/Tokyo (东京)</option>
                    </select>
                  </div>

                  {/* Default Account Order */}
                  <div className="space-y-1.5">
                    <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                      {t('settings.accountOrder', 'Default Account Order')}
                    </label>
                    <select
                      value={accountOrder}
                      onChange={(e) => {
                        setAccountOrder(e.target.value);
                        localStorage.setItem('famledger_acc_order', e.target.value);
                        showToast('账户排序规则已更新', 'info');
                      }}
                      className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl text-xs font-medium text-zinc-900 dark:text-white outline-none focus:border-zinc-900 transition-colors"
                    >
                      <option value="name_asc">Name (A-Z)</option>
                      <option value="balance_desc">Balance (High to Low)</option>
                      <option value="activity">Most Active</option>
                    </select>
                  </div>
                </div>

                {/* Privacy Mode Toggle */}
                <div className="pt-4 border-t border-zinc-100 dark:border-zinc-800 flex items-center justify-between">
                  <div>
                    <span className="text-xs font-bold text-zinc-900 dark:text-zinc-100 block">
                      {t('settings.privacyMode', 'Privacy Mode')}
                    </span>
                    <span className="text-[11px] text-zinc-500">
                      {t('settings.privacyModeDesc', 'Blurs sensitive amounts across the interface')}
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
            <div className="space-y-6">
              <div className="bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 rounded-2xl p-6 shadow-xs space-y-6">
                <div className="flex items-center justify-between">
                  <div>
                    <h2 className="text-base font-bold text-zinc-900 dark:text-zinc-100">
                      {t('settings.oidc', 'OIDC / SSO Single Sign-On')}
                    </h2>
                    <p className="text-xs text-zinc-500 mt-0.5">
                      Connect Authentik, Keycloak, or custom OIDC IdP for centralized identity and JIT provisioning
                    </p>
                  </div>
                  <button
                    onClick={() => setShowAddOidcModal(true)}
                    className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-semibold rounded-lg bg-zinc-900 hover:bg-zinc-800 text-white shadow-xs transition-colors"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    <span>{t('settings.addProvider', 'Add OIDC Provider')}</span>
                  </button>
                </div>

                {/* SSO Providers List */}
                <div className="space-y-3">
                  {ssoLoading ? (
                    <div className="py-8 text-center text-xs text-zinc-400">Loading SSO providers...</div>
                  ) : ssoProviders.length === 0 ? (
                    <div className="p-8 text-center border border-dashed border-zinc-200 dark:border-zinc-800 rounded-xl">
                      <KeyRound className="w-8 h-8 text-zinc-300 dark:text-zinc-600 mx-auto mb-2" />
                      <p className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
                        {t('settings.noProviders', 'No SSO providers configured yet')}
                      </p>
                      <p className="text-[11px] text-zinc-400 mt-1">
                        Add Authentik, Keycloak, or Google OIDC to enable single sign-on for family members.
                      </p>
                    </div>
                  ) : (
                    ssoProviders.map((p) => (
                      <div
                        key={p.name}
                        className="flex items-center justify-between p-4 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-800/40"
                      >
                        <div className="flex items-center gap-3">
                          <div className="w-9 h-9 rounded-lg bg-zinc-900 text-white flex items-center justify-center font-bold text-xs uppercase">
                            {p.name.slice(0, 2)}
                          </div>
                          <div>
                            <span className="text-xs font-bold text-zinc-900 dark:text-zinc-100 block">
                              {p.label}
                            </span>
                            <span className="text-[11px] font-mono text-zinc-400 block truncate max-w-sm">
                              {p.issuer}
                            </span>
                          </div>
                        </div>

                        <div className="flex items-center gap-2">
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300">
                            <CheckCircle2 className="w-3 h-3" />
                            Active
                          </span>
                          <a
                            href={`/api/v1/auth/sso/${p.name}/authorize`}
                            className="p-1.5 rounded-lg text-zinc-500 hover:text-zinc-900 dark:hover:text-white hover:bg-zinc-100 dark:hover:bg-zinc-700 transition-colors"
                            title="测试此 SSO 登录"
                            target="_blank"
                            rel="noreferrer"
                          >
                            <ExternalLink className="w-4 h-4" />
                          </a>
                          <button
                            onClick={() => handleDeleteOidc(p.name)}
                            className="p-1.5 rounded-lg text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-950/30 transition-colors"
                            title="移除此提供商"
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
          )}

          {/* ══════════════════════════════════════════════════════════════ */}
          {/* TAB 3: RULES & AUTOMATIONS (Blueprint Section 8 & 9)          */}
          {/* ══════════════════════════════════════════════════════════════ */}
          {activeTab === 'rules' && (
            <div className="space-y-6">
              <div className="bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 rounded-2xl p-6 shadow-xs space-y-6">
                <div className="flex items-center justify-between">
                  <div>
                    <h2 className="text-base font-bold text-zinc-900 dark:text-zinc-100">
                      {t('settings.automations', 'Automated Pipelines')}
                    </h2>
                    <p className="text-xs text-zinc-500 mt-0.5">
                      Configure high-confidence auto-matching, refunds allocation, and categorization rules
                    </p>
                  </div>
                  <Link
                    to="/rules"
                    className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-semibold rounded-lg bg-zinc-900 hover:bg-zinc-800 text-white shadow-xs transition-colors"
                  >
                    <span>{t('nav.rules', 'Rules Pipeline')}</span>
                    <ArrowRight className="w-3.5 h-3.5" />
                  </Link>
                </div>

                <div className="space-y-4 pt-2 divide-y divide-zinc-100 dark:divide-zinc-800">
                  {/* Auto Transfer */}
                  <div className="pt-4 flex items-center justify-between">
                    <div>
                      <span className="text-xs font-bold text-zinc-900 dark:text-zinc-100 block">
                        {t('settings.autoTransfer', 'Silent Auto-Transfer Matching (≤ 2 days)')}
                      </span>
                      <span className="text-[11px] text-zinc-500 max-w-lg block mt-0.5">
                        {t('settings.autoTransferDesc', 'Automatically combines matching outflow and inflow into a single transfer')}
                      </span>
                    </div>
                    <button
                      onClick={() => setAutoTransfer(!autoTransfer)}
                      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
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
                  <div className="pt-4 flex items-center justify-between">
                    <div>
                      <span className="text-xs font-bold text-zinc-900 dark:text-zinc-100 block">
                        {t('settings.autoRefund', 'Smart Refund Allocation & Current Period Offsetting')}
                      </span>
                      <span className="text-[11px] text-zinc-500 max-w-lg block mt-0.5">
                        {t('settings.autoRefundDesc', 'Allocates refunds to offset current living expenses without altering past accounting months')}
                      </span>
                    </div>
                    <button
                      onClick={() => setAutoRefund(!autoRefund)}
                      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
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
          {/* TAB 4: SECURITY                                               */}
          {/* ══════════════════════════════════════════════════════════════ */}
          {activeTab === 'security' && (
            <div className="space-y-6">
              {/* Password Change Card */}
              <div className="bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 rounded-2xl p-6 shadow-xs space-y-5">
                <div>
                  <h2 className="text-base font-bold text-zinc-900 dark:text-zinc-100">
                    {t('settings.changePassword', 'Change Password')}
                  </h2>
                  <p className="text-xs text-zinc-500 mt-0.5">
                    Update your account password to maintain security
                  </p>
                </div>

                <form onSubmit={handleChangePassword} className="space-y-3 max-w-md">
                  <div className="space-y-1">
                    <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                      {t('settings.currentPassword', 'Current Password')}
                    </label>
                    <input
                      type="password"
                      value={currentPassword}
                      onChange={(e) => setCurrentPassword(e.target.value)}
                      required
                      className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl text-xs outline-none focus:border-zinc-900 transition-colors"
                    />
                  </div>

                  <div className="space-y-1">
                    <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                      {t('settings.newPassword', 'New Password')}
                    </label>
                    <input
                      type="password"
                      value={newPassword}
                      onChange={(e) => setNewPassword(e.target.value)}
                      required
                      className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl text-xs outline-none focus:border-zinc-900 transition-colors"
                    />
                  </div>

                  <div className="space-y-1">
                    <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                      {t('settings.confirmPassword', 'Confirm Password')}
                    </label>
                    <input
                      type="password"
                      value={confirmPassword}
                      onChange={(e) => setConfirmPassword(e.target.value)}
                      required
                      className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl text-xs outline-none focus:border-zinc-900 transition-colors"
                    />
                  </div>

                  <button
                    type="submit"
                    disabled={passwordLoading}
                    className="mt-2 inline-flex items-center justify-center px-4 py-2 text-xs font-semibold rounded-lg bg-zinc-900 hover:bg-zinc-800 text-white shadow-xs transition-colors"
                  >
                    {passwordLoading ? 'Updating...' : t('common.save', 'Save')}
                  </button>
                </form>
              </div>

              {/* Stay Signed In Card */}
              <div className="bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 rounded-2xl p-6 shadow-xs flex items-center justify-between">
                <div>
                  <span className="text-xs font-bold text-zinc-900 dark:text-zinc-100 block">
                    {t('settings.staySignedIn', 'Stay Signed In')}
                  </span>
                  <span className="text-[11px] text-zinc-500">
                    {t('settings.staySignedInDesc', 'Remember login session on this browser for 30 days')}
                  </span>
                </div>
                <button
                  onClick={() => setStaySignedIn(!staySignedIn)}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                    staySignedIn ? 'bg-zinc-900 dark:bg-emerald-600' : 'bg-zinc-200 dark:bg-zinc-700'
                  }`}
                >
                  <span
                    className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                      staySignedIn ? 'translate-x-6' : 'translate-x-1'
                    }`}
                  />
                </button>
              </div>
            </div>
          )}

          {/* ══════════════════════════════════════════════════════════════ */}
          {/* TAB 5: PROFILE                                                */}
          {/* ══════════════════════════════════════════════════════════════ */}
          {activeTab === 'profile' && (
            <div className="bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 rounded-2xl p-6 shadow-xs space-y-6">
              <div>
                <h2 className="text-base font-bold text-zinc-900 dark:text-zinc-100">
                  {t('settings.profile', 'Profile Info')}
                </h2>
                <p className="text-xs text-zinc-500 mt-0.5">
                  Manage your display name and user identity
                </p>
              </div>

              <div className="flex items-center gap-4">
                <div
                  key={avatarKey}
                  onClick={() => fileInputRef.current?.click()}
                  className="cursor-pointer group relative"
                  title="点击更换头像"
                >
                  <Avatar user={user?.displayName || 'QQ'} size="lg" />
                  <div className="absolute inset-0 bg-black/40 rounded-full opacity-0 group-hover:opacity-100 flex items-center justify-center transition-opacity text-white text-[10px] font-semibold">
                    Change
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
                    {user?.displayName || user?.username || 'QQ'}
                  </span>
                  <span className="text-xs text-zinc-500 block">
                    Role: {user?.role || 'Owner (Family Admin)'}
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* ══════════════════════════════════════════════════════════════ */}
          {/* TAB 6: DATA & BACKUP                                          */}
          {/* ══════════════════════════════════════════════════════════════ */}
          {activeTab === 'data' && (
            <div className="bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 rounded-2xl p-6 shadow-xs space-y-6">
              <div>
                <h2 className="text-base font-bold text-zinc-900 dark:text-zinc-100">
                  {t('settings.data', 'Data & Backup')}
                </h2>
                <p className="text-xs text-zinc-500 mt-0.5">
                  Export financial archives, SQLite/PostgreSQL backups, and transaction history
                </p>
              </div>

              <div className="space-y-3">
                <a
                  href="/api/export/csv"
                  download
                  className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-800 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-700 transition-colors shadow-2xs"
                >
                  <Database className="w-4 h-4 text-zinc-500" />
                  <span>导出全部流水 (CSV)</span>
                </a>
              </div>
            </div>
          )}

          {/* ══════════════════════════════════════════════════════════════ */}
          {/* TAB 7: SELF-HOSTING & AI ASSISTANT                            */}
          {/* ══════════════════════════════════════════════════════════════ */}
          {activeTab === 'hosting' && (
            <div className="bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 rounded-2xl p-6 shadow-xs space-y-6">
              <div>
                <h2 className="text-base font-bold text-zinc-900 dark:text-zinc-100">
                  {t('settings.hosting', 'Self-Hosting & AI')}
                </h2>
                <p className="text-xs text-zinc-500 mt-0.5">
                  {t('settings.aiAssistant', 'AI Assistant & LLM Configuration')} (OpenAI, Anthropic Claude, Local Ollama)
                </p>
              </div>

              <div className="space-y-4 max-w-xl text-xs">
                {/* AI Provider */}
                <div className="space-y-1.5">
                  <label className="font-semibold text-zinc-700 dark:text-zinc-300">AI Provider</label>
                  <div className="grid grid-cols-2 gap-2">
                    {['openai', 'anthropic'].map((p) => (
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
                        {p === 'openai' ? 'OpenAI / Compatible' : 'Anthropic (Claude)'}
                      </button>
                    ))}
                  </div>
                </div>

                {/* API Key */}
                <div className="space-y-1.5">
                  <label className="font-semibold text-zinc-700 dark:text-zinc-300">Access Token / API Key</label>
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
                  <label className="font-semibold text-zinc-700 dark:text-zinc-300">API Base URL (Optional)</label>
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
                  <label className="font-semibold text-zinc-700 dark:text-zinc-300">Default Model</label>
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
                  onClick={() => showToast('AI 服务配置已持久化至本地环境', 'success')}
                  className="mt-2 inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold rounded-lg bg-zinc-900 hover:bg-zinc-800 text-white shadow-xs transition-colors"
                >
                  <Sparkles className="w-3.5 h-3.5" />
                  <span>保存配置</span>
                </button>
              </div>
            </div>
          )}
        </main>
      </div>

      {/* ── Add OIDC Modal ── */}
      {showAddOidcModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="fixed inset-0 bg-black/50 backdrop-blur-xs" onClick={() => setShowAddOidcModal(false)} />
          <div className="relative w-full max-w-lg bg-white dark:bg-zinc-900 rounded-2xl border border-zinc-200 dark:border-zinc-800 p-6 shadow-2xl z-10 space-y-5 animate-in zoom-in-95 duration-150">
            <div>
              <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-100">
                {t('settings.addProvider', 'Add OIDC Provider')}
              </h3>
              <p className="text-xs text-zinc-500 mt-1">
                Enter your identity provider details. Supports Authentik, Keycloak, and standard OIDC.
              </p>
            </div>

            {/* Quick Preset Buttons */}
            <div className="flex items-center gap-2 pb-1 overflow-x-auto">
              {[
                { name: 'authentik', label: 'Authentik SSO', issuer: 'https://auth.example.lan/application/o/famledger' },
                { name: 'keycloak', label: 'Keycloak SSO', issuer: 'https://keycloak.example.lan/realms/famrealm' },
                { name: 'google', label: 'Google Workspace', issuer: 'https://accounts.google.com' },
                { name: 'custom', label: 'Custom OIDC', issuer: 'https://oidc.example.com' },
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
                  + {preset.label}
                </button>
              ))}
            </div>

            <form onSubmit={handleCreateOidcProvider} className="space-y-4 text-xs">
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="font-semibold text-zinc-700 dark:text-zinc-300">Provider Name</label>
                  <input
                    type="text"
                    value={oidcForm.name}
                    onChange={(e) => setOidcForm({ ...oidcForm, name: e.target.value })}
                    placeholder="authentik"
                    required
                    className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none"
                  />
                </div>

                <div className="space-y-1">
                  <label className="font-semibold text-zinc-700 dark:text-zinc-300">Display Label</label>
                  <input
                    type="text"
                    value={oidcForm.label}
                    onChange={(e) => setOidcForm({ ...oidcForm, label: e.target.value })}
                    placeholder="Authentik Login"
                    required
                    className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none"
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label className="font-semibold text-zinc-700 dark:text-zinc-300">Issuer URL (Discovery Endpoint)</label>
                <input
                  type="url"
                  value={oidcForm.issuer}
                  onChange={(e) => setOidcForm({ ...oidcForm, issuer: e.target.value })}
                  placeholder="https://auth.example.com/application/o/famledger"
                  required
                  className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none font-mono"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="font-semibold text-zinc-700 dark:text-zinc-300">Client ID</label>
                  <input
                    type="text"
                    value={oidcForm.client_id}
                    onChange={(e) => setOidcForm({ ...oidcForm, client_id: e.target.value })}
                    placeholder="famledger-client"
                    required
                    className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none font-mono"
                  />
                </div>

                <div className="space-y-1">
                  <label className="font-semibold text-zinc-700 dark:text-zinc-300">Client Secret</label>
                  <input
                    type="password"
                    value={oidcForm.client_secret}
                    onChange={(e) => setOidcForm({ ...oidcForm, client_secret: e.target.value })}
                    placeholder="••••••••••••"
                    required
                    className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none font-mono"
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label className="font-semibold text-zinc-700 dark:text-zinc-300">
                  {t('settings.allowedDomains', 'Allowed Domains (comma-separated, optional)')}
                </label>
                <input
                  type="text"
                  value={oidcForm.allowed_domains}
                  onChange={(e) => setOidcForm({ ...oidcForm, allowed_domains: e.target.value })}
                  placeholder="@family.lan, @gmail.com"
                  className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none"
                />
              </div>

              <div className="flex items-center gap-2 pt-2">
                <input
                  type="checkbox"
                  id="allow_jit"
                  checked={oidcForm.allow_jit}
                  onChange={(e) => setOidcForm({ ...oidcForm, allow_jit: e.target.checked })}
                  className="rounded text-zinc-900 dark:text-white"
                />
                <label htmlFor="allow_jit" className="font-medium text-zinc-700 dark:text-zinc-300 cursor-pointer">
                  {t('settings.allowJit', 'Enable JIT User Creation on first login')}
                </label>
              </div>

              <div className="pt-4 flex items-center justify-end gap-2 border-t border-zinc-100 dark:border-zinc-800">
                <button
                  type="button"
                  onClick={() => setShowAddOidcModal(false)}
                  className="px-3 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 font-medium"
                >
                  {t('common.cancel', 'Cancel')}
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 rounded-lg bg-zinc-900 hover:bg-zinc-800 text-white font-semibold shadow-xs"
                >
                  {t('settings.saveProvider', 'Save Provider')}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
