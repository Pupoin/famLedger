import { tx, useLocale } from "../localization.js";
import { createContext, useContext, useState, useEffect } from "react";
import { API_BASE } from "../config";
import { setOnUnauthorized } from "../api/fetchWithAuth";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  useLocale();
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const refreshUser = async () => {
    try {
      const res = await fetch(`${API_BASE}/auth/me`, { credentials: "include" });
      if (res.ok) {
        const data = await res.json();
        setUser({
          username: data.username,
          displayName: data.display_name,
          email: data.email,
          role: data.role,
          avatarUrl: data.avatar_url,
          userMap: data.user_map || {},
        });
        return data;
      }
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    fetch(`${API_BASE}/auth/me`, { credentials: "include" })
      .then((res) => {
        if (res.ok) return res.json();
        throw new Error(tx("Not authenticated"));
      })
      .then((data) => setUser({
        username: data.username,
        displayName: data.display_name,
        email: data.email,
        role: data.role,
        avatarUrl: data.avatar_url,
        userMap: data.user_map || {},
      }))
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    setOnUnauthorized(() => setUser(null));
    return () => setOnUnauthorized(null);
  }, []);

  const login = async (username, password) => {
    const res = await fetch(`${API_BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-FamLedger-CSRF": "1" },
      credentials: "include",
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Login failed");
    }
    const data = await res.json();
    setUser({
      username: data.username,
      displayName: data.display_name,
      email: data.email,
      role: data.role,
      avatarUrl: data.avatar_url,
      userMap: data.user_map || {},
    });
  };

  const logout = async () => {
    await fetch(`${API_BASE}/auth/logout`, {
      method: "POST",
      headers: { "X-FamLedger-CSRF": "1" },
      credentials: "include",
    });
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, refreshUser, setUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
