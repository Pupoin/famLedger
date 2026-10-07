import { createModulePreloader } from './modulePreloader';

export const loadAnalytics = createModulePreloader(() => import('../pages/Analytics'));
export const loadNetWorthChart = createModulePreloader(() => import('../components/ds/NetWorthChart'));
export function preloadAnalytics() {
  // Prefetch failures must not reload a page the user is still using.
  loadAnalytics().catch(() => {});
  loadNetWorthChart().catch(() => {});
}
