import { tx, useLocale } from "../localization.js";
import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { SlidersHorizontal, Plus, Play, Trash2, Edit2, AlertCircle, ArrowRight, ShieldAlert, X, Sparkles, Filter } from 'lucide-react';
import { fetchWithAuth } from '../api/fetchWithAuth';
import { useToast } from '../ToastContext';

export const formatConditionSummary = (node) => {
  if (!node) return '无匹配条件';
  if (node.field !== undefined) {
    const fieldMap = {
      merchant: '商户',
      description: '商户',
      name: '商户',
      narration: '商户',
      amount: '金额',
      account: '账户',
      notes: '备注',
      type: '类型',
      category: '分类',
    };
    const f = fieldMap[node.field] || node.field;
    const opMap = {
      contains: '包含',
      not_contains: '不包含',
      equals: '=',
      '==': '=',
      not_equals: '!=',
      '!=': '!=',
      starts_with: '开头是',
      ends_with: '结尾是',
      regex: '正则',
      '>': '>',
      '>=': '>=',
      '<': '<',
      '<=': '<=',
    };
    const op = opMap[node.operator] || node.operator;
    return `${f} ${op} "${node.value ?? ''}"`;
  }
  const op = (node.operator || 'AND').toUpperCase();
  const opLabel = op === 'OR' ? ' 或 ' : ' 且 ';
  const subRules = node.rules || [];
  if (subRules.length === 0) return '无匹配条件';
  const parts = subRules.map((r) => {
    if (r.rules && Array.isArray(r.rules)) {
      return `(${formatConditionSummary(r)})`;
    }
    return formatConditionSummary(r);
  });
  return parts.join(opLabel);
};

