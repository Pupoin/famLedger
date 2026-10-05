import { tx, useLocale } from "../localization.js";
import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { API_BASE } from "../config";
import config from "../config";

export default function Login() {
  useLocale();
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [registrationOpen, setRegistrationOpen] = useState(false);
  const [ssoProviders, setSsoProviders] = useState([]);

  useEffect(() => {
    fetch(`${API_BASE}/auth/account-status`)
      .then((r) => r.json())
      .then((data) => setRegistrationOpen(data.registration_open ?? false))
      .catch(() => {});

    // 动态拉取后台已启用的 SSO / OIDC 提供商（名称与启停均由用户/管理员在后台配置）
    fetch('/api/v1/auth/sso/providers')
      .then((r) => r.json())
      .then((data) => setSsoProviders(data.providers || []))
      .catch(() => {});
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await login(username, password);
    } catch (err) {
      setError(tx(err.message || "Login failed"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-background flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="bg-surface-container-lowest rounded-[2rem] p-8 shadow-[0_4px_32px_rgba(47,51,52,0.08)]">
          <div className="text-center mb-8">
            <img
              src="/logo.svg?v=blue-purple"
              alt="famLedger"
              className="h-20 w-20 object-contain mx-auto mb-4"
              onError={(e) => { e.currentTarget.src = '/logo.png?v=blue-purple'; }}
            />
            <h1 className="font-headline text-2xl font-extrabold text-primary tracking-tight">
              {config.appName}
            </h1>
            <p className="text-on-surface-variant text-sm font-medium mt-1">{tx("Sign in to continue")}</p>
          </div>

          {error && (
            <div className="bg-error-container/20 border border-error/20 text-error px-4 py-3 rounded-xl text-sm mb-6 flex items-center gap-2">
              <span className="material-symbols-outlined text-sm">error</span>
              {tx(error)}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="flex flex-col">
              <label className="font-label text-xs uppercase tracking-widest text-on-surface-variant font-semibold mb-2 ml-1">{tx("Username")}</label>
              <div className="bg-surface-container-high rounded-xl px-4 py-3 flex items-center focus-within:bg-surface-container-lowest transition-colors">
                <span className="material-symbols-outlined text-primary/60 mr-3">
                  person
                </span>
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder={tx("Enter your username")}
                  className="bg-transparent border-none focus:ring-0 focus:outline-none w-full font-medium text-on-surface"
                  autoFocus
                  required
                />
              </div>
            </div>

            <div className="flex flex-col">
              <label className="font-label text-xs uppercase tracking-widest text-on-surface-variant font-semibold mb-2 ml-1">{tx("Password")}</label>
              <div className="bg-surface-container-high rounded-xl px-4 py-3 flex items-center focus-within:bg-surface-container-lowest transition-colors">
                <span className="material-symbols-outlined text-primary/60 mr-3">
                  lock
                </span>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={tx("Enter your password")}
                  className="bg-transparent border-none focus:ring-0 focus:outline-none w-full font-medium text-on-surface"
                  required
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={submitting}
              className="w-full h-14 rounded-full bg-gradient-to-r from-primary to-primary-dim text-on-primary font-headline font-bold text-lg shadow-lg hover:shadow-primary/20 active:scale-[0.98] transition-all duration-200 flex items-center justify-center gap-2 disabled:opacity-60 mt-2"
            >
              <span className="material-symbols-outlined">login</span>
              {submitting ? tx("Signing in...") : tx("Sign In")}
            </button>
          </form>

          {/* SSO / OIDC 单点登录入口（根据后台配置动态呈现） */}
          {ssoProviders.length > 0 && (
            <div className="mt-6 space-y-3">
              <div className="relative flex items-center justify-center">
                <div className="border-t border-zinc-200 dark:border-zinc-800 w-full" />
                <span className="bg-surface-container-lowest px-3 text-[11px] font-semibold tracking-wider uppercase text-zinc-400 absolute">{tx("or")}</span>
              </div>

              <div className="space-y-2 pt-2">
                {ssoProviders.map((p) => {
                  // 100% 原始呈现用户在后台 http://localhost:8888/settings?tab=oidc 编辑的按钮文案
                  const buttonText = p.button_text || p.label || tx("Sign in with SSO");

                  return (
                    <a
                      key={p.name}
                      href={p.authorize_url}
                      className="w-full h-12 rounded-full border border-zinc-200/90 dark:border-zinc-700 bg-surface-container-high hover:bg-surface-container hover:border-zinc-300 dark:hover:border-zinc-600 text-on-surface font-medium tracking-normal text-sm shadow-xs transition-all duration-150 flex items-center justify-center gap-2.5 active:scale-[0.98]"
                    >
                      {/* 图标适配 */}
                      {p.name.includes('authelia') ? (
                        <svg className="w-4 h-4 text-primary" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                          <path d="M9 12l2 2 4-4" />
                        </svg>
                      ) : p.name.includes('google') ? (
                        <svg className="w-4 h-4" viewBox="0 0 24 24">
                          <path fill="#4285F4" d="M23.745 12.27c0-.7-.06-1.4-.19-2.07H12v4.51h6.6c-.29 1.52-1.14 2.8-2.4 3.66v3.05h3.88c2.27-2.09 3.665-5.17 3.665-9.15z"/>
                          <path fill="#34A853" d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.88-3.05c-1.08.72-2.45 1.16-4.05 1.16-3.12 0-5.77-2.1-6.72-4.93H1.27v3.14C3.25 21.32 7.31 24 12 24z"/>
                          <path fill="#FBBC05" d="M5.28 14.27c-.25-.72-.38-1.49-.38-2.27s.13-1.55.38-2.27V6.59H1.27C.46 8.21 0 10.05 0 12s.46 3.79 1.27 5.41l4.01-3.14z"/>
                          <path fill="#EA4335" d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.42-3.42C17.95 1.19 15.24 0 12 0 7.31 0 3.25 2.68 1.27 6.59l4.01 3.14c.95-2.83 3.6-4.98 6.72-4.98z"/>
                        </svg>
                      ) : (
                        <svg className="w-4 h-4 text-primary" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                        </svg>
                      )}
                      <span>{buttonText}</span>
                    </a>
                  );
                })}
              </div>
            </div>
          )}

          <div className="flex flex-col items-center gap-3 mt-6">
            <Link
              to="/forgot-password"
              className="text-primary font-bold text-sm hover:underline"
            >{tx("Forgot Password?")}</Link>
            {registrationOpen && (
              <Link
                to="/create-account"
                className="text-primary font-bold text-sm hover:underline"
              >{tx("Create Account")}</Link>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
