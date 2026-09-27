import React, { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  LayoutDashboard,
  CreditCard,
  BarChart3,
  CalendarDays,
  Sparkles,
  Inbox,
  SlidersHorizontal,
  HandCoins,
  Plus,
  HelpCircle,
  Settings,
  LogOut,
  Sun,
  Moon,
  Menu,
  X,
  ChevronRight,
  Eye,
  EyeOff,
  PanelLeft,
  Wallet,
  ReceiptText,
  Languages,
  Map,
} from 'lucide-react';
import { useAuth } from '../auth/AuthContext';
import { useTheme } from '../ThemeContext';
import { useCurrency } from '../CurrencyContext';
import { useUsers } from '../ConfigContext';
import { useToast } from '../ToastContext';
import HelpModal from './HelpModal';
import Avatar from './Avatar';
import AccountsPanel from './AccountsPanel';
import config from '../config';

export default function SureLayout({ children }) {
  const location = useLocation();
  const { t, i18n } = useTranslation();
  const { user, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const { currency, setCurrency, currencies, privacyMode, togglePrivacyMode } = useCurrency();
  const { mode } = useUsers();
  const { showToast } = useToast();

  const currentLang = i18n.language || 'zh';

  const toggleLanguage = () => {
    const nextLang = currentLang.startsWith('zh') ? 'en' : 'zh';
    i18n.changeLanguage(nextLang);
    localStorage.setItem('famledger_lang', nextLang);
    showToast(nextLang === 'zh' ? '已切换至简体中文' : 'Switched to English', 'info');
  };

  // 84px Rail navigation items (Sure desktop vertical style)
  const railNavItems = [
    { to: '/', label: t('nav.dashboard', '总览'), icon: LayoutDashboard },
    { to: '/transactions', label: t('nav.transactions', '明细'), icon: CreditCard, badge: '163' },
    { to: '/analytics', label: t('nav.analytics', '报表'), icon: BarChart3 },
    { to: '/budget', label: t('nav.budget', '预算'), icon: Map },
    { to: '/calendar', label: t('nav.calendar', '日历'), icon: CalendarDays },
    { to: '/emails', label: t('nav.emails', '邮件'), icon: Inbox, badge: '164' },
    { to: '/rules', label: t('nav.rules', '规则'), icon: SlidersHorizontal },
    { to: '/debts', label: t('nav.debts', '借贷'), icon: HandCoins },
  ];

  // Desktop left accounts sidebar visibility (Sure defaults to open!)
  const [showAccountsSidebar, setShowAccountsSidebar] = useState(true);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [showHelp, setShowHelp] = useState(false);

  // Breadcrumb resolver
  const isSettingsOrRules = location.pathname.startsWith('/settings') || location.pathname.startsWith('/rules');

  const getBreadcrumbs = () => {
    const p = location.pathname;
    const home = t('nav.home', '主页');
    if (p === '/') return [home, t('nav.dashboard', '仪表盘')];
    if (p.startsWith('/transactions')) return [home, t('nav.transactions', '交易明细')];
    if (p.startsWith('/analytics')) return [home, t('nav.analytics', '统计报表')];
    if (p.startsWith('/budget')) return [home, t('nav.budget', '预算管理')];
    if (p.startsWith('/calendar')) return [home, t('nav.calendar', '消费日历')];
    if (p.startsWith('/emails')) return [home, t('nav.emails', '账单邮件箱')];
    if (p.startsWith('/rules')) return [home, t('nav.rules', '规则引擎')];
    if (p.startsWith('/debts')) return [home, t('nav.debts', '债务借贷')];
    if (p.startsWith('/settings')) return [home, t('nav.settings', '系统设置')];
    return [home, t('nav.overview', '总览')];
  };

  const breadcrumbs = getBreadcrumbs();

  return (
    <div className="min-h-screen bg-[#FAFAFA] dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 flex flex-col lg:flex-row antialiased font-sans w-full max-w-full overflow-x-hidden">
      {/* ────────────────────────────────────────────────────────── */}
      {/* 1. DESKTOP 84px SLIM RAIL NAVBAR (Exact Sure Design)     */}
      {/* ────────────────────────────────────────────────────────── */}
      <nav
        aria-label="主功能导航"
        className="hidden lg:flex fixed inset-y-0 left-0 w-[84px] bg-white dark:bg-zinc-900 border-r border-zinc-200/80 dark:border-zinc-800 flex-col items-center py-4 z-40 select-none justify-between"
      >
        {/* Top: Brand Logo */}
        <div className="w-full flex flex-col items-center gap-4">
          <Link to="/" className="block p-1 hover:opacity-85 transition-opacity" title="famLedger 首页">
            <img
              src="/logo.svg"
              alt="famLedger"
              className="w-9 h-9 object-contain drop-shadow-xs"
              onError={(e) => { e.currentTarget.src = '/logo.png'; }}
            />
          </Link>

          {/* Vertical Icon Nav List */}
          <ul className="w-full space-y-1.5 px-2">
            {railNavItems.map((item) => {
              const Icon = item.icon;
              const isActive = location.pathname === item.to || (item.to !== '/' && location.pathname.startsWith(item.to));

              return (
                <li key={item.to} className="w-full">
                  <Link
                    to={item.to}
                    className={`group relative flex flex-col items-center justify-center py-2.5 px-1 rounded-xl transition-all duration-150 text-center ${
                      isActive
                        ? 'bg-zinc-100 dark:bg-zinc-800 text-zinc-900 dark:text-white font-semibold shadow-xs'
                        : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-white hover:bg-zinc-50 dark:hover:bg-zinc-800/50'
                    }`}
                  >
                    <Icon className={`w-5 h-5 shrink-0 transition-transform group-hover:scale-105 ${isActive ? 'text-zinc-900 dark:text-white' : 'text-zinc-500 group-hover:text-zinc-800 dark:group-hover:text-zinc-200'}`} />
                    <span className="text-[11px] mt-1 tracking-tight leading-none">{item.label}</span>

                    {item.badge && (
                      <span className="absolute top-1.5 right-2 min-w-3.5 h-3.5 px-1 rounded-full bg-zinc-200 dark:bg-zinc-700 text-zinc-600 dark:text-zinc-300 text-[9px] font-mono font-bold flex items-center justify-center">
                        {item.badge}
                      </span>
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>

        {/* Bottom: Utilities & User Avatar */}
        <div className="w-full flex flex-col items-center gap-2.5 px-2">
          {/* Language switcher */}
          <button
            onClick={toggleLanguage}
            title={currentLang.startsWith('zh') ? 'Switch to English' : '切换为简体中文'}
            className="w-9 h-9 rounded-lg text-zinc-600 dark:text-zinc-300 hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-800 flex items-center justify-center transition-colors text-xs font-bold font-mono border border-zinc-200/80 dark:border-zinc-700"
          >
            {currentLang.startsWith('zh') ? 'EN' : '中'}
          </button>

          {/* Theme toggle */}
          <button
            onClick={toggleTheme}
            title="切换明暗主题"
            className="w-9 h-9 rounded-lg text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-800 flex items-center justify-center transition-colors"
          >
            {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
          </button>

          {/* Help guide */}
          <button
            onClick={() => setShowHelp(true)}
            title="系统使用说明"
            className="w-9 h-9 rounded-lg text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-800 flex items-center justify-center transition-colors"
          >
            <HelpCircle className="w-4 h-4" />
          </button>

          {/* User Avatar Circle (Sure Style) */}
          <Link
            to="/settings"
            title="个人偏好设置"
            className="w-9 h-9 rounded-full bg-zinc-200 dark:bg-zinc-700 text-zinc-800 dark:text-zinc-100 text-xs font-bold flex items-center justify-center hover:ring-2 hover:ring-zinc-400 transition-all cursor-pointer"
          >
            {(user?.displayName || user?.username || 'QQ').slice(0, 2).toUpperCase()}
          </Link>
        </div>
      </nav>

      {/* ────────────────────────────────────────────────────────── */}
      {/* 2. DESKTOP ACCOUNTS SIDEBAR (Sure 280px Persistent Sidebar) */}
      {/* ────────────────────────────────────────────────────────── */}
      {!isSettingsOrRules && (
        <aside
          className={`hidden lg:flex fixed inset-y-0 left-[84px] bg-white dark:bg-zinc-900 border-r border-zinc-200/80 dark:border-zinc-800 flex-col z-30 transition-all duration-200 ease-in-out select-none ${
            showAccountsSidebar ? 'w-72 opacity-100' : 'w-0 opacity-0 pointer-events-none overflow-hidden'
          }`}
        >
          <div className="w-72 h-full flex flex-col">
            <AccountsPanel />
          </div>
        </aside>
      )}

      {/* ────────────────────────────────────────────────────────── */}
      {/* 3. MOBILE HEADER (Exact Sure Mobile Topbar)               */}
      {/* ────────────────────────────────────────────────────────── */}
      <header className="lg:hidden fixed top-0 inset-x-0 h-14 bg-white/95 dark:bg-zinc-900/95 backdrop-blur-md border-b border-zinc-200/80 dark:border-zinc-800 z-40 flex items-center justify-between px-3.5">
        {/* Left: [|] Panel Icon to open Accounts Drawer */}
        <button
          onClick={() => setMobileSidebarOpen(true)}
          title="打开银行卡账户列表"
          className="w-9 h-9 rounded-lg text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 flex items-center justify-center transition-colors active:scale-95"
        >
          <PanelLeft className="w-5 h-5" />
        </button>

        {/* Center: Sure-style Clean Centered LogoMark */}
        <Link to="/" className="flex items-center justify-center">
          <img
            src="/logo.svg"
            alt="famLedger"
            className="w-8 h-8 object-contain"
            onError={(e) => { e.currentTarget.src = '/logo.png'; }}
          />
        </Link>

        {/* Right: Language, Privacy Eye & User Avatar */}
        <div className="flex items-center gap-1.5">
          <button
            onClick={toggleLanguage}
            title={currentLang.startsWith('zh') ? 'Switch to English' : '切换为简体中文'}
            className="w-8 h-8 rounded-lg text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800 flex items-center justify-center text-xs font-bold font-mono border border-zinc-200/80 dark:border-zinc-700"
          >
            {currentLang.startsWith('zh') ? 'EN' : '中'}
          </button>

          <button
            onClick={togglePrivacyMode}
            title={privacyMode ? '显示金额' : '隐藏敏感金额'}
            className="w-8 h-8 rounded-lg text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800 flex items-center justify-center transition-colors"
          >
            {privacyMode ? <EyeOff className="w-4 h-4 text-emerald-600 dark:text-emerald-400" /> : <Eye className="w-4 h-4" />}
          </button>

          <Link
            to="/settings"
            className="w-8 h-8 rounded-full bg-zinc-200 dark:bg-zinc-700 text-zinc-800 dark:text-zinc-100 text-xs font-bold flex items-center justify-center"
          >
            {(user?.displayName || user?.username || 'QQ').slice(0, 2).toUpperCase()}
          </Link>
        </div>
      </header>

      {/* ────────────────────────────────────────────────────────── */}
      {/* 4. MOBILE FULLSCREEN ACCOUNTS SLIDE-OVER (Sure Mobile)     */}
      {/* ────────────────────────────────────────────────────────── */}
      {mobileSidebarOpen && (
        <div className="lg:hidden fixed inset-0 z-50 flex">
          <div
            className="fixed inset-0 bg-black/40 backdrop-blur-xs transition-opacity"
            onClick={() => setMobileSidebarOpen(false)}
          />
          <div className="relative w-80 max-w-[85vw] bg-white dark:bg-zinc-900 h-full shadow-2xl flex flex-col z-10 animate-in slide-in-from-left duration-200">
            <div className="p-3 pb-1 flex items-center justify-between border-b border-zinc-100 dark:border-zinc-800">
              <span className="text-xs font-semibold text-zinc-500 uppercase tracking-wider px-2">Accounts Navigation</span>
              <button
                onClick={() => setMobileSidebarOpen(false)}
                className="p-1.5 rounded-lg text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
                title="关闭侧栏"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto">
              <AccountsPanel isMobileDrawer onClose={() => setMobileSidebarOpen(false)} />
            </div>
          </div>
        </div>
      )}

      {/* ────────────────────────────────────────────────────────── */}
      {/* 5. SHARED MAIN CONTENT AREA                                */}
      {/* ────────────────────────────────────────────────────────── */}
      <main
        id="main"
        className={`grow min-h-screen flex flex-col transition-all duration-200 pt-14 lg:pt-0 pb-20 lg:pb-8 w-full max-w-full overflow-x-hidden ${
          showAccountsSidebar && !isSettingsOrRules ? 'lg:pl-[368px]' : 'lg:pl-[84px]'
        }`}
      >
        {/* Desktop Sticky Header with Breadcrumbs & Toggles (Exact Sure Topbar, hidden on dashboard like 1.png) */}
        {location.pathname !== '/' && (
          <div className="hidden lg:flex items-center justify-between px-8 py-3.5 bg-white/80 dark:bg-zinc-900/80 backdrop-blur-md border-b border-zinc-200/80 dark:border-zinc-800 sticky top-0 z-20">
          {/* Left: Sidebar Toggle + Breadcrumb */}
          <div className="flex items-center gap-3">
            {!isSettingsOrRules && (
              <button
                onClick={() => setShowAccountsSidebar(!showAccountsSidebar)}
                title={showAccountsSidebar ? '收起账户侧栏' : '展开账户侧栏'}
                className="p-1.5 rounded-lg text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
              >
                <PanelLeft className="w-4 h-4" />
              </button>
            )}

            <nav aria-label="面包屑导航" className="flex items-center gap-1.5 text-xs font-medium text-zinc-500">
              {breadcrumbs.map((b, idx) => (
                <React.Fragment key={idx}>
                  {idx > 0 && <span className="text-zinc-400">/</span>}
                  <span className={idx === breadcrumbs.length - 1 ? 'text-zinc-900 dark:text-zinc-100 font-semibold' : ''}>
                    {b}
                  </span>
                </React.Fragment>
              ))}
            </nav>
          </div>

          {/* Right: Currency Selector & Privacy Toggle */}
          <div className="flex items-center gap-2">
            <select
              aria-label="选择显示币种"
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
              className="bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 text-xs font-semibold text-zinc-800 dark:text-zinc-200 rounded-lg px-2.5 py-1.5 border border-zinc-200 dark:border-zinc-700 outline-none cursor-pointer transition-colors"
            >
              {currencies.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.symbol} {c.code}
                </option>
              ))}
            </select>

            <button
              onClick={togglePrivacyMode}
              title={privacyMode ? '显示金额' : '隐藏敏感金额 (隐私模式)'}
              className={`p-1.5 rounded-lg border transition-colors ${
                privacyMode
                  ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-600 dark:text-emerald-400'
                  : 'border-zinc-200 dark:border-zinc-800 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-800'
              }`}
            >
              {privacyMode ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>
        </div>
        )}

        {/* Content Body Container */}
        <div className="grow max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6">
          {children}
        </div>
      </main>

      {/* ────────────────────────────────────────────────────────── */}
      {/* 6. MOBILE BOTTOM NAVIGATION (Sure 4-Tab Bar: Home, New, Transactions, Reports) */}
      {/* ────────────────────────────────────────────────────────── */}
      <nav
        aria-label="移动端快速导航"
        className="lg:hidden fixed bottom-0 inset-x-0 bg-white/95 dark:bg-zinc-900/95 backdrop-blur-md border-t border-zinc-200/80 dark:border-zinc-800 z-40 px-3 pt-1.5 pb-[max(env(safe-area-inset-bottom),0.5rem)] flex items-center justify-around shadow-sm select-none"
      >
        {/* Tab 1: Home */}
        <Link
          to="/"
          className={`relative flex flex-col items-center gap-1 py-1 px-3 rounded-lg transition-colors ${
            location.pathname === '/'
              ? 'text-zinc-900 dark:text-white font-semibold'
              : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-300'
          }`}
        >
          {location.pathname === '/' && (
            <span className="absolute -top-1.5 w-6 h-0.5 bg-zinc-900 dark:bg-white rounded-full" />
          )}
          <LayoutDashboard className="w-5 h-5" />
          <span className="text-[10px] leading-tight">{t('nav.dashboard', '总览')}</span>
        </Link>

        {/* Tab 2: New Transaction */}
        <Link
          to="/add"
          className="relative flex flex-col items-center gap-1 py-1 px-3 rounded-lg text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-300 transition-colors"
        >
          <Plus className="w-5 h-5" />
          <span className="text-[10px] leading-tight">{t('nav.quickAdd', '记一笔')}</span>
        </Link>

        {/* Tab 3: Transactions */}
        <Link
          to="/transactions"
          className={`relative flex flex-col items-center gap-1 py-1 px-3 rounded-lg transition-colors ${
            location.pathname.startsWith('/transactions')
              ? 'text-zinc-900 dark:text-white font-semibold'
              : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-300'
          }`}
        >
          {location.pathname.startsWith('/transactions') && (
            <span className="absolute -top-1.5 w-6 h-0.5 bg-zinc-900 dark:bg-white rounded-full" />
          )}
          <CreditCard className="w-5 h-5" />
          <span className="text-[10px] leading-tight">{t('nav.transactions', '明细')}</span>
        </Link>

        {/* Tab 4: Reports */}
        <Link
          to="/analytics"
          className={`relative flex flex-col items-center gap-1 py-1 px-3 rounded-lg transition-colors ${
            location.pathname.startsWith('/analytics')
              ? 'text-zinc-900 dark:text-white font-semibold'
              : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-300'
          }`}
        >
          {location.pathname.startsWith('/analytics') && (
            <span className="absolute -top-1.5 w-6 h-0.5 bg-zinc-900 dark:bg-white rounded-full" />
          )}
          <BarChart3 className="w-5 h-5" />
          <span className="text-[10px] leading-tight">{t('nav.analytics', '报表')}</span>
        </Link>
      </nav>

      {/* Help Modal */}
      {showHelp && <HelpModal onClose={() => setShowHelp(false)} />}
    </div>
  );
}
