import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Users,
  Building,
  Plus,
  ArrowUpRight,
  ArrowDownLeft,
  Calendar,
  CheckCircle2,
  Trash2,
  DollarSign,
  AlertCircle,
} from 'lucide-react';
import { Button, Card, Pill, Drawer } from '../components/ds/DesignSystem';
import { fetchWithAuth } from '../api/fetchWithAuth';

export default function DebtsPage() {
  const { t } = useTranslation();
  const [debts, setDebts] = useState([]);
  const [loans, setLoans] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('lend'); // lend | borrow | loans
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [repayModalOpen, setRepayModalOpen] = useState(false);
  const [selectedDebt, setSelectedDebt] = useState(null);
  const [repayAmount, setRepayAmount] = useState('');

  // Form State
  const [formData, setFormData] = useState({
    counterparty: '',
    debt_type: 'lend',
    principal_amount: '',
    borrowed_date: new Date().toISOString().split('T')[0],
    due_date: '',
    interest_rate: '0',
    notes: '',
  });

  const fetchDebts = async () => {
    try {
      setLoading(true);
      const [debtsRes, loansRes] = await Promise.all([
        fetchWithAuth('/api/v1/debts'),
        fetchWithAuth('/api/v1/debts/loans'),
      ]);
      if (debtsRes.ok) {
        const d = await debtsRes.json();
        setDebts(Array.isArray(d) ? d : (d.items || []));
      }
      if (loansRes.ok) {
        const l = await loansRes.json();
        setLoans(Array.isArray(l) ? l : (l.items || []));
      }
    } catch (err) {
      console.error('Failed to fetch debts or loans', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDebts();
  }, []);

  const handleCreateDebt = async () => {
    try {
      const res = await fetchWithAuth('/api/v1/debts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...formData,
          principal_amount: Number(formData.principal_amount),
          interest_rate: Number(formData.interest_rate),
          due_date: formData.due_date || null,
        }),
      });
      if (res.ok) {
        setDrawerOpen(false);
        fetchDebts();
      }
    } catch (err) {
      console.error('Failed to create debt', err);
    }
  };

  const handleRepay = async () => {
    if (!selectedDebt || !repayAmount) return;
    try {
      const res = await fetchWithAuth(`/api/v1/debts/${selectedDebt.id}/repay`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          amount: Number(repayAmount),
        }),
      });
      if (res.ok) {
        setRepayModalOpen(false);
        setRepayAmount('');
        fetchDebts();
      }
    } catch (err) {
      console.error('Failed to record repayment', err);
    }
  };

  const handleWriteOff = async (id) => {
    if (!window.confirm('确认要对此款项进行坏账核销吗？此操作将剩余额度记为损失。')) return;
    try {
      const res = await fetchWithAuth(`/api/v1/debts/${id}/write-off`, {
        method: 'POST',
      });
      if (res.ok) {
        fetchDebts();
      }
    } catch (err) {
      console.error('Failed to write off debt', err);
    }
  };

  const lendDebts = debts.filter((d) => d.debt_type === 'lend');
  const borrowDebts = debts.filter((d) => d.debt_type === 'borrow');

  const totalLend = lendDebts.reduce((sum, d) => sum + Number(d.remaining_amount || 0), 0);
  const totalBorrow = borrowDebts.reduce((sum, d) => sum + Number(d.remaining_amount || 0), 0);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-on-surface">
            {t('debts.title')}
          </h1>
          <p className="text-sm text-on-surface-variant mt-1">
            {t('debts.subtitle')}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="primary"
            icon={Plus}
            onClick={() => {
              setFormData({
                counterparty: '',
                debt_type: 'lend',
                principal_amount: '',
                borrowed_date: new Date().toISOString().split('T')[0],
                due_date: '',
                interest_rate: '0',
                notes: '',
              });
              setDrawerOpen(true);
            }}
          >
            {t('debts.newDebt')}
          </Button>
        </div>
      </div>

      {/* Summary KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Card className="flex items-center gap-4">
          <div className="p-3 rounded-xl bg-emerald-500/10 text-emerald-600">
            <ArrowDownLeft className="w-6 h-6" />
          </div>
          <div>
            <span className="text-xs text-on-surface-variant block font-medium">别人欠我 (应收债权)</span>
            <span className="text-2xl font-bold font-mono text-emerald-600">¥{totalLend.toFixed(2)}</span>
          </div>
        </Card>

        <Card className="flex items-center gap-4">
          <div className="p-3 rounded-xl bg-red-500/10 text-red-600">
            <ArrowUpRight className="w-6 h-6" />
          </div>
          <div>
            <span className="text-xs text-on-surface-variant block font-medium">我欠别人 (应付债务)</span>
            <span className="text-2xl font-bold font-mono text-red-600">¥{totalBorrow.toFixed(2)}</span>
          </div>
        </Card>

        <Card className="flex items-center gap-4">
          <div className="p-3 rounded-xl bg-blue-500/10 text-blue-600">
            <Building className="w-6 h-6" />
          </div>
          <div>
            <span className="text-xs text-on-surface-variant block font-medium">金融机构贷款数</span>
            <span className="text-2xl font-bold font-mono text-on-surface">{loans.length} 笔</span>
          </div>
        </Card>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-outline/15 gap-4">
        <button
          onClick={() => setActiveTab('lend')}
          className={`pb-3 text-sm font-semibold border-b-2 transition-colors ${
            activeTab === 'lend'
              ? 'border-primary text-primary'
              : 'border-transparent text-on-surface-variant hover:text-on-surface'
          }`}
        >
          别人欠我 ({lendDebts.length})
        </button>
        <button
          onClick={() => setActiveTab('borrow')}
          className={`pb-3 text-sm font-semibold border-b-2 transition-colors ${
            activeTab === 'borrow'
              ? 'border-primary text-primary'
              : 'border-transparent text-on-surface-variant hover:text-on-surface'
          }`}
        >
          我欠别人 ({borrowDebts.length})
        </button>
        <button
          onClick={() => setActiveTab('loans')}
          className={`pb-3 text-sm font-semibold border-b-2 transition-colors ${
            activeTab === 'loans'
              ? 'border-primary text-primary'
              : 'border-transparent text-on-surface-variant hover:text-on-surface'
          }`}
        >
          金融贷款 ({loans.length})
        </button>
      </div>

      {/* Main List */}
      <div className="space-y-3">
        {loading ? (
          <div className="py-12 flex items-center justify-center">
            <span className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
          </div>
        ) : activeTab === 'loans' ? (
          loans.length === 0 ? (
            <div className="py-12 text-center text-on-surface-variant">暂无银行贷款记录</div>
          ) : (
            loans.map((loan) => (
              <Card key={loan.id} className="flex items-center justify-between">
                <div>
                  <h4 className="font-semibold text-on-surface text-base">{loan.lender_name || '贷款机构'}</h4>
                  <div className="flex items-center gap-3 text-xs text-on-surface-variant mt-1">
                    <span>类型: {loan.loan_type}</span>
                    <span>年利率: {loan.interest_rate}%</span>
                    <span>期限: {loan.term_months} 个月</span>
                  </div>
                </div>
                <div className="text-right">
                  <span className="text-lg font-bold font-mono text-on-surface block">
                    ¥{Number(loan.original_amount).toFixed(2)}
                  </span>
                  <span className="text-xs text-on-surface-variant">月供: ¥{Number(loan.monthly_payment || 0).toFixed(2)}</span>
                </div>
              </Card>
            ))
          )
        ) : (
          (activeTab === 'lend' ? lendDebts : borrowDebts).length === 0 ? (
            <div className="py-12 text-center text-on-surface-variant">暂无借据记录</div>
          ) : (
            (activeTab === 'lend' ? lendDebts : borrowDebts).map((debt) => (
              <Card key={debt.id} className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2">
                    <h4 className="font-semibold text-on-surface text-base">{debt.counterparty}</h4>
                    <Pill
                      label={debt.status === 'active' ? '进行中' : debt.status === 'settled' ? '已结清' : '已核销'}
                      variant={debt.status === 'active' ? 'warning' : debt.status === 'settled' ? 'success' : 'error'}
                    />
                  </div>
                  <div className="flex items-center gap-4 text-xs text-on-surface-variant mt-1.5 font-mono">
                    <span>发生日: {debt.borrowed_date}</span>
                    {debt.due_date && <span>约定归还: {debt.due_date}</span>}
                    {Number(debt.interest_rate) > 0 && <span>年息: {debt.interest_rate}%</span>}
                  </div>
                </div>

                <div className="flex items-center gap-4">
                  <div className="text-right">
                    <span className="text-xs text-on-surface-variant block">剩余待还 / 原始本金</span>
                    <span className="text-lg font-bold font-mono text-on-surface">
                      ¥{Number(debt.remaining_amount).toFixed(2)}{' '}
                      <span className="text-xs text-on-surface-variant font-normal">
                        / ¥{Number(debt.principal_amount).toFixed(2)}
                      </span>
                    </span>
                  </div>

                  {debt.status === 'active' && (
                    <div className="flex items-center gap-2">
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => {
                          setSelectedDebt(debt);
                          setRepayAmount(debt.remaining_amount);
                          setRepayModalOpen(true);
                        }}
                      >
                        记录还款
                      </Button>
                      {activeTab === 'lend' && (
                        <Button
                          size="sm"
                          variant="tertiary"
                          className="text-red-500 hover:text-red-600"
                          onClick={() => handleWriteOff(debt.id)}
                        >
                          核销
                        </Button>
                      )}
                    </div>
                  )}
                </div>
              </Card>
            ))
          )
        )}
      </div>

      {/* New Debt Drawer */}
      <Drawer
        isOpen={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        title="新建亲友借据"
        subtitle="登记一笔往来借出或借入款项，全程跟踪分批还款"
        footer={
          <>
            <Button variant="tertiary" onClick={() => setDrawerOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button variant="primary" onClick={handleCreateDebt}>
              {t('common.save')}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-on-surface-variant mb-1">借贷类型</label>
            <div className="grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setFormData({ ...formData, debt_type: 'lend' })}
                className={`py-2 px-3 rounded-lg border text-sm font-semibold flex items-center justify-center gap-2 ${
                  formData.debt_type === 'lend'
                    ? 'border-emerald-500 bg-emerald-500/10 text-emerald-600'
                    : 'border-outline/20 text-on-surface'
                }`}
              >
                <ArrowDownLeft className="w-4 h-4" /> 别人欠我 (借出)
              </button>
              <button
                type="button"
                onClick={() => setFormData({ ...formData, debt_type: 'borrow' })}
                className={`py-2 px-3 rounded-lg border text-sm font-semibold flex items-center justify-center gap-2 ${
                  formData.debt_type === 'borrow'
                    ? 'border-red-500 bg-red-500/10 text-red-600'
                    : 'border-outline/20 text-on-surface'
                }`}
              >
                <ArrowUpRight className="w-4 h-4" /> 我欠别人 (借入)
              </button>
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-on-surface-variant mb-1">往来对象姓名</label>
            <input
              type="text"
              value={formData.counterparty}
              onChange={(e) => setFormData({ ...formData, counterparty: e.target.value })}
              placeholder="例如：张三"
              className="w-full px-3 py-2 rounded-md border border-outline/20 bg-surface-container-lowest text-on-surface focus-ring text-sm"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-on-surface-variant mb-1">借款本金金额 (¥)</label>
            <input
              type="number"
              step="0.01"
              value={formData.principal_amount}
              onChange={(e) => setFormData({ ...formData, principal_amount: e.target.value })}
              placeholder="0.00"
              className="w-full px-3 py-2 rounded-md border border-outline/20 bg-surface-container-lowest text-on-surface focus-ring text-sm"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-on-surface-variant mb-1">发生日期</label>
              <input
                type="date"
                value={formData.borrowed_date}
                onChange={(e) => setFormData({ ...formData, borrowed_date: e.target.value })}
                className="w-full px-3 py-2 rounded-md border border-outline/20 bg-surface-container-lowest text-on-surface focus-ring text-sm"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-on-surface-variant mb-1">约定归还日期 (选填)</label>
              <input
                type="date"
                value={formData.due_date}
                onChange={(e) => setFormData({ ...formData, due_date: e.target.value })}
                className="w-full px-3 py-2 rounded-md border border-outline/20 bg-surface-container-lowest text-on-surface focus-ring text-sm"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-on-surface-variant mb-1">约定年化利息 % (选填)</label>
            <input
              type="number"
              step="0.01"
              value={formData.interest_rate}
              onChange={(e) => setFormData({ ...formData, interest_rate: e.target.value })}
              className="w-full px-3 py-2 rounded-md border border-outline/20 bg-surface-container-lowest text-on-surface focus-ring text-sm"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-on-surface-variant mb-1">备注说明</label>
            <textarea
              rows={3}
              value={formData.notes}
              onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
              placeholder="借款缘由等..."
              className="w-full px-3 py-2 rounded-md border border-outline/20 bg-surface-container-lowest text-on-surface focus-ring text-sm"
            />
          </div>
        </div>
      </Drawer>

      {/* Repay Modal */}
      {repayModalOpen && selectedDebt && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-xs">
          <div className="bg-surface-container-lowest p-6 rounded-2xl shadow-xl max-w-sm w-full border border-outline/20 space-y-4">
            <h3 className="text-lg font-semibold text-on-surface">记录还款</h3>
            <p className="text-xs text-on-surface-variant">
              往来对象: <span className="font-semibold text-on-surface">{selectedDebt.counterparty}</span> | 剩余待还: ¥{selectedDebt.remaining_amount}
            </p>
            <div>
              <label className="block text-xs font-medium text-on-surface-variant mb-1">本次还款金额</label>
              <input
                type="number"
                step="0.01"
                value={repayAmount}
                onChange={(e) => setRepayAmount(e.target.value)}
                className="w-full px-3 py-2 rounded-md border border-outline/20 bg-surface-container-lowest text-on-surface focus-ring text-sm"
              />
            </div>
            <div className="flex items-center justify-end gap-2 pt-2">
              <Button variant="tertiary" onClick={() => setRepayModalOpen(false)}>
                取消
              </Button>
              <Button variant="primary" onClick={handleRepay}>
                确认还款
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
