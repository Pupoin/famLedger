import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  SlidersHorizontal,
  Plus,
  Play,
  Trash2,
  Edit2,
  CheckCircle2,
  XCircle,
  AlertCircle,
  ArrowRight,
  ShieldAlert,
  GripVertical,
  X,
  Sparkles,
  ChevronDown,
  ChevronRight,
  Layers,
  Filter,
} from 'lucide-react';
import { fetchWithAuth } from '../api/fetchWithAuth';
import { useToast } from '../ToastContext';

export default function RulesPage() {
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
    actions: [{ type: 'set_category', target_value: '' }],
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
      actions: [{ type: 'set_category', target_value: '' }],
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
      actions: r.actions || [{ type: 'set_category', target_value: '' }],
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
        showToast(editingRule ? '规则已更新' : '新规则已创建', 'success');
        setDrawerOpen(false);
        fetchRules();
      } else {
        const err = await res.json();
        showToast(err.detail || '保存失败', 'error');
      }
    } catch {
      showToast('请求失败', 'error');
    }
  };

  const handleDeleteRule = async (id) => {
    if (!window.confirm('确定要删除此规则吗？')) return;
    try {
      const res = await fetchWithAuth(`/api/v1/rules/${id}`, { method: 'DELETE' });
      if (res.ok) {
        showToast('规则已删除', 'success');
        fetchRules();
      }
    } catch {
      showToast('删除失败', 'error');
    }
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
        showToast('状态已更新', 'info');
      }
    } catch {
      showToast('更新失败', 'error');
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
      showToast('预演请求失败', 'error');
    } finally {
      setDryRunLoading(false);
    }
  };

  const handleApplyRetroactive = async () => {
    if (!window.confirm('确定要将当前启用的规则应用到历史全部交易吗？已手动修改的分类不会被覆盖。')) return;
    try {
      const res = await fetchWithAuth('/api/v1/rules/apply-retroactive', { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        showToast(`已成功评估历史交易，共应用更新 ${data.updated_count || 0} 笔流水`, 'success');
      }
    } catch {
      showToast('执行失败', 'error');
    }
  };

  return (
    <div className="max-w-6xl mx-auto pb-12 space-y-6">
      {/* ── 1. Page Header (Sure Style) ── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-xs text-zinc-500 mb-1">
            <Link to="/" className="hover:text-zinc-900 dark:hover:text-white transition-colors">
              Home
            </Link>
            <span>/</span>
            <span className="font-semibold text-zinc-900 dark:text-zinc-100">Rules</span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-zinc-900 dark:text-zinc-100">
            Rules
          </h1>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => handleDryRun(null)}
            className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-semibold rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-700 transition-colors shadow-2xs"
            title="预演全部规则"
          >
            <Play className="w-3.5 h-3.5" />
            <span>Dry Run</span>
          </button>

          <button
            onClick={handleApplyRetroactive}
            className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-semibold rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-700 transition-colors shadow-2xs"
            title="回溯应用到历史流水"
          >
            <Sparkles className="w-3.5 h-3.5 text-amber-500" />
            <span>Apply to History</span>
          </button>

          <button
            onClick={openNewRule}
            className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-semibold rounded-lg bg-zinc-900 hover:bg-zinc-800 text-white shadow-xs transition-colors"
          >
            <Plus className="w-4 h-4" />
            <span>New rule</span>
          </button>
        </div>
      </div>

      {/* ── 2. Sure Info Notice Banner ── */}
      <div className="flex items-center gap-2.5 p-3.5 rounded-xl border border-zinc-200/80 dark:border-zinc-800 bg-zinc-50/60 dark:bg-zinc-800/40 text-xs text-zinc-600 dark:text-zinc-400">
        <AlertCircle className="w-4 h-4 text-zinc-400 shrink-0" />
        <span>
          {t('rules.aiNotice', 'Active rules evaluate transactions on import using Specification + Composite trees and regex pattern matching.')}
        </span>
      </div>

      {/* ── 3. Rules List Container (Sure Card Container) ── */}
      <div className="rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-xs divide-y divide-zinc-100 dark:divide-zinc-800">
        {loading ? (
          <div className="py-24 flex items-center justify-center">
            <span className="w-6 h-6 border-2 border-zinc-900 dark:border-white border-t-transparent rounded-full animate-spin" />
          </div>
        ) : rules.length === 0 ? (
          <div className="py-24 text-center p-6 space-y-3">
            <SlidersHorizontal className="w-10 h-10 text-zinc-300 dark:text-zinc-600 mx-auto" />
            <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
              No rules yet
            </h3>
            <p className="text-xs text-zinc-500 max-w-sm mx-auto">
              Set up rules to perform actions to your transactions and other data on every sync.
            </p>
            <button
              onClick={openNewRule}
              className="mt-2 inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold rounded-lg bg-zinc-900 hover:bg-zinc-800 text-white shadow-xs transition-colors"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>New rule</span>
            </button>
          </div>
        ) : (
          rules.map((rule) => {
            const condList = rule.conditions?.rules || [];
            const actionList = rule.actions || [];

            return (
              <div
                key={rule.id}
                className="p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4 hover:bg-zinc-50/50 dark:hover:bg-zinc-800/30 transition-colors"
              >
                {/* Left: Priority Badge & Rule Details */}
                <div className="space-y-2">
                  <div className="flex items-center gap-2.5">
                    <span className="px-2 py-0.5 rounded-md bg-zinc-100 dark:bg-zinc-800 text-[11px] font-mono font-bold text-zinc-600 dark:text-zinc-300 border border-zinc-200 dark:border-zinc-700">
                      #{rule.priority}
                    </span>
                    <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">
                      {rule.name}
                    </h3>
                    {rule.stop_processing && (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-100 dark:bg-amber-950/40 text-amber-800 dark:text-amber-300">
                        <ShieldAlert className="w-3 h-3" />
                        Stop Processing
                      </span>
                    )}
                  </div>

                  {/* Conditions & Actions Summary Pills */}
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    {/* Condition badge */}
                    <div className="flex items-center gap-1 px-2 py-1 rounded-lg bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 font-mono text-[11px]">
                      <Filter className="w-3 h-3 text-zinc-400" />
                      <span>{rule.conditions?.operator || 'AND'}:</span>
                      <span className="font-semibold truncate max-w-xs">
                        {condList.map((c) => `${c.field} ${c.operator} "${c.value}"`).join(', ') || 'No conditions'}
                      </span>
                    </div>

                    <ArrowRight className="w-3 h-3 text-zinc-400" />

                    {/* Actions badge */}
                    <div className="flex flex-wrap gap-1">
                      {actionList.map((a, i) => (
                        <span
                          key={i}
                          className="px-2 py-1 rounded-lg bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 text-[11px] font-medium border border-emerald-200/60 dark:border-emerald-800/40"
                        >
                          {a.type}: {a.target_value || a.tag || 'Active'}
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
                    title="在历史流水上预演此规则"
                  >
                    <Play className="w-4 h-4" />
                  </button>

                  <button
                    onClick={() => openEditRule(rule)}
                    className="p-1.5 rounded-lg text-zinc-500 hover:text-zinc-900 dark:hover:text-white hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
                    title="编辑规则"
                  >
                    <Edit2 className="w-4 h-4" />
                  </button>

                  <button
                    onClick={() => handleDeleteRule(rule.id)}
                    className="p-1.5 rounded-lg text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-950/30 transition-colors"
                    title="删除规则"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>

                  {/* Active Switch Toggle */}
                  <button
                    onClick={() => handleToggleActive(rule)}
                    title={rule.is_active ? '点击停用' : '点击启用'}
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
      <div className="grid grid-cols-2 gap-4 pt-2">
        <Link
          to="/settings?tab=preferences"
          className="flex items-center gap-2 p-4 rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 hover:bg-zinc-50 dark:hover:bg-zinc-800/50 transition-colors shadow-2xs group"
        >
          <span className="text-zinc-400 group-hover:-translate-x-0.5 transition-transform">←</span>
          <div>
            <span className="text-[10px] text-zinc-400 uppercase tracking-wider block">Back</span>
            <span className="text-xs font-semibold text-zinc-800 dark:text-zinc-200">Preferences</span>
          </div>
        </Link>

        <Link
          to="/settings?tab=oidc"
          className="flex items-center justify-end gap-2 p-4 rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 hover:bg-zinc-50 dark:hover:bg-zinc-800/50 transition-colors shadow-2xs group text-right"
        >
          <div>
            <span className="text-[10px] text-zinc-400 uppercase tracking-wider block">Next</span>
            <span className="text-xs font-semibold text-zinc-800 dark:text-zinc-200">OIDC / SSO</span>
          </div>
          <span className="text-zinc-400 group-hover:translate-x-0.5 transition-transform">→</span>
        </Link>
      </div>

      {/* ── Slide-Over / Modal: Rule Editor ── */}
      {drawerOpen && (
        <div className="fixed inset-0 z-50 flex justify-end">
          <div className="fixed inset-0 bg-black/40 backdrop-blur-xs" onClick={() => setDrawerOpen(false)} />
          <div className="relative w-full max-w-xl bg-white dark:bg-zinc-900 h-full shadow-2xl flex flex-col z-10 animate-in slide-in-from-right duration-200">
            <div className="p-5 border-b border-zinc-100 dark:border-zinc-800 flex items-center justify-between">
              <div>
                <h2 className="text-base font-bold text-zinc-900 dark:text-zinc-100">
                  {editingRule ? t('rules.editRule', 'Edit Rule') : t('rules.newRule', 'New Rule')}
                </h2>
                <p className="text-xs text-zinc-500 mt-0.5">
                  Specification + Composite pattern rule definition
                </p>
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
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="font-semibold text-zinc-700 dark:text-zinc-300">
                    {t('rules.ruleName', 'Rule Name')}
                  </label>
                  <input
                    type="text"
                    value={ruleForm.name}
                    onChange={(e) => setRuleForm({ ...ruleForm, name: e.target.value })}
                    placeholder="如：美团外卖餐饮分类"
                    required
                    className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none"
                  />
                </div>

                <div className="space-y-1">
                  <label className="font-semibold text-zinc-700 dark:text-zinc-300">
                    {t('rules.priority', 'Priority (数字越小越先执行)')}
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
                  {t('rules.stopProcessing', 'Stop Processing Remaining Rules once matched')}
                </label>
              </div>

              {/* Conditions Block */}
              <div className="space-y-2 border border-zinc-200 dark:border-zinc-800 rounded-xl p-4 bg-zinc-50/30 dark:bg-zinc-800/20">
                <div className="flex items-center justify-between">
                  <span className="font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-1.5">
                    <Filter className="w-3.5 h-3.5 text-zinc-400" />
                    <span>{t('rules.conditions', 'Conditions')}</span>
                  </span>
                  <select
                    value={ruleForm.conditions.operator}
                    onChange={(e) =>
                      setRuleForm({
                        ...ruleForm,
                        conditions: { ...ruleForm.conditions, operator: e.target.value },
                      })
                    }
                    className="px-2 py-1 bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg text-xs font-semibold outline-none"
                  >
                    <option value="AND">AND (必须满足所有条件)</option>
                    <option value="OR">OR (满足任一条件即可)</option>
                  </select>
                </div>

                <div className="space-y-2 pt-2">
                  {ruleForm.conditions.rules.map((cond, idx) => (
                    <div key={idx} className="flex items-center gap-2">
                      <select
                        value={cond.field}
                        onChange={(e) => {
                          const list = [...ruleForm.conditions.rules];
                          list[idx].field = e.target.value;
                          setRuleForm({
                            ...ruleForm,
                            conditions: { ...ruleForm.conditions, rules: list },
                          });
                        }}
                        className="px-2 py-1.5 bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg outline-none"
                      >
                        <option value="merchant">商户 (Merchant)</option>
                        <option value="amount">金额 (Amount)</option>
                        <option value="description">描述 (Description)</option>
                        <option value="notes">备注 (Notes)</option>
                      </select>

                      <select
                        value={cond.operator}
                        onChange={(e) => {
                          const list = [...ruleForm.conditions.rules];
                          list[idx].operator = e.target.value;
                          setRuleForm({
                            ...ruleForm,
                            conditions: { ...ruleForm.conditions, rules: list },
                          });
                        }}
                        className="px-2 py-1.5 bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg outline-none"
                      >
                        <option value="contains">包含 (contains)</option>
                        <option value="equals">等于 (equals)</option>
                        <option value="regex">正则匹配 (regex)</option>
                        <option value="starts_with">开头是 (starts_with)</option>
                        <option value=">">大于 (&gt;)</option>
                        <option value="<">小于 (&lt;)</option>
                      </select>

                      <input
                        type="text"
                        value={cond.value}
                        onChange={(e) => {
                          const list = [...ruleForm.conditions.rules];
                          list[idx].value = e.target.value;
                          setRuleForm({
                            ...ruleForm,
                            conditions: { ...ruleForm.conditions, rules: list },
                          });
                        }}
                        placeholder="目标值或正则"
                        required
                        className="flex-1 px-2.5 py-1.5 bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg outline-none"
                      />

                      {ruleForm.conditions.rules.length > 1 && (
                        <button
                          type="button"
                          onClick={() => {
                            const list = ruleForm.conditions.rules.filter((_, i) => i !== idx);
                            setRuleForm({
                              ...ruleForm,
                              conditions: { ...ruleForm.conditions, rules: list },
                            });
                          }}
                          className="p-1 text-zinc-400 hover:text-rose-500"
                        >
                          <X className="w-4 h-4" />
                        </button>
                      )}
                    </div>
                  ))}

                  <button
                    type="button"
                    onClick={() => {
                      const list = [
                        ...ruleForm.conditions.rules,
                        { field: 'merchant', operator: 'contains', value: '' },
                      ];
                      setRuleForm({
                        ...ruleForm,
                        conditions: { ...ruleForm.conditions, rules: list },
                      });
                    }}
                    className="text-xs text-zinc-500 hover:text-zinc-900 dark:hover:text-white font-medium flex items-center gap-1 pt-1"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    <span>{t('rules.addCondition', '添加子条件')}</span>
                  </button>
                </div>
              </div>

              {/* Actions Block */}
              <div className="space-y-2 border border-zinc-200 dark:border-zinc-800 rounded-xl p-4 bg-zinc-50/30 dark:bg-zinc-800/20">
                <span className="font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-1.5">
                  <Sparkles className="w-3.5 h-3.5 text-zinc-400" />
                  <span>{t('rules.actions', 'Actions')}</span>
                </span>

                <div className="space-y-2 pt-2">
                  {ruleForm.actions.map((act, idx) => (
                    <div key={idx} className="flex items-center gap-2">
                      <select
                        value={act.type}
                        onChange={(e) => {
                          const list = [...ruleForm.actions];
                          list[idx].type = e.target.value;
                          setRuleForm({ ...ruleForm, actions: list });
                        }}
                        className="px-2 py-1.5 bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg outline-none"
                      >
                        <option value="set_category">设置分类 (set_category)</option>
                        <option value="set_merchant">清洗标准化商户 (set_merchant)</option>
                        <option value="set_transaction_type">变更类型 (set_type)</option>
                        <option value="add_tag">追加标签 (add_tag)</option>
                        <option value="exclude_from_statistics">免计入统计 (exclude)</option>
                      </select>

                      <input
                        type="text"
                        value={act.target_value || ''}
                        onChange={(e) => {
                          const list = [...ruleForm.actions];
                          list[idx].target_value = e.target.value;
                          setRuleForm({ ...ruleForm, actions: list });
                        }}
                        placeholder="分类名称、商户名或标签"
                        required={act.type !== 'exclude_from_statistics'}
                        className="flex-1 px-2.5 py-1.5 bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg outline-none"
                      />

                      {ruleForm.actions.length > 1 && (
                        <button
                          type="button"
                          onClick={() => {
                            const list = ruleForm.actions.filter((_, i) => i !== idx);
                            setRuleForm({ ...ruleForm, actions: list });
                          }}
                          className="p-1 text-zinc-400 hover:text-rose-500"
                        >
                          <X className="w-4 h-4" />
                        </button>
                      )}
                    </div>
                  ))}

                  <button
                    type="button"
                    onClick={() => {
                      const list = [...ruleForm.actions, { type: 'set_category', target_value: '' }];
                      setRuleForm({ ...ruleForm, actions: list });
                    }}
                    className="text-xs text-zinc-500 hover:text-zinc-900 dark:hover:text-white font-medium flex items-center gap-1 pt-1"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    <span>{t('rules.addAction', '添加执行动作')}</span>
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
                  {t('common.cancel', 'Cancel')}
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 rounded-lg bg-zinc-900 hover:bg-zinc-800 text-white font-semibold shadow-xs"
                >
                  {t('common.save', 'Save')}
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
                {t('rules.dryRunModalTitle', 'Dry Run Simulation Results')}
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
                <div className="py-12 text-center text-zinc-400">Evaluating transactions against pipeline...</div>
              ) : !dryRunResults ? (
                <div className="py-12 text-center text-zinc-400">No results</div>
              ) : (
                <>
                  <div className="p-3 rounded-xl bg-zinc-50 dark:bg-zinc-800/50 flex items-center justify-between font-medium">
                    <span>
                      {t('rules.matchedCount', 'Total matched transactions')}:
                    </span>
                    <span className="font-bold text-emerald-600 dark:text-emerald-400 font-mono text-sm">
                      {dryRunResults.matched_count || dryRunResults.results?.length || 0} 笔
                    </span>
                  </div>

                  <div className="space-y-1.5 divide-y divide-zinc-100 dark:divide-zinc-800">
                    {(dryRunResults.results || []).slice(0, 30).map((r, i) => (
                      <div key={i} className="pt-2 flex items-center justify-between gap-2">
                        <div>
                          <span className="font-semibold text-zinc-900 dark:text-zinc-100 block">
                            {r.merchant_name || r.name}
                          </span>
                          <span className="text-[10px] text-zinc-400">
                            {r.date} · 命中规则: #{r.matched_rule_priority} {r.matched_rule_name}
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
              >
                关闭
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
