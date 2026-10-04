import { tx, useLocale } from "../localization.js";
import { useState } from "react";
import { User } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { API_BASE } from "../config";

export default function Avatar({ user, size = "md", cacheBust = "", className = "" }) {
  useLocale();
  const { user: authUser } = useAuth();
  const [imgError, setImgError] = useState(false);

  // Invert the userMap: { displayName -> loginUsername }
  const userMap = authUser?.userMap || {};
  const displayToLogin = Object.fromEntries(
    Object.entries(userMap).map(([login, display]) => [display, login])
  );
  const login = displayToLogin[user] || (userMap[user] ? user : user);

  const avatarUrl = login
    ? `${API_BASE}/auth/avatar/${encodeURIComponent(login)}${cacheBust ? `?v=${cacheBust}` : ""}`
    : null;

  const sizes = {
    sm: "w-6 h-6 text-xs",
    md: "w-10 h-10 text-sm",
    lg: "w-14 h-14 sm:w-16 sm:h-16 text-lg",
    xl: "w-20 h-20 text-2xl",
    full: "w-full h-full",
  };
  const sizeCls = className || sizes[size] || sizes.md;

  if (avatarUrl && !imgError) {
    return (
      <img
        src={avatarUrl}
        alt={user || tx("Avatar")}
        className={`${sizeCls} rounded-full object-cover shrink-0`}
        onError={() => setImgError(true)}
      />
    );
  }

  return (
    <div
      className={`${sizeCls} rounded-full bg-zinc-100 dark:bg-zinc-800 text-zinc-400 dark:text-zinc-500 flex items-center justify-center shrink-0 select-none`}
    >
      <User className="w-1/2 h-1/2 text-zinc-400 dark:text-zinc-500" />
    </div>
  );
}
