import { tx } from "../localization.js";
import { API_BASE } from "../config";
import { fetchWithAuth } from "./fetchWithAuth";

export async function uploadAvatar(file) {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetchWithAuth(`${API_BASE}/auth/avatar`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to upload avatar");
  }
  return res.json();
}

export async function getUserPreferences() {
  const res = await fetchWithAuth(`${API_BASE}/user-preferences`);
  if (!res.ok) throw new Error(tx("Failed to fetch user preferences"));
  return res.json();
}

export async function updateUserPreferences(data) {
  const res = await fetchWithAuth(`${API_BASE}/user-preferences`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(tx("Failed to update user preferences"));
  return res.json();
}

export async function getInsights() {
  const res = await fetchWithAuth(`${API_BASE}/insights`);
  if (!res.ok) throw new Error(tx("Failed to fetch insights"));
  return res.json();
}