export default function RulesPage({ embedded = false }) {
  useLocale();
  const { t } = useTranslation();
  const { showToast } = useToast();
  const [rules, setRules] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editingRule, setEditingRule] = useState(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  // Dry-run modal state
  const [dryRunModalOpen, setDryRunModalOpen] = useState(false);
  const [dryRunResults, setDryRunResults] = useState(null);
  const [dryRunLoading, setDryRunLoading] = useState(false);

  // Form state
  const [ruleForm, setRuleForm] = useState({
    name: '',
    description: '',
    priority: 100,
    stop_processing: false,
    is_active: true,
    conditions: {
      operator: 'AND',
      rules: [{ field: 'merchant', operator: 'contains', value: '' }],
    },
    actions: [{ type: 'set_category', value: '' }],
  });

  const fetchRules = async () => {
    setLoading(true);
    try {
      const res = await fetchWithAuth('/api/v1/rules');
      if (res.ok) {
        const data = await res.json();
        setRules(data.rules || []);
      }
    } catch (err) {
      console.error('Failed to fetch rules', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRules();
  }, []);

  const openNewRule = () => {
    setEditingRule(null);
    setRuleForm({
      name: '',
      description: '',
      priority: (rules.length + 1) * 10,
      stop_processing: false,
      is_active: true,
      conditions: {
        operator: 'AND',
        rules: [{ field: 'merchant', operator: 'contains', value: '' }],
      },
      actions: [{ type: 'set_category', value: '' }],
    });
    setDrawerOpen(true);
  };

  const openEditRule = (r) => {
    setEditingRule(r);
    setRuleForm({
      name: r.name,
      description: r.description || '',
      priority: r.priority,
      stop_processing: r.stop_processing,
      is_active: r.is_active,
      conditions: r.conditions || {
        operator: 'AND',
        rules: [{ field: 'merchant', operator: 'contains', value: '' }],
      },
      actions: r.actions?.map(action => ({ ...action, value: action.value ?? action.target_value })) || [{ type: 'set_category', value: '' }],
    });
    setDrawerOpen(true);
  };

  const handleSaveRule = async (e) => {
    e.preventDefault();
    try {
      const url = editingRule ? `/api/v1/rules/${editingRule.id}` : '/api/v1/rules';
      const method = editingRule ? 'PATCH' : 'POST';

      const res = await fetchWithAuth(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(ruleForm),
      });

      if (res.ok) {
        showToast(tx(editingRule ? '规则已更新' : '新规则已创建'), 'success');
        setDrawerOpen(false);
        fetchRules();
      } else {
        const err = await res.json();
        showToast(tx(err.detail || '保存失败'), 'error');
      }
    } catch {
      showToast(tx("请求失败"), 'error');
    }
  };

  const handleDeleteRule = async (id) => {
    if (!window.confirm(tx("确定要删除此规则吗？"))) return;
    try {
      const res = await fetchWithAuth(`/api/v1/rules/${id}`, { method: 'DELETE' });
      if (res.ok) {
        showToast(tx("规则已删除"), 'success');
        fetchRules();
      }
    } catch {
      showToast(tx("删除失败"), 'error');
    }
  };

  // ── 嵌套条件组（Composite Condition Groups）操作方法 ──
  const handleTopOperatorChange = (op) => {
    setRuleForm((prev) => ({
      ...prev,
      conditions: { ...prev.conditions, operator: op },
    }));
  };

  const handleAddTopRule = () => {
    setRuleForm((prev) => ({
      ...prev,
      conditions: {
        ...prev.conditions,
        rules: [
          ...(prev.conditions.rules || []),
          { field: 'merchant', operator: 'contains', value: '' },
        ],
      },
    }));
  };

  const handleAddTopGroup = () => {
    setRuleForm((prev) => ({
      ...prev,
      conditions: {
        ...prev.conditions,
        rules: [
          ...(prev.conditions.rules || []),
          {
            operator: 'OR',
            rules: [
              { field: 'merchant', operator: 'contains', value: '' },
              { field: 'merchant', operator: 'contains', value: '' },
            ],
          },
        ],
      },
    }));
  };

  const handleDeleteTopItem = (topIdx) => {
    setRuleForm((prev) => {
      const list = [...(prev.conditions.rules || [])];
      list.splice(topIdx, 1);
      return {
        ...prev,
        conditions: { ...prev.conditions, rules: list },
      };
    });
  };

  const handleUpdateCondition = (topIdx, subIdx, patch) => {
    setRuleForm((prev) => {
      const list = [...(prev.conditions.rules || [])];
      if (subIdx === null || subIdx === undefined) {
        list[topIdx] = { ...list[topIdx], ...patch };
      } else {
        const group = { ...list[topIdx] };
        const subRules = [...(group.rules || [])];
        subRules[subIdx] = { ...subRules[subIdx], ...patch };
        group.rules = subRules;
        list[topIdx] = group;
      }
      return {
        ...prev,
        conditions: { ...prev.conditions, rules: list },
      };
    });
  };

  const handleGroupOperatorChange = (topIdx, op) => {
    setRuleForm((prev) => {
      const list = [...(prev.conditions.rules || [])];
      list[topIdx] = { ...list[topIdx], operator: op };
      return {
        ...prev,
        conditions: { ...prev.conditions, rules: list },
      };
    });
  };

  const handleAddSubRule = (topIdx) => {
    setRuleForm((prev) => {
      const list = [...(prev.conditions.rules || [])];
      const group = { ...list[topIdx] };
      group.rules = [
        ...(group.rules || []),
        { field: 'merchant', operator: 'contains', value: '' },
      ];
      list[topIdx] = group;
      return {
        ...prev,
        conditions: { ...prev.conditions, rules: list },
      };
    });
  };

  const handleDeleteSubRule = (topIdx, subIdx) => {
    setRuleForm((prev) => {
      const list = [...(prev.conditions.rules || [])];
      const group = { ...list[topIdx] };
      const subRules = [...(group.rules || [])];
      subRules.splice(subIdx, 1);
      group.rules = subRules;
      list[topIdx] = group;
      return {
        ...prev,
        conditions: { ...prev.conditions, rules: list },
      };
    });
  };

  const handleToggleActive = async (rule) => {
    try {
      const res = await fetchWithAuth(`/api/v1/rules/${rule.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active: !rule.is_active }),
      });
      if (res.ok) {
        setRules(rules.map((r) => (r.id === rule.id ? { ...r, is_active: !r.is_active } : r)));
        showToast(tx("状态已更新"), 'info');
      }
    } catch {
      showToast(tx("更新失败"), 'error');
    }
  };

  const handleDryRun = async (rule) => {
    setDryRunLoading(true);
    setDryRunModalOpen(true);
    try {
      const res = await fetchWithAuth('/api/v1/rules/dry-run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          rule: rule ? {
            name: rule.name,
            priority: rule.priority,
            conditions: rule.conditions,
            actions: rule.actions,
            stop_processing: rule.stop_processing,
          } : null,
          limit: 100,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setDryRunResults(data);
      }
    } catch {
      showToast(tx("预演请求失败"), 'error');
    } finally {
      setDryRunLoading(false);
    }
  };

  const handleApplyRetroactive = async () => {
    if (!window.confirm(tx("确定要将当前启用的规则应用到历史全部交易吗？已手动修改的分类不会被覆盖。"))) return;
    try {
      const res = await fetchWithAuth('/api/v1/rules/apply-retroactive', { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        showToast(tx("已成功评估历史交易，共应用更新 {p0} 笔流水", {p0: (data.updated_count || 0)}), 'success');
      }
    } catch {
      showToast(tx("执行失败"), 'error');
    }
  };

  return (
    <div className={embedded ? "space-y-6" : "max-w-6xl mx-auto pb-12 space-y-6"}>
      {/* ── 1. Page Header (Sure Style) ── */}
      {!embedded ? (
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-xs text-zinc-500 mb-1">
              <Link to="/" className="hover:text-zinc-900 dark:hover:text-white transition-colors">{tx("主页")}</Link>
              <span>/</span>
              <span className="font-semibold text-zinc-900 dark:text-zinc-100">{tx("规则引擎")}</span>
            </div>
            <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-zinc-900 dark:text-zinc-100">{tx("规则引擎")}</h1>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => handleDryRun(null)}
              className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-semibold rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-700 transition-colors shadow-2xs cursor-pointer"
              title={tx("预演全部规则")}
            >
              <Play className="w-3.5 h-3.5" />
              <span>{tx("规则预演")}</span>
            </button>

            <button
              onClick={handleApplyRetroactive}
              className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-semibold rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-700 transition-colors shadow-2xs cursor-pointer"
              title={tx("回溯应用到历史流水")}
            >
              <Sparkles className="w-3.5 h-3.5 text-amber-500" />
              <span>{tx("应用到历史")}</span>
            </button>

            <button
              onClick={openNewRule}
              className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-semibold rounded-lg bg-zinc-900 hover:bg-zinc-800 dark:bg-white dark:hover:bg-zinc-100 text-white dark:text-zinc-900 shadow-xs transition-colors cursor-pointer"
            >
              <Plus className="w-4 h-4" />
              <span>{tx("新建规则")}</span>
            </button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3.5 sm:pb-4 border-b border-zinc-100 dark:border-zinc-800">
          <div>
            <h2 className="text-base font-bold text-zinc-900 dark:text-zinc-100">{tx("规则引擎流水线 (Rules Pipeline)")}</h2>
            <p className="text-xs text-zinc-500 mt-0.5">{tx("配置自动分类、打标签及商户标准化流水线规则，支持拖拽排序与单笔实时预演")}</p>
          </div>

          <div className="flex items-center gap-2 flex-wrap w-full sm:w-auto">
            <button
              onClick={() => handleDryRun(null)}
              className="flex-1 sm:flex-initial px-3 py-1.5 text-xs font-semibold rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-700 transition-colors shadow-2xs cursor-pointer flex items-center justify-center gap-1.5 whitespace-nowrap text-center"
              title={tx("预演全部规则")}
            >
              <Play className="w-3.5 h-3.5 shrink-0" />
              <span>{tx("规则预演")}</span>
            </button>

            <button
              onClick={handleApplyRetroactive}
              className="flex-1 sm:flex-initial px-3 py-1.5 text-xs font-semibold rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-700 transition-colors shadow-2xs cursor-pointer flex items-center justify-center gap-1.5 whitespace-nowrap text-center"
              title={tx("回溯应用到历史流水")}
            >
              <Sparkles className="w-3.5 h-3.5 text-amber-500 shrink-0" />
              <span>{tx("应用到历史")}</span>
            </button>

            <button
              onClick={openNewRule}
              className="w-full sm:w-auto px-3.5 py-1.5 text-xs font-bold rounded-lg bg-zinc-900 hover:bg-zinc-800 dark:bg-white dark:hover:bg-zinc-100 text-white dark:text-zinc-900 shadow-xs transition-colors cursor-pointer flex items-center justify-center gap-1.5 whitespace-nowrap text-center"
            >
              <Plus className="w-4 h-4 shrink-0" />
              <span>{tx("新建规则")}</span>
            </button>
          </div>
        </div>
      )}

      {/* ── 2. Sure Info Notice Banner ── */}
      <div className="flex items-center gap-2.5 p-3 sm:p-3.5 rounded-xl border border-zinc-200/80 dark:border-zinc-800 bg-zinc-50/60 dark:bg-zinc-800/40 text-xs text-zinc-600 dark:text-zinc-400">
        <AlertCircle className="w-4 h-4 text-zinc-400 shrink-0" />
        <span className="leading-relaxed">
          {t('rules.aiNotice', tx("Active rules evaluate transactions on import using Specification + Composite trees and regex pattern matching."))}
        </span>
      </div>

      {/* ── 3. Rules List Container (Sure Card Container) ── */}
      <div className="rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-xs divide-y divide-zinc-100 dark:divide-zinc-800">
        {loading ? (
          <div className="py-12 sm:py-20 flex items-center justify-center">
            <span className="w-6 h-6 border-2 border-zinc-900 dark:border-white border-t-transparent rounded-full animate-spin" />
          </div>
        ) : rules.length === 0 ? (
          <div className="py-10 sm:py-20 text-center p-4 sm:p-6 space-y-3">
            <SlidersHorizontal className="w-10 h-10 text-zinc-300 dark:text-zinc-600 mx-auto" />
            <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">{tx("No rules yet")}</h3>
            <p className="text-xs text-zinc-500 max-w-sm mx-auto">{tx("Set up rules to perform actions to your transactions and other data on every sync.")}</p>
            <button
              onClick={openNewRule}
              className="mt-2 inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold rounded-lg bg-zinc-900 hover:bg-zinc-800 text-white shadow-xs transition-colors"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>{tx("New rule")}</span>
            </button>
          </div>
        ) : (
          rules.map((rule) => {
            const condList = rule.conditions?.rules || [];
            const actionList = rule.actions || [];

            return (
              <div
                key={rule.id}
                className="p-3.5 sm:p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 sm:gap-4 hover:bg-zinc-50/50 dark:hover:bg-zinc-800/30 transition-colors"
              >
                {/* Left: Priority Badge & Rule Details */}
                <div className="space-y-2 min-w-0 max-w-full">
                  <div className="flex items-center gap-2 flex-wrap min-w-0">
                    <span className="px-2 py-0.5 rounded-md bg-zinc-100 dark:bg-zinc-800 text-[11px] font-mono font-bold text-zinc-600 dark:text-zinc-300 border border-zinc-200 dark:border-zinc-700 shrink-0">
                      #{rule.priority}
                    </span>
                    <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100 break-words line-clamp-1">
                      {rule.name}
                    </h3>
                    {rule.stop_processing && (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-amber-100 dark:bg-amber-950/40 text-amber-800 dark:text-amber-300 shrink-0">
                        <ShieldAlert className="w-3 h-3" /> {tx("Stop Processing")}</span>
                    )}
                  </div>

                  {/* Conditions & Actions Summary Pills */}
                  <div className="flex flex-wrap items-center gap-2 text-xs min-w-0 max-w-full">
                    {/* Condition badge */}
                    <div
                      className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 font-mono text-[11px] max-w-full min-w-0"
                      title={formatConditionSummary(rule.conditions)}
                    >
                      <Filter className="w-3 h-3 text-zinc-400 shrink-0" />
                      <span className="font-semibold truncate max-w-[200px] sm:max-w-md block min-w-0">
                        {formatConditionSummary(rule.conditions)}
                      </span>
                    </div>

                    <ArrowRight className="w-3 h-3 text-zinc-400 shrink-0 hidden sm:inline" />

                    {/* Actions badge */}
                    <div className="flex flex-wrap gap-1 min-w-0 max-w-full">
                      {actionList.map((a, i) => (
                        <span
                          key={i}
                          className="px-2 py-1 rounded-lg bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 text-[11px] font-medium border border-emerald-200/60 dark:border-emerald-800/40 truncate max-w-full"
                        >
                          {a.type}: {a.value || a.tag || tx("Active")}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Right: Actions & Toggle */}
                <div className="flex items-center gap-3 self-end sm:self-center">
                  <button
                    onClick={() => handleDryRun(rule)}
                    className="p-1.5 rounded-lg text-zinc-500 hover:text-zinc-900 dark:hover:text-white hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
                    title={tx("在历史流水上预演此规则")}
                  >
                    <Play className="w-4 h-4" />
                  </button>

                  <button
                    onClick={() => openEditRule(rule)}
                    className="p-1.5 rounded-lg text-zinc-500 hover:text-zinc-900 dark:hover:text-white hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
                    title={tx("编辑规则")}
                  >
                    <Edit2 className="w-4 h-4" />
                  </button>

                  <button
                    onClick={() => handleDeleteRule(rule.id)}
                    className="p-1.5 rounded-lg text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-950/30 transition-colors"
                    title={tx("删除规则")}
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>

                  {/* Active Switch Toggle */}
                  <button
                    onClick={() => handleToggleActive(rule)}
                    title={rule.is_active ? tx("点击停用") : tx("点击启用")}
                    className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                      rule.is_active ? 'bg-zinc-900 dark:bg-emerald-600' : 'bg-zinc-200 dark:bg-zinc-700'
                    }`}
                  >
                    <span
                      className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                        rule.is_active ? 'translate-x-6' : 'translate-x-1'
                      }`}
                    />
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* ── 4. Bottom Previous/Next Section Navigation (Sure Layout) ── */}
      {!embedded && (
        <div className="grid grid-cols-2 gap-4 pt-2">
          <Link
            to="/settings?tab=preferences"
            className="flex items-center gap-2 p-4 rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 hover:bg-zinc-50 dark:hover:bg-zinc-800/50 transition-colors shadow-2xs group"
          >
            <span className="text-zinc-400 group-hover:-translate-x-0.5 transition-transform">←</span>
            <div>
              <span className="text-[11px] text-zinc-400 uppercase tracking-wider block">{tx("Back")}</span>
              <span className="text-xs font-semibold text-zinc-800 dark:text-zinc-200">{tx("Preferences")}</span>
            </div>
          </Link>

          <Link
            to="/settings?tab=oidc"
            className="flex items-center justify-end gap-2 p-4 rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 hover:bg-zinc-50 dark:hover:bg-zinc-800/50 transition-colors shadow-2xs group text-right"
          >
            <div>
              <span className="text-[11px] text-zinc-400 uppercase tracking-wider block">{tx("Next")}</span>
              <span className="text-xs font-semibold text-zinc-800 dark:text-zinc-200">{tx("OIDC / SSO")}</span>
            </div>
            <span className="text-zinc-400 group-hover:translate-x-0.5 transition-transform">→</span>
          </Link>
        </div>
      )}

      {/* ── Slide-Over / Modal: Rule Editor ── */}
      {drawerOpen && (
        <div className="fixed inset-0 z-50 flex justify-end">
          <div className="fixed inset-0 bg-black/40 backdrop-blur-xs" onClick={() => setDrawerOpen(false)} />
          <div className="relative w-full max-w-xl bg-white dark:bg-zinc-900 h-full shadow-2xl flex flex-col z-10 animate-in slide-in-from-right duration-200">
            <div className="p-5 border-b border-zinc-100 dark:border-zinc-800 flex items-center justify-between">
              <div>
                <h2 className="text-base font-bold text-zinc-900 dark:text-zinc-100">
                  {editingRule ? t('rules.editRule', tx("Edit Rule")) : t('rules.newRule', tx("New Rule"))}
                </h2>
                <p className="text-xs text-zinc-500 mt-0.5">{tx("Specification + Composite pattern rule definition")}</p>
              </div>
              <button
                onClick={() => setDrawerOpen(false)}
                className="p-1.5 rounded-lg text-zinc-400 hover:text-zinc-900 dark:hover:text-white hover:bg-zinc-100 dark:hover:bg-zinc-800"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSaveRule} className="flex-1 overflow-y-auto p-5 space-y-5 text-xs">
              {/* Basic Fields */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4">
                <div className="space-y-1">
                  <label className="font-semibold text-zinc-700 dark:text-zinc-300">
                    {t('rules.ruleName', tx("Rule Name"))}
                  </label>
                  <input
                    type="text"
                    value={ruleForm.name}
                    onChange={(e) => setRuleForm({ ...ruleForm, name: e.target.value })}
                    placeholder={tx("如：美团外卖餐饮分类")}
                    required
                    className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none"
                  />
                </div>

                <div className="space-y-1">
                  <label className="font-semibold text-zinc-700 dark:text-zinc-300">
                    {t('rules.priority', tx("Priority (数字越小越先执行)"))}
                  </label>
                  <input
                    type="number"
                    value={ruleForm.priority}
                    onChange={(e) => setRuleForm({ ...ruleForm, priority: Number(e.target.value) })}
                    required
                    className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none font-mono"
                  />
                </div>
              </div>

              {/* Stop Processing Toggle */}
              <div className="flex items-center gap-2 p-3 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-800/40">
                <input
                  type="checkbox"
                  id="stop_proc"
                  checked={ruleForm.stop_processing}
                  onChange={(e) => setRuleForm({ ...ruleForm, stop_processing: e.target.checked })}
                  className="rounded text-zinc-900"
                />
                <label htmlFor="stop_proc" className="font-medium text-zinc-800 dark:text-zinc-200 cursor-pointer">
                  {t('rules.stopProcessing', tx("Stop Processing Remaining Rules once matched"))}
                </label>
              </div>

              {/* Conditions Block (Composite Groups Supported) */}
              <div className="space-y-3 border border-zinc-200 dark:border-zinc-800 rounded-xl p-4 bg-zinc-50/30 dark:bg-zinc-800/20">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  <span className="font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-1.5 shrink-0">
                    <Filter className="w-3.5 h-3.5 text-zinc-400" />
                    <span>{t('rules.conditions', tx("匹配条件 (Conditions)"))}</span>
                  </span>
                  <div className="flex items-center gap-1.5 shrink-0 self-start sm:self-auto">
                    <span className="text-[11px] text-zinc-500 font-medium whitespace-nowrap">{tx("主规则关系:")}</span>
                    <select
                      value={ruleForm.conditions.operator || 'AND'}
                      onChange={(e) => handleTopOperatorChange(e.target.value)}
                      className="px-2 py-1 bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg text-xs font-semibold outline-none text-zinc-900 dark:text-zinc-100 shadow-2xs"
                    >
                      <option value="AND">{tx("AND (且 - 必须满足所有项)")}</option>
                      <option value="OR">{tx("OR (或 - 满足任一项即可)")}</option>
                    </select>
                  </div>
                </div>

                <div className="space-y-2.5 pt-1">
                  {(ruleForm.conditions.rules || []).map((item, idx) => {
                    const isGroup = Boolean(item.rules && Array.isArray(item.rules));

                    if (isGroup) {
                      return (
                        <div
                          key={idx}
                          className="p-3 rounded-xl bg-amber-50/40 dark:bg-amber-950/20 border border-dashed border-amber-300 dark:border-amber-700/60 space-y-2.5"
                        >
                          <div className="flex items-center justify-between gap-1.5 flex-wrap">
                            <div className="flex items-center gap-1.5 flex-wrap">
                              <span className="px-1.5 py-0.5 rounded text-[11px] font-bold bg-amber-200/80 dark:bg-amber-900/60 text-amber-800 dark:text-amber-200">{tx("条件组")}</span>
                              <select
                                value={item.operator || 'OR'}
                                onChange={(e) => handleGroupOperatorChange(idx, e.target.value)}
                                className="px-2 py-0.5 bg-white dark:bg-zinc-800 border border-amber-300 dark:border-amber-700 rounded-md text-[11px] font-bold text-amber-900 dark:text-amber-200 outline-none"
                              >
                                <option value="OR">{tx("OR (组内任一满足即可)")}</option>
                                <option value="AND">{tx("AND (组内必须全部满足)")}</option>
                              </select>
                            </div>
                            <button
                              type="button"
                              onClick={() => handleDeleteTopItem(idx)}
                              className="text-xs text-rose-500 hover:text-rose-700 flex items-center gap-0.5 px-1.5 py-0.5 rounded hover:bg-rose-50 dark:hover:bg-rose-950/40 cursor-pointer transition-colors"
                              title={tx("删除此条件组")}
                            >
                              <Trash2 className="w-3 h-3" />
                              <span>{tx("删除组")}</span>
                            </button>
                          </div>

                          <div className="space-y-2 pl-2 border-l-2 border-amber-300/70 dark:border-amber-700/70">
                            {(item.rules || []).map((subCond, subIdx) => {
                              const isSubNum = subCond.field === 'amount';
                              return (
                                <div key={subIdx} className="p-2.5 rounded-xl bg-white dark:bg-zinc-800/90 border border-zinc-200/80 dark:border-zinc-700/80 space-y-2">
                                  <div className="grid grid-cols-2 gap-2">
                                    <select
                                      value={subCond.field === 'description' ? 'merchant' : subCond.field || 'merchant'}
                                      onChange={(e) => {
                                        const newF = e.target.value;
                                        handleUpdateCondition(idx, subIdx, {
                                          field: newF,
                                          operator: newF === 'amount' ? '>' : 'contains',
                                        });
                                      }}
                                      className="w-full px-2 py-1.5 bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg outline-none text-xs font-medium text-zinc-900 dark:text-zinc-100"
                                    >
                                      <option value="merchant">{tx("商户 / 交易名称 (Narration)")}</option>
                                      <option value="amount">{tx("金额 (Amount)")}</option>
                                      <option value="account">{tx("所属账户 (Account)")}</option>
                                      <option value="notes">{tx("备注说明 (Notes)")}</option>
                                      <option value="type">{tx("交易类型 (Type)")}</option>
                                    </select>

                                    <select
                                      value={subCond.operator || (isSubNum ? '>' : 'contains')}
                                      onChange={(e) => handleUpdateCondition(idx, subIdx, { operator: e.target.value })}
                                      className="w-full px-2 py-1.5 bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg outline-none text-xs text-zinc-800 dark:text-zinc-200"
                                    >
                                      {isSubNum ? (
                                        <>
                                          <option value=">">{tx("大于 (>)")}</option>
                                          <option value=">=">{tx("大于等于 (>=)")}</option>
                                          <option value="<">{tx("小于 (<)")}</option>
                                          <option value="<=">{tx("小于等于 (<=)")}</option>
                                          <option value="equals">{tx("等于 (==)")}</option>
                                          <option value="!=">{tx("不等于 (!=)")}</option>
                                        </>
                                      ) : (
                                        <>
                                          <option value="contains">{tx("包含 (contains)")}</option>
                                          <option value="not_contains">{tx("不包含 (not contains)")}</option>
                                          <option value="equals">{tx("等于 (equals)")}</option>
                                          <option value="starts_with">{tx("开头是 (starts_with)")}</option>
                                          <option value="ends_with">{tx("结尾是 (ends_with)")}</option>
                                          <option value="regex">{tx("正则匹配 (regex)")}</option>
                                        </>
                                      )}
                                    </select>
                                  </div>

                                  <div className="flex items-center gap-2">
                                    <input
                                      type={isSubNum ? 'number' : 'text'}
                                      step={isSubNum ? 'any' : undefined}
                                      value={subCond.value ?? ''}
                                      onChange={(e) => handleUpdateCondition(idx, subIdx, { value: e.target.value })}
                                      placeholder={
                                        subCond.field === 'amount'
                                          ? tx("如：30 或 100.5")
                                          : subCond.field === 'type'
                                          ? tx("expense (支出) / income (收入)")
                                          : tx("匹配目标值或关键词")
                                      }
                                      required
                                      className="flex-1 px-2.5 py-1.5 bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg outline-none text-xs min-w-0 text-zinc-900 dark:text-zinc-100 font-mono"
                                    />

                                    {(item.rules || []).length > 1 && (
                                      <button
                                        type="button"
                                        onClick={() => handleDeleteSubRule(idx, subIdx)}
                                        className="p-1.5 text-zinc-400 hover:text-rose-500 rounded-lg shrink-0 cursor-pointer transition-colors"
                                        title={tx("删除此子条件")}
                                      >
                                        <X className="w-4 h-4" />
                                      </button>
                                    )}
                                  </div>
                                </div>
                              );
                            })}

                            <button
                              type="button"
                              onClick={() => handleAddSubRule(idx)}
                              className="text-xs text-amber-700 dark:text-amber-300 hover:text-amber-900 dark:hover:text-amber-100 font-medium flex items-center gap-1 pt-1 cursor-pointer"
                            >
                              <Plus className="w-3.5 h-3.5" />
                              <span>{tx("在此组添加条件")}</span>
                            </button>
                          </div>
                        </div>
                      );
                    }

                    // 顶层单条条件
                    const isNum = item.field === 'amount';
                    return (
                      <div key={idx} className="p-2.5 rounded-xl bg-white dark:bg-zinc-800/80 border border-zinc-200/80 dark:border-zinc-700/80 space-y-2">
                        <div className="grid grid-cols-2 gap-2">
                          <select
                            value={item.field === 'description' ? 'merchant' : item.field || 'merchant'}
                            onChange={(e) => {
                              const newF = e.target.value;
                              handleUpdateCondition(idx, null, {
                                field: newF,
                                operator: newF === 'amount' ? '>' : 'contains',
                              });
                            }}
                            className="w-full px-2 py-1.5 bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg outline-none text-xs font-medium text-zinc-900 dark:text-zinc-100"
                          >
                            <option value="merchant">{tx("商户 / 交易名称 (Narration)")}</option>
                            <option value="amount">{tx("金额 (Amount)")}</option>
                            <option value="account">{tx("所属账户 (Account)")}</option>
                            <option value="notes">{tx("备注说明 (Notes)")}</option>
                            <option value="type">{tx("交易类型 (Type)")}</option>
                          </select>

                          <select
                            value={item.operator || (isNum ? '>' : 'contains')}
                            onChange={(e) => handleUpdateCondition(idx, null, { operator: e.target.value })}
                            className="w-full px-2 py-1.5 bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg outline-none text-xs text-zinc-800 dark:text-zinc-200"
                          >
                            {isNum ? (
                              <>
                                <option value=">">{tx("大于 (>)")}</option>
                                <option value=">=">{tx("大于等于 (>=)")}</option>
                                <option value="<">{tx("小于 (<)")}</option>
                                <option value="<=">{tx("小于等于 (<=)")}</option>
                                <option value="equals">{tx("等于 (==)")}</option>
                                <option value="!=">{tx("不等于 (!=)")}</option>
                              </>
                            ) : (
                              <>
                                <option value="contains">{tx("包含 (contains)")}</option>
                                <option value="not_contains">{tx("不包含 (not contains)")}</option>
                                <option value="equals">{tx("等于 (equals)")}</option>
                                <option value="starts_with">{tx("开头是 (starts_with)")}</option>
                                <option value="ends_with">{tx("结尾是 (ends_with)")}</option>
                                <option value="regex">{tx("正则匹配 (regex)")}</option>
                              </>
                            )}
                          </select>
                        </div>

                        <div className="flex items-center gap-2">
                          <input
                            type={isNum ? 'number' : 'text'}
                            step={isNum ? 'any' : undefined}
                            value={item.value ?? ''}
                            onChange={(e) => handleUpdateCondition(idx, null, { value: e.target.value })}
                            placeholder={
                              item.field === 'amount'
                                ? tx("如：30 或 100.5")
                                : item.field === 'type'
                                ? tx("expense (支出) / income (收入)")
                                : tx("匹配目标值或关键词")
                            }
                            required
                            className="flex-1 px-2.5 py-1.5 bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg outline-none text-xs min-w-0 text-zinc-900 dark:text-zinc-100 font-mono"
                          />

                          {(ruleForm.conditions.rules || []).length > 1 && (
                            <button
                              type="button"
                              onClick={() => handleDeleteTopItem(idx)}
                              className="p-1.5 text-zinc-400 hover:text-rose-500 rounded-lg shrink-0 cursor-pointer transition-colors"
                              title={tx("删除此条件")}
                            >
                              <X className="w-4 h-4" />
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })}

                  {/* Actions for Conditions */}
                  <div className="flex items-center gap-2 pt-2 flex-wrap">
                    <button
                      type="button"
                      onClick={handleAddTopRule}
                      className="text-xs text-zinc-700 hover:text-zinc-900 dark:text-zinc-300 dark:hover:text-white font-medium flex items-center gap-1 px-3 py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 hover:bg-zinc-50 dark:hover:bg-zinc-700 transition-colors cursor-pointer"
                    >
                      <Plus className="w-3.5 h-3.5" />
                      <span>{tx("添加单条条件")}</span>
                    </button>
                    <button
                      type="button"
                      onClick={handleAddTopGroup}
                      className="text-xs text-amber-700 hover:text-amber-900 dark:text-amber-300 dark:hover:text-amber-100 font-medium flex items-center gap-1 px-3 py-1.5 rounded-lg border border-dashed border-amber-300 dark:border-amber-700/80 bg-amber-50/40 dark:bg-amber-950/20 hover:bg-amber-50 dark:hover:bg-amber-950/40 transition-colors cursor-pointer"
                    >
                      <Plus className="w-3.5 h-3.5" />
                      <span>{tx("添加条件组 (OR / AND 嵌套)")}</span>
                    </button>
                  </div>
                </div>
              </div>

              {/* Actions Block */}
              <div className="space-y-2 border border-zinc-200 dark:border-zinc-800 rounded-xl p-4 bg-zinc-50/30 dark:bg-zinc-800/20">
                <span className="font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-1.5">
                  <Sparkles className="w-3.5 h-3.5 text-zinc-400" />
                  <span>{t('rules.actions', tx("Actions"))}</span>
                </span>

                <div className="space-y-2 pt-2">
                  {ruleForm.actions.map((act, idx) => (
                    <div key={idx} className="p-2.5 rounded-xl bg-white dark:bg-zinc-800/60 border border-zinc-200/80 dark:border-zinc-700/80 space-y-2">
                      <select
                        value={act.type}
                        onChange={(e) => {
                          const list = [...ruleForm.actions];
                          list[idx].type = e.target.value;
                          setRuleForm({ ...ruleForm, actions: list });
                        }}
                        className="w-full px-2 py-1.5 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg outline-none text-xs"
                      >
                        <option value="set_category">{tx("设置分类 (set_category)")}</option>
                        <option value="set_merchant">{tx("清洗标准化商户 (set_merchant)")}</option>
                        <option value="set_transaction_type">{tx("变更类型 (set_type)")}</option>
                        <option value="add_tag">{tx("追加标签 (add_tag)")}</option>
                        <option value="exclude_from_statistics">{tx("免计入统计 (exclude)")}</option>
                      </select>

                      <div className="flex items-center gap-2">
                        <input
                          type="text"
                          value={act.value || ''}
                          onChange={(e) => {
                            const list = [...ruleForm.actions];
                            list[idx].value = e.target.value;
                            setRuleForm({ ...ruleForm, actions: list });
                          }}
                          placeholder={tx("分类名称、商户名或标签")}
                          required={act.type !== 'exclude_from_statistics'}
                          className="flex-1 px-2.5 py-1.5 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg outline-none text-xs min-w-0"
                        />

                        {ruleForm.actions.length > 1 && (
                          <button
                            type="button"
                            onClick={() => {
                              const list = ruleForm.actions.filter((_, i) => i !== idx);
                              setRuleForm({ ...ruleForm, actions: list });
                            }}
                            className="p-1.5 text-zinc-400 hover:text-rose-500 rounded-lg shrink-0 cursor-pointer"
                            title={tx("删除执行动作")}
                          >
                            <X className="w-4 h-4" />
                          </button>
                        )}
                      </div>
                    </div>
                  ))}

                  <button
                    type="button"
                    onClick={() => {
                      const list = [...ruleForm.actions, { type: 'set_category', value: '' }];
                      setRuleForm({ ...ruleForm, actions: list });
                    }}
                    className="text-xs text-zinc-500 hover:text-zinc-900 dark:hover:text-white font-medium flex items-center gap-1 pt-1"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    <span>{t('rules.addAction', tx("添加执行动作"))}</span>
                  </button>
                </div>
              </div>

              {/* Bottom Actions */}
              <div className="pt-4 border-t border-zinc-100 dark:border-zinc-800 flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setDrawerOpen(false)}
                  className="px-3 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 font-medium"
                >
                  {t('common.cancel', tx("Cancel"))}
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 rounded-lg bg-zinc-900 hover:bg-zinc-800 text-white font-semibold shadow-xs"
                >
                  {t('common.save', tx("Save"))}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── Modal: Dry Run Results ── */}
      {dryRunModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="fixed inset-0 bg-black/50 backdrop-blur-xs" onClick={() => setDryRunModalOpen(false)} />
          <div className="relative w-full max-w-2xl bg-white dark:bg-zinc-900 rounded-2xl border border-zinc-200 dark:border-zinc-800 p-6 shadow-2xl z-10 space-y-4 max-h-[85vh] flex flex-col">
            <div className="flex items-center justify-between pb-3 border-b border-zinc-100 dark:border-zinc-800">
              <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-100">
                {t('rules.dryRunModalTitle', tx("Dry Run Simulation Results"))}
              </h3>
              <button
                onClick={() => setDryRunModalOpen(false)}
                className="p-1 rounded-lg text-zinc-400 hover:text-zinc-900 dark:hover:text-white"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto space-y-2 text-xs">
              {dryRunLoading ? (
                <div className="py-12 text-center text-zinc-400">{tx("Evaluating transactions against pipeline...")}</div>
              ) : !dryRunResults ? (
                <div className="py-12 text-center text-zinc-400">{tx("No results")}</div>
              ) : (
                <>
                  <div className="p-3 rounded-xl bg-zinc-50 dark:bg-zinc-800/50 flex items-center justify-between font-medium">
                    <span>
                      {t('rules.matchedCount', tx("Total matched transactions"))}:
                    </span>
                    <span className="font-bold text-emerald-600 dark:text-emerald-400 font-mono text-sm">
                      {dryRunResults.matched_count || dryRunResults.results?.length || 0} {tx("笔")}</span>
                  </div>

                  <div className="space-y-1.5 divide-y divide-zinc-100 dark:divide-zinc-800">
                    {(dryRunResults.results || []).slice(0, 30).map((r, i) => (
                      <div key={i} className="pt-2 flex items-center justify-between gap-2">
                        <div>
                          <span className="font-semibold text-zinc-900 dark:text-zinc-100 block">
                            {r.narration || tx("未命名交易")}
                          </span>
                          <span className="text-[11px] text-zinc-400">
                            {r.date} {tx("· 命中规则: #")} {r.matched_rule_priority} {r.matched_rule_name}
                          </span>
                        </div>
                        <span className="font-mono font-bold text-zinc-900 dark:text-zinc-100">
                          {r.amount}
                        </span>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>

            <div className="pt-3 border-t border-zinc-100 dark:border-zinc-800 flex justify-end">
              <button
                onClick={() => setDryRunModalOpen(false)}
                className="px-4 py-2 rounded-lg bg-zinc-900 hover:bg-zinc-800 text-white font-semibold text-xs"
              >{tx("关闭")}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
