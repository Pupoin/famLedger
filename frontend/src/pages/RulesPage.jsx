import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
  useSortable,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import {
  GripVertical,
  Plus,
  Play,
  Trash2,
  Edit2,
  CheckCircle,
  XCircle,
  AlertTriangle,
  ArrowRight,
  ShieldAlert,
} from 'lucide-react';
import { Button, Card, Pill, Drawer, Modal } from '../components/ds/DesignSystem';
import { fetchWithAuth } from '../api/fetchWithAuth';

function SortableRuleItem({ rule, onEdit, onDelete, onDryRun }) {
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id: rule.id });
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  const conditionsSummary = () => {
    try {
      const c = rule.conditions;
      if (!c) return '无条件';
      const op = c.operator || 'AND';
      const list = c.rules || [];
      return `${op} (${list.map(r => `${r.field} ${r.operator} ${r.value}`).join(', ')})`;
    } catch {
      return '自定义条件';
    }
  };

  return (
    <div ref={setNodeRef} style={style} className="relative mb-3">
      <Card className="hover:border-primary/40 transition-all duration-200">
        <div className="flex items-center justify-between gap-4">
          {/* Drag Handle & Info */}
          <div className="flex items-center gap-3">
            <button
              {...attributes}
              {...listeners}
              className="cursor-grab active:cursor-grabbing p-1.5 rounded text-outline/50 hover:text-on-surface hover:bg-surface-container"
            >
              <GripVertical className="w-5 h-5" />
            </button>
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs px-2 py-0.5 rounded bg-surface-container font-semibold">
                #{rule.priority}
              </span>
              <h4 className="font-semibold text-on-surface">{rule.name}</h4>
              {rule.stop_processing && (
                <Pill label="终止后续" variant="warning" icon={ShieldAlert} />
              )}
              {rule.is_active ? (
                <span className="w-2 h-2 rounded-full bg-emerald-500" title="已启用" />
              ) : (
                <span className="w-2 h-2 rounded-full bg-gray-400" title="已停用" />
              )}
            </div>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="secondary"
              icon={Play}
              onClick={() => onDryRun(rule)}
              title="在历史交易上预演"
            >
              预演
            </Button>
            <Button
              size="sm"
              variant="tertiary"
              icon={Edit2}
              onClick={() => onEdit(rule)}
            />
            <Button
              size="sm"
              variant="tertiary"
              className="text-red-500 hover:text-red-600"
              icon={Trash2}
              onClick={() => onDelete(rule.id)}
            />
          </div>
        </div>

        {/* Conditions and Actions Summary */}
        <div className="mt-3 pt-3 border-t border-outline/10 grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
          <div className="flex items-center gap-2">
            <span className="text-on-surface-variant font-medium">条件:</span>
            <code className="bg-surface-container px-2 py-1 rounded text-on-surface font-mono truncate max-w-xs">
              {conditionsSummary()}
            </code>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-on-surface-variant font-medium">动作:</span>
            <div className="flex flex-wrap gap-1">
              {(rule.actions || []).map((act, idx) => (
                <Pill
                  key={idx}
                  label={`${act.type}: ${act.target_value || act.tag || '已配置'}`}
                  variant="info"
                />
              ))}
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
}

