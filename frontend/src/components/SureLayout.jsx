import React, { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  CreditCard,
  BarChart3,
  CalendarDays,
  Sparkles,
  Inbox,
  SlidersHorizontal,
  HandCoins,
  PlusCircle,
  HelpCircle,
  Settings,
  LogOut,
  Sun,
  Moon,
  Menu,
  X,
  ChevronRight,
  ShieldCheck,
  Eye,
  EyeOff,
  PanelLeft,
  PanelLeftClose,
  Wallet,
  ReceiptText,
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

const navItems = [
  { to: '/', label: '总览看板', icon: LayoutDashboard },
  { to: '/transactions', label: '交易明细', icon: CreditCard, badge: '163' },
  { to: '/analytics', label: '统计报表', icon: BarChart3 },
  { to: '/calendar', label: '消费日历', icon: CalendarDays },
  { to: '/insights', label: '财务洞察', icon: Sparkles },
  { to: '/emails', label: '邮件归档', icon: Inbox, badge: '164' },
  { to: '/rules', label: '分类规则', icon: SlidersHorizontal },
  { to: '/debts', label: '借贷结算', icon: HandCoins },
];

export default function SureLayout({ children }) {
  const location = useLocation();
  const { user, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const { currency, setCurrency, currencies, privacyMode, togglePrivacyMode } = useCurrency();
  const { mode } = useUsers();
  const { showToast } = useToast();

  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [mobileAccountsDrawerOpen, setMobileAccountsDrawerOpen] = useState(false);
  const [desktopSidebarAccountsOpen, setDesktopSidebarAccountsOpen] = useState(false);
  const [showHelp, setShowHelp] = useState(false);

  const handleCurrencyChange = async (code) => {
    try {
      await setCurrency(code);
    } catch {
      showToast('货币设置更新失败', 'error');
    }
  };

  const modeBadge = mode === 'personal' ? '个人模式' : mode === 'blended' ? '混合模式' : '家庭共享';

  const NavLinkItem = ({ item, isMobile = false }) => {
    const Icon = item.icon;
    const isActive = location.pathname === item.to || (item.to !== '/' && location.pathname.startsWith(item.to));

    return (
      <Link
        to={item.to}
        onClick={() => isMobile && setMobileMenuOpen(false)}
        className={`group relative flex items-center justify-between px-3.5 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 select-none ${
          isActive
            ? 'bg-primary text-white shadow-sm shadow-primary/25 font-semibold'
            : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container/70'
        }`}
      >
        <div className="flex items-center gap-3">
          <Icon className={`w-4 h-4 shrink-0 transition-transform group-hover:scale-110 ${isActive ? 'text-white' : 'text-on-surface-variant group-hover:text-primary'}`} />
          <span className="truncate">{item.label}</span>
        </div>

        {item.badge && (
          <span
            className={`text-[11px] font-mono px-2 py-0.5 rounded-full font-semibold shrink-0 ${
              isActive
                ? 'bg-white/20 text-white'
                : 'bg-surface-container text-on-surface-variant group-hover:bg-primary/10 group-hover:text-primary'
            }`}
          >
            {item.badge}
          </span>
        )}
      </Link>
    );
  };

  return (
    <div className="min-h-screen bg-background text-on-surface flex flex-col lg:flex-row antialiased">
      {/* ── 1. Desktop Primary Left Rail (Sure Style) ── */}
      <aside className="hidden lg:flex fixed inset-y-0 left-0 w-64 border-r border-outline/10 bg-surface-container-lowest flex-col justify-between z-40 select-none shadow-[1px_0_12px_rgba(0,0,0,0.02)]">
        {/* Brand Header */}
        <div className="p-5 pb-3">
          <Link to="/" className="flex items-center gap-3 group">
            <img
              src="/logo.svg"
              alt="famLedger"
              className="h-9 w-9 object-contain drop-shadow-sm transition-transform group-hover:scale-105"
              onError={(e) => { e.currentTarget.src = '/logo.png'; }}
            />
            <div className="min-w-0">
              <span className="text-lg font-bold tracking-tight text-on-surface font-headline flex items-center gap-1.5">
                {config.appName}
              </span>
              <div className="flex items-center gap-1.5 mt-0.5">
                <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-500" />
                <span className="text-[11px] font-medium text-on-surface-variant uppercase tracking-wider">
                  {modeBadge}
                </span>
              </div>
            </div>
          </Link>
        </div>

        {/* Quick Actions (Add & Multi-Card Quick Toggle) */}
        <div className="px-4 py-2 space-y-2">
          <Link
            to="/add"
            className="flex items-center justify-center gap-2 w-full py-2.5 px-4 rounded-xl bg-primary hover:bg-primary/90 text-white font-semibold text-sm shadow-sm shadow-primary/20 transition-all duration-200 active:scale-[0.98]"
          >
            <PlusCircle className="w-4 h-4" />
            <span>记一笔账</span>
          </Link>

          <button
            onClick={() => setDesktopSidebarAccountsOpen(!desktopSidebarAccountsOpen)}
            className={`flex items-center justify-between w-full py-2 px-3 rounded-xl border text-xs font-semibold transition-all duration-200 ${
              desktopSidebarAccountsOpen
                ? 'bg-primary/10 border-primary/40 text-primary'
                : 'bg-surface-container/60 hover:bg-surface-container border-outline/15 text-on-surface-variant'
            }`}
          >
            <div className="flex items-center gap-2">
              <Wallet className="w-3.5 h-3.5 text-primary" />
              <span>多卡账户侧栏</span>
            </div>
            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-surface-container text-on-surface-variant">
              {desktopSidebarAccountsOpen ? '收起' : '展开'}
            </span>
          </button>
        </div>

        {/* Navigation Links */}
        <div className="flex-1 overflow-y-auto px-3 py-2 space-y-1 scrollbar-none">
          <div className="text-[11px] font-bold uppercase tracking-wider text-outline px-3 py-1.5">
            财务中心
          </div>
          {navItems.map((item) => (
            <NavLinkItem key={item.to} item={item} />
          ))}
        </div>

        {/* Footer User & Utility Controls */}
        <div className="p-3 border-t border-outline/10 bg-surface-container-low/50 space-y-2">
          {/* Currency, Privacy Mode & Theme Toggles */}
          <div className="flex items-center justify-between px-1">
            <select
              aria-label="选择显示币种"
              value={currency}
              onChange={(e) => handleCurrencyChange(e.target.value)}
              className="bg-surface-container hover:bg-surface-container-high text-xs font-bold text-on-surface rounded-lg px-2.5 py-1.5 border border-outline/15 outline-none cursor-pointer transition-colors"
            >
              {currencies.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.symbol} {c.code}
                </option>
              ))}
            </select>

            <div className="flex items-center gap-1">
              <button
                onClick={togglePrivacyMode}
                title={privacyMode ? '显示金额' : '隐藏敏感金额 (隐私模式)'}
                className={`p-1.5 rounded-lg transition-colors ${
                  privacyMode
                    ? 'bg-primary/15 text-primary'
                    : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
                }`}
              >
                {privacyMode ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
              <button
                onClick={() => setShowHelp(true)}
                title="系统帮助指南"
                className="p-1.5 rounded-lg text-on-surface-variant hover:text-on-surface hover:bg-surface-container transition-colors"
              >
                <HelpCircle className="w-4 h-4" />
              </button>
              <button
                onClick={toggleTheme}
                title="切换明暗主题"
                className="p-1.5 rounded-lg text-on-surface-variant hover:text-on-surface hover:bg-surface-container transition-colors"
              >
                {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
              </button>
              <Link
                to="/settings"
                title="个人设置"
                className="p-1.5 rounded-lg text-on-surface-variant hover:text-on-surface hover:bg-surface-container transition-colors"
              >
                <Settings className="w-4 h-4" />
              </Link>
            </div>
          </div>

          {/* User Profile Bar */}
          {user && (
            <div className="flex items-center justify-between p-2 rounded-xl bg-surface-container-lowest border border-outline/10">
              <div className="flex items-center gap-2.5 min-w-0">
                <Avatar user={user.displayName || user.username} size="sm" />
                <div className="min-w-0">
                  <div className="text-xs font-bold text-on-surface truncate">
                    {user.displayName || user.username}
                  </div>
                  <div className="text-[10px] text-on-surface-variant truncate">
                    {user.username}
                  </div>
                </div>
              </div>

              <button
                onClick={logout}
                title="退出当前登录"
                className="p-1.5 rounded-lg text-on-surface-variant hover:text-red-600 hover:bg-red-500/10 transition-colors"
              >
                <LogOut className="w-4 h-4" />
              </button>
            </div>
          )}
        </div>
      </aside>

      {/* ── 2. Desktop Collapsible Secondary Accounts Panel (Sure Style) ── */}
      {desktopSidebarAccountsOpen && (
        <aside className="hidden lg:flex fixed inset-y-0 left-64 w-80 border-r border-outline/10 bg-surface-container-lowest/95 backdrop-blur-md flex-col z-30 shadow-lg">
          <AccountsPanel
            onClose={() => setDesktopSidebarAccountsOpen(false)}
          />
        </aside>
      )}

      {/* ── 3. Mobile Header (Sure Style) ── */}
      <header className="lg:hidden fixed top-0 inset-x-0 h-14 bg-surface-container-lowest/90 backdrop-blur-md border-b border-outline/10 z-40 flex items-center justify-between px-4">
        {/* Left: Quick Accounts Drawer Toggle */}
        <button
          onClick={() => setMobileAccountsDrawerOpen(true)}
          title="银行卡 / 账户"
          className="p-2 -ml-2 rounded-xl text-on-surface-variant hover:text-on-surface hover:bg-surface-container active:scale-95 transition-all flex items-center gap-1.5"
        >
          <PanelLeft className="w-5 h-5 text-primary" />
          <span className="text-xs font-bold text-on-surface">卡片</span>
        </button>

        {/* Center: Brand */}
        <Link to="/" className="flex items-center gap-2">
          <img src="/logo.svg" alt="famLedger" className="h-7 w-7 object-contain" onError={(e) => { e.currentTarget.src = '/logo.png'; }} />
          <span className="font-bold text-base font-headline tracking-tight">{config.appName}</span>
        </Link>

        {/* Right: Privacy & Menu */}
        <div className="flex items-center gap-1 -mr-2">
          <button
            onClick={togglePrivacyMode}
            title={privacyMode ? '显示金额' : '隐藏敏感金额'}
            className={`p-2 rounded-xl transition-colors ${
              privacyMode ? 'text-primary bg-primary/10' : 'text-on-surface-variant hover:bg-surface-container'
            }`}
          >
            {privacyMode ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
          </button>
          <button
            onClick={() => setMobileMenuOpen(true)}
            className="p-2 rounded-xl text-on-surface-variant hover:bg-surface-container active:scale-95 transition-transform"
          >
            <Menu className="w-5 h-5" />
          </button>
        </div>
      </header>

      {/* ── 4. Mobile Accounts Drawer (Slide-over) ── */}
      {mobileAccountsDrawerOpen && (
        <div className="lg:hidden fixed inset-0 z-50 flex">
          <div
            className="fixed inset-0 bg-black/50 backdrop-blur-xs transition-opacity"
            onClick={() => setMobileAccountsDrawerOpen(false)}
          />
          <div className="relative w-80 max-w-[85vw] bg-surface-container-lowest h-full shadow-2xl flex flex-col z-10 animate-in slide-in-from-left duration-200">
            <AccountsPanel
              isMobileDrawer
              onClose={() => setMobileAccountsDrawerOpen(false)}
            />
          </div>
        </div>
      )}

      {/* ── 5. Mobile Full Menu Drawer ── */}
      {mobileMenuOpen && (
        <div className="lg:hidden fixed inset-0 z-50 flex justify-end">
          <div
            className="fixed inset-0 bg-black/50 backdrop-blur-xs transition-opacity"
            onClick={() => setMobileMenuOpen(false)}
          />

          <div className="relative w-72 max-w-[80vw] bg-surface-container-lowest h-full shadow-2xl flex flex-col justify-between p-4 z-10 animate-in slide-in-from-right duration-200">
            <div>
              <div className="flex items-center justify-between mb-4 pb-3 border-b border-outline/10">
                <div className="flex items-center gap-2">
                  <img src="/logo.svg" alt="famLedger" className="h-7 w-7" onError={(e) => { e.currentTarget.src = '/logo.png'; }} />
                  <span className="font-bold font-headline">{config.appName}</span>
                </div>
                <button
                  onClick={() => setMobileMenuOpen(false)}
                  className="p-1 rounded-lg hover:bg-surface-container text-on-surface-variant"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              <div className="space-y-1">
                {navItems.map((item) => (
                  <NavLinkItem key={item.to} item={item} isMobile />
                ))}
              </div>
            </div>

            <div className="pt-4 border-t border-outline/10 space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs text-on-surface-variant">明暗主题</span>
                <button
                  onClick={toggleTheme}
                  className="p-1.5 rounded-lg border border-outline/15 text-on-surface"
                >
                  {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
                </button>
              </div>

              <button
                onClick={logout}
                className="flex items-center justify-center gap-2 w-full px-3 py-2 text-sm text-red-600 font-semibold bg-red-500/10 hover:bg-red-500/20 rounded-xl transition-colors"
              >
                <LogOut className="w-4 h-4" />
                <span>退出登录</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── 6. Main Content Area (Sure Style with generous breathing space) ── */}
      <main
        className={`flex-1 min-h-screen pt-16 lg:pt-0 flex flex-col transition-all duration-300 pb-24 lg:pb-8 ${
          desktopSidebarAccountsOpen ? 'lg:pl-[36rem]' : 'lg:pl-64'
        }`}
      >
        {/* Desktop Topbar Quick Switcher */}
        <div className="hidden lg:flex items-center justify-between px-8 py-3.5 border-b border-outline/10 bg-surface-container-lowest/60 backdrop-blur-sm sticky top-0 z-20">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setDesktopSidebarAccountsOpen(!desktopSidebarAccountsOpen)}
              title="切换银行卡账户侧栏"
              className={`p-1.5 rounded-lg border text-xs font-semibold flex items-center gap-1.5 transition-colors ${
                desktopSidebarAccountsOpen
                  ? 'bg-primary text-white border-primary shadow-xs'
                  : 'bg-surface-container hover:bg-surface-container-high border-outline/15 text-on-surface'
              }`}
            >
              <PanelLeft className="w-4 h-4" />
              <span>{desktopSidebarAccountsOpen ? '收起卡片' : '展开银行卡'}</span>
            </button>
            <span className="text-xs text-on-surface-variant">
              支持一户多卡智能对账与流水穿透
            </span>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={togglePrivacyMode}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold border transition-colors ${
                privacyMode
                  ? 'bg-primary/10 border-primary/40 text-primary'
                  : 'bg-surface-container hover:bg-surface-container-high border-outline/15 text-on-surface-variant'
              }`}
            >
              {privacyMode ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
              <span>{privacyMode ? '隐私保护中' : '隐私模式'}</span>
            </button>
          </div>
        </div>

        <div className="flex-1 max-w-7xl w-full mx-auto p-4 sm:p-6 lg:p-8">
          {children}
        </div>
      </main>

      {/* ── 7. Sure Mobile Bottom Navigation Bar (Fixed with Safe Area) ── */}
      <nav
        aria-label="移动端快速导航"
        className="lg:hidden fixed bottom-0 inset-x-0 bg-surface-container-lowest/90 backdrop-blur-md border-t border-outline/15 z-40 px-2 pt-2 pb-[max(env(safe-area-inset-bottom),0.5rem)] flex items-center justify-around shadow-[0_-4px_16px_rgba(0,0,0,0.04)]"
      >
        {/* 1. 总览 */}
        <Link
          to="/"
          className={`flex flex-col items-center gap-1 py-1 px-3 rounded-xl transition-all ${
            location.pathname === '/'
              ? 'text-primary font-bold scale-105'
              : 'text-on-surface-variant hover:text-on-surface'
          }`}
        >
          <LayoutDashboard className="w-5 h-5" />
          <span className="text-[10px] leading-tight">总览</span>
        </Link>

        {/* 2. 我的卡片 (呼出抽屉) */}
        <button
          onClick={() => setMobileAccountsDrawerOpen(true)}
          className="flex flex-col items-center gap-1 py-1 px-3 rounded-xl text-on-surface-variant hover:text-primary transition-all active:scale-95"
        >
          <CreditCard className="w-5 h-5 text-primary" />
          <span className="text-[10px] leading-tight font-semibold text-primary">卡片</span>
        </button>

        {/* 3. 记一笔 (中心突出快捷按钮) */}
        <Link
          to="/add"
          className="flex flex-col items-center -mt-4 group active:scale-95 transition-transform"
        >
          <div className="w-11 h-11 rounded-full bg-primary text-white flex items-center justify-center shadow-md shadow-primary/30 group-hover:bg-primary/90">
            <PlusCircle className="w-6 h-6" />
          </div>
          <span className="text-[10px] font-semibold text-primary mt-0.5">记账</span>
        </Link>

        {/* 4. 流水 */}
        <Link
          to="/transactions"
          className={`flex flex-col items-center gap-1 py-1 px-3 rounded-xl transition-all ${
            location.pathname.startsWith('/transactions')
              ? 'text-primary font-bold scale-105'
              : 'text-on-surface-variant hover:text-on-surface'
          }`}
        >
          <ReceiptText className="w-5 h-5" />
          <span className="text-[10px] leading-tight">明细</span>
        </Link>

        {/* 5. 报表 */}
        <Link
          to="/analytics"
          className={`flex flex-col items-center gap-1 py-1 px-3 rounded-xl transition-all ${
            location.pathname.startsWith('/analytics')
              ? 'text-primary font-bold scale-105'
              : 'text-on-surface-variant hover:text-on-surface'
          }`}
        >
          <BarChart3 className="w-5 h-5" />
          <span className="text-[10px] leading-tight">报表</span>
        </Link>
      </nav>

      {/* System Help Modal */}
      {showHelp && <HelpModal onClose={() => setShowHelp(false)} />}
    </div>
  );
}
