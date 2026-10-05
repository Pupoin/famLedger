import { tx, useLocale } from "../localization.js";
import React, { useState, useEffect, useRef } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { LayoutDashboard, CreditCard, BarChart3, SlidersHorizontal, Plus, HelpCircle, Settings, LogOut, Sun, Moon, Monitor, X, Eye, EyeOff, PanelLeft, Languages, Map, Users } from 'lucide-react';
import { useAuth } from '../auth/AuthContext';
import { useTheme } from '../ThemeContext';
import { useCurrency } from '../CurrencyContext';
import { useUsers } from '../ConfigContext';
import { useToast } from '../ToastContext';
import HelpModal from './HelpModal';

import AccountsPanel from './AccountsPanel';
import AddTransactionModal from './AddTransactionModal';
import InitialCurrencySelectModal from './InitialCurrencySelectModal';
import InitialLanguageSelectModal from './InitialLanguageSelectModal';


export default function SureLayout({ children }) {
  useLocale();
  const location = useLocation();
  const { t, i18n } = useTranslation();
  const { user, logout } = useAuth();
  const { theme, themeMode, toggleTheme } = useTheme();
  const themeLabel = {light:'日间', dark:'夜间', auto:'自动'}[themeMode];
  const {
    currency,
    setCurrency,
    currencies,
    privacyMode,
    togglePrivacyMode,
    hasChosenCurrency,
    chooseInitialCurrency,
    hasChosenLanguage,
    setLanguage,
  } = useCurrency();
  const { mode } = useUsers();
  const { showToast } = useToast();

  const currentLang = i18n.language || 'en';

  const toggleLanguage = async () => {
    const nextLang = currentLang.startsWith('zh') ? 'en' : 'zh';
    try {
      await setLanguage(nextLang);
      showToast(tx(nextLang === 'zh' ? '已切换至简体中文' : 'Switched to English'), 'info');
    } catch { showToast(tx("Could not save your language. Please try again."), 'error'); }
  };

  const railNavItems = [
    { to: '/', label: t('nav.dashboard', tx("总览")), icon: LayoutDashboard },
    { to: '/transactions', label: t('nav.transactions', tx("明细")), icon: CreditCard },
    { to: '/analytics', label: t('nav.analytics', tx("报表")), icon: BarChart3 },
    { to: '/budget', label: t('nav.budget', tx("预算")), icon: Map },
  ];

  // Desktop left accounts sidebar visibility & customizable width
  const DEFAULT_SIDEBAR_WIDTH = 320;
  const MIN_SIDEBAR_WIDTH = 240;
  const MAX_SIDEBAR_WIDTH = 560;

  const [sidebarWidth, setSidebarWidth] = useState(() => {
    try {
      const saved = localStorage.getItem('famledger_sidebar_width');
      if (saved) {
        const parsed = parseInt(saved, 10);
        if (!isNaN(parsed) && parsed >= MIN_SIDEBAR_WIDTH && parsed <= MAX_SIDEBAR_WIDTH) {
          return parsed;
        }
      }
    } catch {}
    return DEFAULT_SIDEBAR_WIDTH;
  });

  const [isResizing, setIsResizing] = useState(false);
  const isResizingRef = useRef(false);

  const startResizing = (e) => {
    if (e.button !== 0) return; // Only primary mouse button
    e.preventDefault();
    setIsResizing(true);
    isResizingRef.current = true;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    const startX = e.clientX;
    const startWidth = sidebarWidth;

    const handlePointerMove = (moveEvent) => {
      if (!isResizingRef.current) return;
      const deltaX = moveEvent.clientX - startX;
      const maxAllowed = Math.min(MAX_SIDEBAR_WIDTH, Math.max(MIN_SIDEBAR_WIDTH, window.innerWidth - 420));
      const nextWidth = Math.max(MIN_SIDEBAR_WIDTH, Math.min(maxAllowed, startWidth + deltaX));
      setSidebarWidth(nextWidth);
    };

    const handlePointerUp = () => {
      setIsResizing(false);
      isResizingRef.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerup', handlePointerUp);
      window.removeEventListener('pointercancel', handlePointerUp);
    };

    window.addEventListener('pointermove', handlePointerMove);
    window.addEventListener('pointerup', handlePointerUp);
    window.addEventListener('pointercancel', handlePointerUp);
  };

  useEffect(() => {
    try {
      localStorage.setItem('famledger_sidebar_width', String(sidebarWidth));
    } catch {}
  }, [sidebarWidth]);

  const resetSidebarWidth = (e) => {
    e.preventDefault();
    setSidebarWidth(DEFAULT_SIDEBAR_WIDTH);
    try {
      localStorage.setItem('famledger_sidebar_width', String(DEFAULT_SIDEBAR_WIDTH));
    } catch {}
  };

  const [showAccountsSidebar, setShowAccountsSidebar] = useState(true);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [mobileUserMenuOpen, setMobileUserMenuOpen] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [showAddModal, setShowAddModal] = useState(false);
  const [desktopUserMenuOpen, setDesktopUserMenuOpen] = useState(false);
  const userMenuRef = useRef(null);

  useEffect(() => {
    function handleClickOutside(event) {
      if (userMenuRef.current && !userMenuRef.current.contains(event.target)) {
        setDesktopUserMenuOpen(false);
      }
    }
    if (desktopUserMenuOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }
  }, [desktopUserMenuOpen]);

  // 移动端侧栏与用户菜单打开时锁定底层 body 滚动，彻底防止向主界面穿透滚动
  useEffect(() => {
    if (mobileSidebarOpen || mobileUserMenuOpen) {
      const originalOverflow = document.body.style.overflow;
      const originalTouchAction = document.body.style.touchAction;
      document.body.style.overflow = 'hidden';
      document.body.style.touchAction = 'none';
      return () => {
        document.body.style.overflow = originalOverflow;
        document.body.style.touchAction = originalTouchAction;
      };
    }
  }, [mobileSidebarOpen, mobileUserMenuOpen]);

  // Breadcrumb resolver
  const isSettingsOrRules = location.pathname.startsWith('/settings') || location.pathname.startsWith('/rules');

  const getBreadcrumbs = () => {
    const p = location.pathname;
    const home = t('nav.home', tx("主页"));
    if (p === '/') return [home, t('nav.dashboard', tx("仪表盘"))];
    if (p.startsWith('/transactions')) return [home, t('nav.transactions', tx("交易明细"))];
    if (p.startsWith('/analytics')) return [home, t('nav.analytics', tx("统计报表"))];
    if (p.startsWith('/budget')) return [home, t('nav.budget', tx("预算管理"))];
    if (p.startsWith('/calendar')) return [home, t('nav.calendar', tx("消费日历"))];
    if (p.startsWith('/rules')) return [home, t('nav.rules', tx("规则引擎"))];
    if (p.startsWith('/debts')) return [home, t('nav.debts', tx("债务借贷"))];
    if (p.startsWith('/settings')) return [home, t('nav.settings', tx("系统设置"))];
    return [home, t('nav.overview', tx("总览"))];
  };

  const breadcrumbs = getBreadcrumbs();

  return (
    <div className="min-h-screen bg-[#FAFAFA] dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 flex flex-col lg:flex-row antialiased font-sans w-full max-w-full overflow-x-hidden">
      {/* ────────────────────────────────────────────────────────── */}
      {/* 1. DESKTOP 84px SLIM RAIL NAVBAR (Exact Sure Design)     */}
      {/* ────────────────────────────────────────────────────────── */}
      <nav
        aria-label={tx("主功能导航")}
        className="hidden lg:flex fixed inset-y-0 left-0 w-[84px] bg-white dark:bg-zinc-900 border-r border-zinc-200/80 dark:border-zinc-800 flex-col items-center py-4 z-40 select-none justify-between"
      >
        {/* Top: Brand Logo */}
        <div className="w-full flex flex-col items-center gap-4">
          <Link to="/" className="block p-1 hover:opacity-85 transition-opacity" title={tx("famLedger 首页")}>
            <img
              src="/logo.svg?v=blue-purple"
              alt="famLedger"
              className="w-9 h-9 object-contain drop-shadow-xs"
              onError={(e) => { e.currentTarget.src = '/logo.png?v=blue-purple'; }}
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
                    <span className="text-xs mt-1 tracking-tight leading-none">{tx(item.label)}</span>

                    {item.badge && (
                      <span className="absolute top-1.5 right-2 min-w-3.5 h-3.5 px-1 rounded-full bg-zinc-200 dark:bg-zinc-700 text-zinc-600 dark:text-zinc-300 text-2xs font-mono font-bold flex items-center justify-center">
                        {item.badge}
                      </span>
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>

          {/* + 新建交易 按钮（Rail Nav 底部快捷，与周边导航风格统一） */}
          <button
            type="button"
            data-testid="sidebar-new-btn"
            onClick={() => setShowAddModal(true)}
            title={tx("新建交易")}
            className="w-[calc(100%-16px)] mx-2 flex flex-col items-center justify-center py-2 px-1 rounded-xl text-zinc-500 hover:text-zinc-900 dark:hover:text-white hover:bg-zinc-100 dark:hover:bg-zinc-800 border border-dashed border-zinc-300/80 dark:border-zinc-700 transition-all duration-150 active:scale-95 group cursor-pointer"
          >
            <Plus className="w-5 h-5 shrink-0 text-zinc-500 group-hover:text-zinc-900 dark:group-hover:text-white transition-transform group-hover:scale-110" />
            <span className="text-xs mt-1 tracking-tight leading-none font-medium">{tx("新建")}</span>
          </button>
        </div>

        {/* Bottom: Utilities & User Avatar */}
        <div className="w-full flex flex-col items-center gap-2.5 px-2">
          {/* Theme toggle */}
          <button
            onClick={toggleTheme}
            title={tx("主题：{p0}（点击切换日间 / 夜间 / 自动）", {p0: (themeLabel)})}
            aria-label={tx("主题：{p0}（点击切换日间 / 夜间 / 自动）", {p0: (themeLabel)})}
            data-testid="theme-mode-cycle"
            className="w-9 h-9 rounded-lg text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-800 flex items-center justify-center transition-colors"
          >
            {themeMode === 'auto' ? <Monitor className="w-4 h-4" /> : theme === 'dark' ? <Moon className="w-4 h-4" /> : <Sun className="w-4 h-4" />}
          </button>

          {/* Help guide */}
          <button
            onClick={() => setShowHelp(true)}
            title={tx("系统使用说明")}
            className="w-9 h-9 rounded-lg text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-800 flex items-center justify-center transition-colors"
          >
            <HelpCircle className="w-4 h-4" />
          </button>

          {/* User Avatar & Desktop Popover Menu */}
          <div className="relative" ref={userMenuRef}>
            <button
              type="button"
              data-testid="desktop-user-menu-trigger"
              onClick={() => setDesktopUserMenuOpen(!desktopUserMenuOpen)}
              title={tx("用户账户与偏好菜单")}
              className={`w-9 h-9 rounded-full bg-zinc-200 dark:bg-zinc-700 text-zinc-800 dark:text-zinc-100 text-xs font-bold flex items-center justify-center transition-all cursor-pointer ${
                desktopUserMenuOpen
                  ? 'ring-2 ring-zinc-900 dark:ring-white scale-105'
                  : 'hover:ring-2 hover:ring-zinc-400'
              }`}
            >
              {(user?.displayName || user?.username || tx("QQ")).slice(0, 2).toUpperCase()}
            </button>

            {/* Desktop User Popover Menu */}
            {desktopUserMenuOpen && (
              <div
                data-testid="desktop-user-menu-dropdown"
                className="fixed left-20 bottom-3 z-50 w-64 bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl border border-zinc-200 dark:border-zinc-800 p-2 animate-in fade-in zoom-in-95 duration-150 select-none text-left"
              >
                {/* User Header */}
                <div className="flex items-center gap-3 p-2.5 pb-3 border-b border-zinc-100 dark:border-zinc-800">
                  <div className="w-10 h-10 rounded-full bg-zinc-200 dark:bg-zinc-700 text-zinc-800 dark:text-zinc-100 text-sm font-bold flex items-center justify-center shrink-0">
                    {(user?.displayName || user?.username || tx("QQ")).slice(0, 2).toUpperCase()}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span className="font-semibold text-sm text-zinc-900 dark:text-zinc-100 truncate">
                        {user?.displayName || user?.username || tx("用户")}
                      </span>
                      {user?.role === 'admin' && (
                        <span className="px-1.5 py-0.2 rounded-md bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300 text-2xs font-semibold shrink-0">{tx("管理员")}</span>
                      )}
                    </div>
                    <span className="text-xs text-zinc-400 dark:text-zinc-500 truncate block">
                      @{user?.username || tx("user")}
                    </span>
                  </div>
                </div>

                {/* Quick Navigation Items */}
                <div className="py-1 space-y-0.5">
                  <Link
                    to="/settings"
                    onClick={() => setDesktopUserMenuOpen(false)}
                    className="flex items-center gap-2.5 px-3 py-2 text-xs font-medium text-zinc-700 dark:text-zinc-300 hover:text-zinc-900 dark:hover:text-white rounded-xl hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
                  >
                    <Settings className="w-4 h-4 text-zinc-400" />
                    <span>{tx("系统与偏好设置")}</span>
                  </Link>

                  <Link
                    to="/settings?tab=family"
                    onClick={() => setDesktopUserMenuOpen(false)}
                    className="flex items-center gap-2.5 px-3 py-2 text-xs font-medium text-zinc-700 dark:text-zinc-300 hover:text-zinc-900 dark:hover:text-white rounded-xl hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
                  >
                    <Users className="w-4 h-4 text-zinc-400" />
                    <span>{tx("家庭组与成员管理")}</span>
                  </Link>

                  <Link
                    to="/rules"
                    onClick={() => setDesktopUserMenuOpen(false)}
                    className="flex items-center gap-2.5 px-3 py-2 text-xs font-medium text-zinc-700 dark:text-zinc-300 hover:text-zinc-900 dark:hover:text-white rounded-xl hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
                  >
                    <SlidersHorizontal className="w-4 h-4 text-zinc-400" />
                    <span>{tx("规则与自动化流水线")}</span>
                  </Link>
                </div>

                {/* Divider & Actions */}
                <div className="pt-1 mt-1 border-t border-zinc-100 dark:border-zinc-800 space-y-0.5">
                  <button
                    type="button"
                    onClick={() => {
                      toggleLanguage();
                      setDesktopUserMenuOpen(false);
                    }}
                    className="w-full flex items-center justify-between px-3 py-2 text-xs font-medium text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-white rounded-xl hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors cursor-pointer"
                  >
                    <div className="flex items-center gap-2.5">
                      <Languages className="w-4 h-4 text-zinc-400" />
                      <span>{tx("界面语言")}</span>
                    </div>
                    <span className="font-mono text-[11px] font-bold text-zinc-500">
                      {currentLang.startsWith('zh') ? tx("中文") : 'EN'}
                    </span>
                  </button>

                  <button
                    type="button"
                    onClick={() => {
                      toggleTheme();
                      setDesktopUserMenuOpen(false);
                    }}
                    className="w-full flex items-center justify-between px-3 py-2 text-xs font-medium text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-white rounded-xl hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors cursor-pointer"
                  >
                    <div className="flex items-center gap-2.5">
                      {themeMode === 'auto' ? <Monitor className="w-4 h-4 text-zinc-400" /> : theme === 'dark' ? <Moon className="w-4 h-4 text-zinc-400" /> : <Sun className="w-4 h-4 text-zinc-400" />}
                      <span>{tx("明暗主题")}</span>
                    </div>
                    <span className="text-[11px] text-zinc-500">
                      {tx(themeLabel)}
                    </span>
                  </button>

                  {/* LOGOUT BUTTON */}
                  <button
                    type="button"
                    data-testid="desktop-logout-btn"
                    onClick={() => {
                      setDesktopUserMenuOpen(false);
                      logout();
                      showToast(tx("已安全退出登录"), 'info');
                    }}
                    className="w-full flex items-center gap-2.5 px-3 py-2.5 text-xs font-semibold text-red-600 dark:text-red-400 hover:text-red-700 dark:hover:text-red-300 rounded-xl hover:bg-red-50 dark:hover:bg-red-950/40 transition-colors mt-1 cursor-pointer"
                  >
                    <LogOut className="w-4 h-4" />
                    <span>{tx("退出登录")}</span>
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </nav>

      {/* ────────────────────────────────────────────────────────── */}
      {/* 2. DESKTOP ACCOUNTS SIDEBAR (Resizable Persistent Sidebar) */}
      {/* ────────────────────────────────────────────────────────── */}
      {!isSettingsOrRules && (
        <aside
          style={{ width: showAccountsSidebar ? `${sidebarWidth}px` : 0 }}
          className={`hidden lg:flex fixed inset-y-0 left-[84px] bg-white dark:bg-zinc-900 border-r border-zinc-200/80 dark:border-zinc-800 flex-col z-30 select-none ${
            isResizing ? '' : 'transition-all duration-200 ease-in-out'
          } ${
            showAccountsSidebar ? 'opacity-100' : 'opacity-0 pointer-events-none overflow-hidden'
          }`}
        >
          <div className="w-full h-full flex flex-col min-w-0 overflow-hidden">
            <AccountsPanel />
          </div>

          {/* Draggable resize handle */}
          {showAccountsSidebar && (
            <div
              data-testid="sidebar-resize-handle"
              title={tx("拖拽调整侧栏宽度，双击恢复默认")}
              onPointerDown={startResizing}
              onDoubleClick={resetSidebarWidth}
              className="absolute top-0 -right-1.5 w-3 h-full cursor-col-resize z-40 group select-none flex items-center justify-center touch-none"
            >
              <div
                className={`w-0.5 h-full transition-colors duration-150 ${
                  isResizing
                    ? 'bg-zinc-900 dark:bg-zinc-100'
                    : 'bg-transparent group-hover:bg-zinc-400/80 dark:group-hover:bg-zinc-500/80'
                }`}
              />
            </div>
          )}
        </aside>
      )}

      {/* ────────────────────────────────────────────────────────── */}
      {/* 3. MOBILE HEADER (Exact Sure Mobile Topbar)               */}
      {/* ────────────────────────────────────────────────────────── */}
      <header className="lg:hidden fixed top-0 inset-x-0 h-12 bg-white/95 dark:bg-zinc-900/95 backdrop-blur-md border-b border-zinc-200/80 dark:border-zinc-800 z-40 flex items-center justify-between px-3">
        {/* Left: [|] Panel Icon to open Accounts Drawer */}
        <button
          data-testid="open-mobile-accounts-btn"
          onClick={() => setMobileSidebarOpen(true)}
          title={tx("打开银行卡账户列表")}
          className="w-8 h-8 rounded-lg text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 flex items-center justify-center transition-colors active:scale-95"
        >
          <PanelLeft className="w-4.5 h-4.5" />
        </button>

        {/* Center: Sure-style Clean Centered LogoMark */}
        <Link to="/" className="flex items-center justify-center">
          <img
            src="/logo.svg?v=blue-purple"
            alt="famLedger"
            className="w-[26px] h-[26px] object-contain"
            onError={(e) => { e.currentTarget.src = '/logo.png?v=blue-purple'; }}
          />
        </Link>

        {/* Right: Privacy Eye & User Avatar (Exact 10.jpg mobile header) */}
        <div className="flex items-center gap-1.5">
          <button
            data-testid="privacy-toggle"
            onClick={togglePrivacyMode}
            title={privacyMode ? tx("显示金额") : tx("隐藏敏感金额")}
            className="w-8 h-8 rounded-lg text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 flex items-center justify-center transition-colors"
          >
            {privacyMode ? <EyeOff className="w-4.5 h-4.5 text-emerald-600 dark:text-emerald-400" /> : <Eye className="w-4.5 h-4.5" />}
          </button>

          <button
            type="button"
            data-testid="mobile-user-avatar-btn"
            onClick={() => setMobileUserMenuOpen(true)}
            className="w-7 h-7 rounded-full bg-zinc-200 dark:bg-zinc-700 text-zinc-800 dark:text-zinc-100 text-[11px] font-bold flex items-center justify-center ring-1 ring-zinc-300 dark:ring-zinc-600 active:scale-95 transition-transform cursor-pointer"
            title={tx("用户中心与系统设置")}
          >
            {(user?.displayName || user?.username || tx("QQ")).slice(0, 2).toUpperCase()}
          </button>
        </div>
      </header>

      {/* ────────────────────────────────────────────────────────── */}
      {/* 4. MOBILE FULLSCREEN ACCOUNTS SLIDE-OVER (Sure Mobile)     */}
      {/* ────────────────────────────────────────────────────────── */}
      {mobileSidebarOpen && (
        <div className="lg:hidden fixed inset-0 z-50 flex overscroll-contain">
          <div
            className="fixed inset-0 bg-black/40 backdrop-blur-xs transition-opacity touch-none overscroll-none"
            onClick={() => setMobileSidebarOpen(false)}
            onTouchMove={(e) => e.preventDefault()}
          />
          <div className="relative w-80 max-w-[85vw] bg-white dark:bg-zinc-900 h-full shadow-2xl flex flex-col z-10 animate-in slide-in-from-left duration-200 overscroll-contain">
            <div className="flex-1 h-full min-h-0 overflow-hidden">
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
        style={{
          '--sidebar-offset': showAccountsSidebar && !isSettingsOrRules ? `${84 + sidebarWidth}px` : '84px',
        }}
        className={`grow min-h-screen flex flex-col pt-12 lg:pt-0 pb-16 lg:pb-8 w-full max-w-full overflow-x-hidden lg:[padding-left:var(--sidebar-offset)] ${
          isResizing ? '' : 'transition-all duration-200'
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
                title={showAccountsSidebar ? tx("收起账户侧栏") : tx("展开账户侧栏")}
                className="p-1.5 rounded-lg text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
              >
                <PanelLeft className="w-4 h-4" />
              </button>
            )}

            <nav aria-label={tx("面包屑导航")} className="flex items-center gap-1.5 text-xs font-medium text-zinc-500">
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

          {/* Right: Privacy Toggle + Quick Logout */}
          <div className="flex items-center gap-2">
            <button
              data-testid="privacy-toggle"
              onClick={togglePrivacyMode}
              title={privacyMode ? tx("显示金额") : tx("隐藏敏感金额 (隐私模式)")}
              className={`p-1.5 rounded-lg border transition-colors cursor-pointer ${
                privacyMode
                  ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-600 dark:text-emerald-400'
                  : 'border-zinc-200 dark:border-zinc-800 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-800'
              }`}
            >
              {privacyMode ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>

            <button
              type="button"
              data-testid="header-quick-logout-btn"
              onClick={() => {
                logout();
                showToast(tx("已安全退出登录"), 'info');
              }}
              title={tx("退出登录")}
              className="p-1.5 rounded-lg border border-zinc-200 dark:border-zinc-800 text-zinc-500 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors cursor-pointer"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
        )}

        {/* Content Body Container */}
        <div className="grow max-w-7xl w-full mx-auto px-3 sm:px-6 lg:px-8 pt-2.5 sm:pt-6 pb-6">
          {children}
        </div>
      </main>

      {/* ────────────────────────────────────────────────────────── */}
      {/* 6. MOBILE BOTTOM NAVIGATION (Sure Mobile Bottom Bar)      */}
      {/* ────────────────────────────────────────────────────────── */}
      <nav
        aria-label={tx("移动端底部导航")}
        className="lg:hidden fixed bottom-0 inset-x-0 h-[52px] bg-white/95 dark:bg-zinc-900/95 backdrop-blur-md border-t border-zinc-200/80 dark:border-zinc-800 z-40 flex items-center justify-around px-2 select-none"
      >
        <Link
          to="/"
          className={`min-h-[40px] min-w-[40px] py-1 px-2 flex flex-col items-center justify-center rounded-xl transition-colors ${
            location.pathname === '/'
              ? 'text-zinc-900 dark:text-white font-semibold'
              : 'text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200'
          }`}
        >
          <LayoutDashboard className="w-[18px] h-[18px] shrink-0" />
          <span className="text-[10px] mt-0.5 tracking-tight leading-none font-medium">{t('nav.tab_dashboard', tx("总览"))}</span>
        </Link>

        <Link
          to="/transactions"
          className={`min-h-[40px] min-w-[40px] py-1 px-2 flex flex-col items-center justify-center rounded-xl transition-colors ${
            location.pathname.startsWith('/transactions')
              ? 'text-zinc-900 dark:text-white font-semibold'
              : 'text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200'
          }`}
        >
          <CreditCard className="w-[18px] h-[18px] shrink-0" />
          <span className="text-[10px] mt-0.5 tracking-tight leading-none font-medium">{t('nav.tab_transactions', tx("明细"))}</span>
        </Link>

        {/* 中间突出的 + 新建按钮 (Sure 风格，紧凑精致) */}
        <button
          type="button"
          onClick={() => setShowAddModal(true)}
          className="relative -mt-4 w-[42px] h-[42px] rounded-full bg-zinc-900 dark:bg-white text-white dark:text-zinc-900 flex items-center justify-center shadow-md hover:bg-zinc-800 dark:hover:bg-zinc-100 active:scale-95 transition-all"
          title={tx("新建交易")}
        >
          <Plus className="w-5 h-5" />
        </button>

        <Link
          to="/analytics"
          className={`min-h-[40px] min-w-[40px] py-1 px-2 flex flex-col items-center justify-center rounded-xl transition-colors ${
            location.pathname.startsWith('/analytics')
              ? 'text-zinc-900 dark:text-white font-semibold'
              : 'text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200'
          }`}
        >
          <BarChart3 className="w-[18px] h-[18px] shrink-0" />
          <span className="text-[10px] mt-0.5 tracking-tight leading-none font-medium">{t('nav.tab_analytics', tx("报表"))}</span>
        </Link>

        <Link
          to="/budget"
          className={`min-h-[40px] min-w-[40px] py-1 px-2 flex flex-col items-center justify-center rounded-xl transition-colors ${
            location.pathname.startsWith('/budget')
              ? 'text-zinc-900 dark:text-white font-semibold'
              : 'text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200'
          }`}
        >
          <Map className="w-[18px] h-[18px] shrink-0" />
          <span className="text-[10px] mt-0.5 tracking-tight leading-none font-medium">{t('nav.tab_budget', tx("预算"))}</span>
        </Link>
      </nav>

      {/* ────────────────────────────────────────────────────────── */}
      {/* 7. MOBILE USER PROFILE & SETTINGS DRAWER (点击右上角头像弹出) */}
      {/* ────────────────────────────────────────────────────────── */}
      {mobileUserMenuOpen && (
        <div className="lg:hidden fixed inset-0 z-50 flex flex-col justify-end overscroll-contain">
          <div
            className="fixed inset-0 bg-black/40 backdrop-blur-xs transition-opacity touch-none"
            onClick={() => setMobileUserMenuOpen(false)}
            onTouchMove={(e) => e.preventDefault()}
          />
          <div className="relative w-full bg-white dark:bg-zinc-900 rounded-t-3xl shadow-2xl p-5 z-10 space-y-4 max-h-[85vh] overflow-y-auto animate-in slide-in-from-bottom duration-200 border-t border-zinc-200/80 dark:border-zinc-800 overscroll-contain custom-scrollbar">
            {/* Top Handle Bar */}
            <div className="w-10 h-1 bg-zinc-300 dark:bg-zinc-700 rounded-full mx-auto -mt-1 mb-1" />

            {/* User Profile Header */}
            <div className="flex items-center justify-between pb-3.5 border-b border-zinc-100 dark:border-zinc-800">
              <div className="flex items-center gap-3">
                <div className="w-11 h-11 rounded-full bg-zinc-200 dark:bg-zinc-700 text-zinc-800 dark:text-zinc-100 text-sm font-bold flex items-center justify-center shrink-0 ring-2 ring-zinc-300/80 dark:ring-zinc-600">
                  {(user?.displayName || user?.username || tx("QQ")).slice(0, 2).toUpperCase()}
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="font-bold text-base text-zinc-900 dark:text-zinc-100 truncate">
                      {user?.displayName || user?.username || tx("用户")}
                    </span>
                    {user?.role === 'admin' && (
                      <span className="px-1.5 py-0.2 rounded-md bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300 text-2xs font-semibold shrink-0">{tx("管理员")}</span>
                    )}
                  </div>
                  <span className="text-xs text-zinc-400 dark:text-zinc-500 font-mono truncate block">
                    @{user?.username || tx("user")}
                  </span>
                </div>
              </div>

              <button
                type="button"
                onClick={() => setMobileUserMenuOpen(false)}
                className="p-1.5 rounded-lg text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
                title={tx("关闭")}
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Quick Links Group (核心功能快捷入口) */}
            <div className="space-y-1.5">
              <div className="text-[11px] font-semibold text-zinc-400 uppercase tracking-wider px-1 mb-1">{tx("功能与自动化")}</div>
              <div className="grid grid-cols-2 gap-2">
                <Link
                  to="/settings"
                  onClick={() => setMobileUserMenuOpen(false)}
                  className="flex items-center gap-2.5 p-3 rounded-xl bg-zinc-50 dark:bg-zinc-800/60 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-800 dark:text-zinc-200 text-xs font-medium transition-colors"
                >
                  <Settings className="w-4 h-4 text-zinc-600 dark:text-zinc-400 shrink-0" />
                  <span>{t('common.settings', tx("系统设置"))}</span>
                </Link>

                <Link
                  to="/rules"
                  onClick={() => setMobileUserMenuOpen(false)}
                  className="flex items-center gap-2.5 p-3 rounded-xl bg-zinc-50 dark:bg-zinc-800/60 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-800 dark:text-zinc-200 text-xs font-medium transition-colors"
                >
                  <SlidersHorizontal className="w-4 h-4 text-zinc-600 dark:text-zinc-400 shrink-0" />
                  <span>{tx("规则引擎")}</span>
                </Link>

                <button
                  type="button"
                  onClick={() => {
                    setShowHelp(true);
                    setMobileUserMenuOpen(false);
                  }}
                  className="flex items-center gap-2.5 p-3 rounded-xl bg-zinc-50 dark:bg-zinc-800/60 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-800 dark:text-zinc-200 text-xs font-medium transition-colors text-left cursor-pointer"
                >
                  <HelpCircle className="w-4 h-4 text-zinc-600 dark:text-zinc-400 shrink-0" />
                  <span>{t('common.helpGuide', tx("使用说明"))}</span>
                </button>
              </div>
            </div>

            {/* Preferences Group (偏好设置) */}
            <div className="space-y-1.5 pt-1 border-t border-zinc-100 dark:border-zinc-800">
              <div className="text-[11px] font-semibold text-zinc-400 uppercase tracking-wider px-1 mb-1">{tx("界面与偏好")}</div>
              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={toggleTheme}
                  className="flex items-center justify-between p-3 rounded-xl bg-zinc-50 dark:bg-zinc-800/60 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-800 dark:text-zinc-200 text-xs font-medium transition-colors cursor-pointer"
                >
                  <div className="flex items-center gap-2">
                    {themeMode === 'auto' ? <Monitor className="w-4 h-4 text-zinc-500" /> : theme === 'dark' ? <Moon className="w-4 h-4 text-zinc-500" /> : <Sun className="w-4 h-4 text-amber-500" />}
                    <span>{tx("明暗主题")}</span>
                  </div>
                  <span className="text-[11px] text-zinc-400 font-normal">
                    {tx(themeLabel)}
                  </span>
                </button>

                <button
                  type="button"
                  onClick={toggleLanguage}
                  className="flex items-center justify-between p-3 rounded-xl bg-zinc-50 dark:bg-zinc-800/60 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-800 dark:text-zinc-200 text-xs font-medium transition-colors cursor-pointer"
                >
                  <div className="flex items-center gap-2">
                    <Languages className="w-4 h-4 text-zinc-600 dark:text-zinc-400" />
                    <span>{tx("语言")}</span>
                  </div>
                  <span className="font-mono text-[11px] font-bold text-zinc-500">
                    {currentLang.startsWith('zh') ? tx("中文") : 'EN'}
                  </span>
                </button>
              </div>
            </div>

            {/* Logout Action */}
            <div className="pt-2 border-t border-zinc-100 dark:border-zinc-800">
              <button
                type="button"
                data-testid="mobile-user-logout-btn"
                onClick={() => {
                  logout();
                  setMobileUserMenuOpen(false);
                  showToast(tx("已安全退出登录"), 'info');
                }}
                className="w-full flex items-center justify-center gap-2 py-3 px-4 rounded-xl text-xs font-semibold text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/40 hover:bg-red-100 dark:hover:bg-red-900/40 transition-colors cursor-pointer"
              >
                <LogOut className="w-4 h-4" />
                <span>{t('common.logout', tx("退出登录"))}</span>
              </button>
            </div>

            {/* 底部安全留白 */}
            <div className="h-6" aria-hidden="true" />
          </div>
        </div>
      )}

      {/* Help Modal */}
      {showHelp && <HelpModal onClose={() => setShowHelp(false)} />}

      {/* 新建交易 Modal (全局 Portal 弹窗) */}
      <AddTransactionModal
        open={showAddModal}
        onClose={() => setShowAddModal(false)}
        onSuccess={() => {
          // 刷新页面数据（通过 window event 通知各页面）
          window.dispatchEvent(new CustomEvent('transaction-added'));
        }}
      />

      <InitialLanguageSelectModal isOpen={hasChosenLanguage === false} onSelectLanguage={setLanguage} />
      {/* 先确认语言，再选择币种，避免首次设置弹窗重叠。 */}
      <InitialCurrencySelectModal
        isOpen={hasChosenLanguage === true && hasChosenCurrency === false}
        onSelectCurrency={async (selectedCode) => {
          if (chooseInitialCurrency) {
            await chooseInitialCurrency(selectedCode);
          }
          showToast(tx("已成功选择 {p0} 作为您的记账与结算基准币种！", {p0: (selectedCode)}), 'success');
        }}
      />
    </div>
  );
}