export default function RulesPage() {
  const { t } = useTranslation();
  const [rules, setRules] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editingRule, setEditingRule] = useState(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [dryRunModalOpen, setDryRunModalOpen] = useState(false);
  const [dryRunReport, setDryRunReport] = useState(null);
  const [dryRunLoading, setDryRunLoading] = useState(false);

  // Form State
  const [formData, setFormData] = useState({
    name: '',
    priority: 100,
    stop_processing: false,
    is_active: true,
    condition_field: 'merchant',
    condition_operator: 'contains',
    condition_value: '',
    action_type: 'set_category',
    action_value: '',
  });

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  const fetchRules = async () => {
    try {
      setLoading(true);
      const res = await fetchWithAuth('/api/v1/rules');
      if (res.ok) {
        const data = await res.json();
        setRules(data);
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

  const handleDragEnd = async (event) => {
    const { active, over } = event;
    if (active.id !== over.id) {
      const oldIndex = rules.findIndex((r) => r.id === active.id);
      const newIndex = rules.findIndex((r) => r.id === over.id);
      const newRules = arrayMove(rules, oldIndex, newIndex);
      
      // Update priorities locally
      const updatedRules = newRules.map((rule, idx) => ({
        ...rule,
        priority: (idx + 1) * 10,
      }));
      setRules(updatedRules);

      // Persist to backend
      try {
        await fetchWithAuth('/api/v1/rules/reorder', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(
            updatedRules.map((r) => ({ id: r.id, priority: r.priority }))
          ),
        });
      } catch (err) {
        console.error('Failed to reorder rules', err);
      }
    }
  };

  const handleSaveRule = async () => {
    const payload = {
      name: formData.name,
      priority: Number(formData.priority),
      stop_processing: formData.stop_processing,
      is_active: formData.is_active,
      conditions: {
        operator: 'AND',
        rules: [
          {
            field: formData.condition_field,
            operator: formData.condition_operator,
            value: formData.condition_value,
          },
        ],
      },
      actions: [
        {
          type: formData.action_type,
          target_value: formData.action_value,
        },
      ],
    };

    try {
      const url = editingRule ? `/api/v1/rules/${editingRule.id}` : '/api/v1/rules';
      const method = editingRule ? 'PUT' : 'POST';
      const res = await fetchWithAuth(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        setDrawerOpen(false);
        fetchRules();
      }
    } catch (err) {
      console.error('Failed to save rule', err);
    }
  };

  const handleOpenEdit = (rule) => {
    setEditingRule(rule);
    const cond = rule?.conditions?.rules?.[0] || {};
    const act = rule?.actions?.[0] || {};
    setFormData({
      name: rule.name,
      priority: rule.priority,
      stop_processing: rule.stop_processing,
      is_active: rule.is_active,
      condition_field: cond.field || 'merchant',
      condition_operator: cond.operator || 'contains',
      condition_value: cond.value || '',
      action_type: act.type || 'set_category',
      action_value: act.target_value || '',
    });
    setDrawerOpen(true);
  };

  const handleOpenNew = () => {
    setEditingRule(null);
    setFormData({
      name: '',
      priority: (rules.length + 1) * 10,
      stop_processing: false,
      is_active: true,
      condition_field: 'merchant',
      condition_operator: 'contains',
      condition_value: '',
      action_type: 'set_category',
      action_value: '',
    });
    setDrawerOpen(true);
  };

  const handleDeleteRule = async (id) => {
    if (!window.confirm('确定要删除该规则吗？')) return;
    try {
      await fetchWithAuth(`/api/v1/rules/${id}`, { method: 'DELETE' });
      fetchRules();
    } catch (err) {
      console.error('Failed to delete rule', err);
    }
  };

  const handleRunDryRun = async (rule) => {
    setDryRunLoading(true);
    setDryRunModalOpen(true);
    try {
      const res = await fetchWithAuth('/api/v1/rules/dry-run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          rule_id: rule.id,
          conditions: rule.conditions,
          actions: rule.actions,
        }),
      });
      if (res.ok) {
        const report = await res.json();
        setDryRunReport(report);
      }
    } catch (err) {
      console.error('Dry run failed', err);
    } finally {
      setDryRunLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-on-surface">
            {t('rules.title')}
          </h1>
          <p className="text-sm text-on-surface-variant mt-1">
            {t('rules.subtitle')}
          </p>
        </div>
        <Button variant="primary" icon={Plus} onClick={handleOpenNew}>
          {t('rules.newRule')}
        </Button>
      </div>

      {/* Rules Pipeline Container */}
      <div className="bg-surface-container-low p-4 sm:p-6 rounded-2xl border border-outline/15">
        {loading ? (
          <div className="py-12 flex items-center justify-center">
            <span className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
          </div>
        ) : rules.length === 0 ? (
          <div className="py-12 text-center text-on-surface-variant">
            {t('rules.noRules')}
          </div>
        ) : (
          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragEnd={handleDragEnd}
          >
            <SortableContext items={rules.map((r) => r.id)} strategy={verticalListSortingStrategy}>
              {rules.map((rule) => (
                <SortableRuleItem
                  key={rule.id}
                  rule={rule}
                  onEdit={handleOpenEdit}
                  onDelete={handleDeleteRule}
                  onDryRun={handleRunDryRun}
                />
              ))}
            </SortableContext>
          </DndContext>
        )}
      </div>

      {/* Rule Edit Drawer */}
      <Drawer
        isOpen={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        title={editingRule ? '编辑规则' : '新建规则'}
        subtitle="配置规则优先级、条件树匹配和命令式动作"
        footer={
          <>
            <Button variant="tertiary" onClick={() => setDrawerOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button variant="primary" onClick={handleSaveRule}>
              {t('common.save')}
            </Button>
          </>
        }
      >
        <div className="space-y-6">
          {/* Base Info */}
          <div className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-on-surface-variant mb-1">
                规则名称
              </label>
              <input
                type="text"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="w-full px-3 py-2 rounded-md border border-outline/20 bg-surface-container-lowest text-on-surface focus-ring text-sm"
                placeholder="例如：美团外卖自动分类"
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-on-surface-variant mb-1">
                  优先级 (Priority)
                </label>
                <input
                  type="number"
                  value={formData.priority}
                  onChange={(e) => setFormData({ ...formData, priority: e.target.value })}
                  className="w-full px-3 py-2 rounded-md border border-outline/20 bg-surface-container-lowest text-on-surface focus-ring text-sm"
                />
              </div>

              <div className="flex items-center pt-5">
                <label className="flex items-center gap-2 cursor-pointer text-sm font-medium text-on-surface">
                  <input
                    type="checkbox"
                    checked={formData.stop_processing}
                    onChange={(e) => setFormData({ ...formData, stop_processing: e.target.checked })}
                    className="w-4 h-4 rounded text-primary focus-ring"
                  />
                  <span>阻断后续执行</span>
                </label>
              </div>
            </div>
          </div>

          {/* Condition Builder */}
          <div className="border-t border-outline/15 pt-5 space-y-3">
            <h4 className="text-sm font-semibold text-on-surface">匹配条件 (Specification)</h4>
            <div className="grid grid-cols-3 gap-2">
              <select
                value={formData.condition_field}
                onChange={(e) => setFormData({ ...formData, condition_field: e.target.value })}
                className="px-3 py-2 rounded-md border border-outline/20 bg-surface-container-lowest text-on-surface text-sm"
              >
                <option value="merchant">商户名称 (merchant)</option>
                <option value="description">交易摘要 (description)</option>
                <option value="amount">金额 (amount)</option>
                <option value="account_id">账户 (account)</option>
              </select>

              <select
                value={formData.condition_operator}
                onChange={(e) => setFormData({ ...formData, condition_operator: e.target.value })}
                className="px-3 py-2 rounded-md border border-outline/20 bg-surface-container-lowest text-on-surface text-sm"
              >
                <option value="contains">包含 (contains)</option>
                <option value="equals">等于 (equals)</option>
                <option value="starts_with">开头是 (starts_with)</option>
                <option value="regex">正则表达式 (regex)</option>
                <option value="<=">&lt;= 小于等于</option>
                <option value=">=">&gt;= 大于等于</option>
              </select>

              <input
                type="text"
                value={formData.condition_value}
                onChange={(e) => setFormData({ ...formData, condition_value: e.target.value })}
                placeholder="匹配目标值"
                className="px-3 py-2 rounded-md border border-outline/20 bg-surface-container-lowest text-on-surface text-sm"
              />
            </div>
          </div>

          {/* Action Builder */}
          <div className="border-t border-outline/15 pt-5 space-y-3">
            <h4 className="text-sm font-semibold text-on-surface">执行动作 (Command)</h4>
            <div className="grid grid-cols-2 gap-2">
              <select
                value={formData.action_type}
                onChange={(e) => setFormData({ ...formData, action_type: e.target.value })}
                className="px-3 py-2 rounded-md border border-outline/20 bg-surface-container-lowest text-on-surface text-sm"
              >
                <option value="set_category">设置分类 (set_category)</option>
                <option value="set_merchant">标准化商户 (set_merchant)</option>
                <option value="add_tag">追加标签 (add_tag)</option>
                <option value="exclude_from_statistics">排除统计 (exclude)</option>
              </select>

              <input
                type="text"
                value={formData.action_value}
                onChange={(e) => setFormData({ ...formData, action_value: e.target.value })}
                placeholder="目标分类/商户名/标签"
                className="px-3 py-2 rounded-md border border-outline/20 bg-surface-container-lowest text-on-surface text-sm"
              />
            </div>
          </div>
        </div>
      </Drawer>

      {/* Dry Run Report Modal */}
      <Modal
        isOpen={dryRunModalOpen}
        onClose={() => setDryRunModalOpen(false)}
        title="规则历史交易预演 (Dry Run Simulation)"
        footer={
          <Button variant="primary" onClick={() => setDryRunModalOpen(false)}>
            确认并关闭
          </Button>
        }
      >
        {dryRunLoading ? (
          <div className="py-12 flex items-center justify-center">
            <span className="w-8 h-8 border-3 border-primary border-t-transparent rounded-full animate-spin" />
          </div>
        ) : dryRunReport ? (
          <div className="space-y-4">
            <div className="grid grid-cols-3 gap-3">
              <div className="bg-surface-container p-3 rounded-lg text-center">
                <span className="text-xs text-on-surface-variant block">扫描交易</span>
                <span className="text-xl font-bold text-on-surface">{dryRunReport.scanned_count}</span>
              </div>
              <div className="bg-emerald-500/10 p-3 rounded-lg text-center">
                <span className="text-xs text-emerald-600 block">命中匹配</span>
                <span className="text-xl font-bold text-emerald-600">{dryRunReport.matched_count}</span>
              </div>
              <div className="bg-amber-500/10 p-3 rounded-lg text-center">
                <span className="text-xs text-amber-600 block">保护跳过 (手动已改)</span>
                <span className="text-xl font-bold text-amber-600">{dryRunReport.skipped_manual_count}</span>
              </div>
            </div>

            <div>
              <h5 className="text-xs font-semibold text-on-surface mb-2">匹配交易样本:</h5>
              <div className="space-y-2 max-h-60 overflow-y-auto custom-scrollbar">
                {(dryRunReport.diff_samples || []).map((sample, idx) => (
                  <div key={idx} className="p-2.5 rounded bg-surface-container text-xs flex items-center justify-between">
                    <div>
                      <span className="font-semibold text-on-surface block">{sample.name}</span>
                      <span className="text-on-surface-variant font-mono">{sample.date} · ¥{sample.amount}</span>
                    </div>
                    <div className="flex items-center gap-1.5 font-mono">
                      <span className="line-through text-on-surface-variant">{sample.before || '空'}</span>
                      <ArrowRight className="w-3.5 h-3.5 text-primary" />
                      <span className="text-primary font-bold">{sample.after}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
