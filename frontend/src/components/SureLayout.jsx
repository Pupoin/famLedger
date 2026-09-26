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
} from 'lucide-react';
import { useAuth } from '../auth/AuthContext';
import { useTheme } from '../ThemeContext';
import { useCurrency } from '../CurrencyContext';
import { useUsers } from '../ConfigContext';
import { useToast } from '../ToastContext';
import HelpModal from './HelpModal';
import Avatar from './Avatar';
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
  const { currency, setCurrency, currencies } = useCurrency();
  const { mode } = useUsers();
  const { showToast } = useToast();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
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
    <div className="min-h-screen bg-background text-on-surface flex">
      {/* ── Desktop Sure Rail Sidebar ── */}
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

        {/* Quick Add Button */}
        <div className="px-4 py-2">
          <Link
            to="/add"
            className="flex items-center justify-center gap-2 w-full py-2.5 px-4 rounded-xl bg-primary/10 hover:bg-primary/15 text-primary font-semibold text-sm border border-primary/20 transition-all duration-200 active:scale-[0.98]"
          >
            <PlusCircle className="w-4 h-4" />
            <span>记一笔账</span>
          </Link>
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
          {/* Currency & Theme Toggles */}
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

      {/* ── Mobile Header & Drawer ── */}
      <div className="lg:hidden fixed top-0 inset-x-0 h-14 bg-surface-container-lowest/90 backdrop-blur-md border-b border-outline/10 z-40 flex items-center justify-between px-4">
        <Link to="/" className="flex items-center gap-2">
          <img src="/logo.svg" alt="famLedger" className="h-7 w-7 object-contain" />
          <span className="font-bold text-base font-headline">{config.appName}</span>
        </Link>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setMobileMenuOpen(true)}
            className="p-2 rounded-lg text-on-surface-variant hover:bg-surface-container"
          >
            <Menu className="w-5 h-5" />
          </button>
        </div>
      </div>

      {/* Mobile Drawer Overlay */}
      {mobileMenuOpen && (
        <div className="lg:hidden fixed inset-0 z-50 flex">
          <div
            className="fixed inset-0 bg-black/40 backdrop-blur-xs transition-opacity"
            onClick={() => setMobileMenuOpen(false)}
          />

          <div className="relative w-72 max-w-[80vw] bg-surface-container-lowest h-full shadow-2xl flex flex-col justify-between p-4 z-10">
            <div>
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <img src="/logo.svg" alt="famLedger" className="h-7 w-7" />
                  <span className="font-bold font-headline">{config.appName}</span>
                </div>
                <button
                  onClick={() => setMobileMenuOpen(false)}
                  className="p-1 rounded-lg hover:bg-surface-container"
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

            <div className="pt-4 border-t border-outline/10 space-y-2">
              <button
                onClick={logout}
                className="flex items-center gap-2 w-full px-3 py-2 text-sm text-red-600 font-medium hover:bg-red-500/10 rounded-lg"
              >
                <LogOut className="w-4 h-4" />
                <span>退出登录</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Main Content Area (Sure Style with generous breathing space) ── */}
      <main className="flex-1 lg:pl-64 min-h-screen pt-16 lg:pt-0 flex flex-col">
        <div className="flex-1 max-w-7xl w-full mx-auto p-4 sm:p-6 lg:p-8">
          {children}
        </div>
      </main>

      {/* System Help Modal */}
      {showHelp && <HelpModal onClose={() => setShowHelp(false)} />}
    </div>
  );
}
