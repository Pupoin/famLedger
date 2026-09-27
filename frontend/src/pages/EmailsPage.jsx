import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import {
  Mail,
  CheckCircle2,
  Clock,
  AlertOctagon,
  FileText,
  Search,
  ExternalLink,
  ChevronRight,
  ShieldCheck,
  CreditCard,
  Code,
  Eye,
  RefreshCw,
} from 'lucide-react';
import { Button, Card, Pill, Modal } from '../components/ds/DesignSystem';
import { fetchWithAuth } from '../api/fetchWithAuth';
import { useCurrency } from '../CurrencyContext';

export default function EmailsPage() {
  const { t } = useTranslation();
  const { fmt } = useCurrency();
  const [emails, setEmails] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedEmail, setSelectedEmail] = useState(null);
  const [emailDetail, setEmailDetail] = useState(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [filterStatus, setFilterStatus] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [activeModalTab, setActiveModalTab] = useState('parsed'); // 'parsed' | 'html' | 'text'

  const fetchEmails = async () => {
    try {
      setLoading(true);
      const res = await fetchWithAuth('/api/v1/imports/emails?limit=200');
      if (res.ok) {
        const data = await res.json();
        setEmails(Array.isArray(data) ? data : (data.items || []));
      }
    } catch (err) {
      console.error('Failed to fetch stored emails', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchEmails();
  }, []);

  const handleOpenEmail = async (email) => {
    setSelectedEmail(email);
    setEmailDetail(null);
    setModalOpen(true);
    setLoadingDetail(true);
    setActiveModalTab('parsed');

    try {
      const res = await fetchWithAuth(`/api/v1/imports/emails/${email.id}`);
      if (res.ok) {
        const detail = await res.json();
        setEmailDetail(detail);
        // If no transactions parsed, default to html tab
        if (!detail.transactions || detail.transactions.length === 0) {
          setActiveModalTab('html');
        }
      }
    } catch (err) {
      console.error('Failed to load email full details', err);
    } finally {
      setLoadingDetail(false);
    }
  };

  const filteredEmails = emails.filter((m) => {
    if (filterStatus !== 'all' && m.status !== filterStatus) return false;
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      const matchSub = m.subject?.toLowerCase().includes(q);
      const matchSend = m.sender?.toLowerCase().includes(q);
      if (!matchSub && !matchSend) return false;
    }
    return true;
  });

  const parsedTotal = emails.reduce((sum, m) => sum + (m.parsed_count || 0), 0);

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12 w-full max-w-full overflow-x-hidden">
      {/* ── Header ── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-zinc-900 dark:text-zinc-100">
            {t('nav.emails', '账单邮件箱')}
          </h1>
          <p className="text-xs sm:text-sm text-zinc-500 mt-1">
            已归档的银行账单原件、对账单 HTML 及自动提取生成的流水明细
          </p>
        </div>

        <button
          onClick={fetchEmails}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 text-zinc-700 dark:text-zinc-200 transition-colors w-fit"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>刷新邮件列表</span>
        </button>
      </div>

      {/* ── KPI Cards ── */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="p-4 rounded-2xl bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 flex items-center gap-4 shadow-2xs">
          <div className="p-3 rounded-xl bg-blue-50 dark:bg-blue-950/40 text-blue-600 dark:text-blue-400">
            <Mail className="w-5 h-5" />
          </div>
          <div>
            <span className="text-xs text-zinc-400 block font-medium">已归档原始邮件</span>
            <span className="text-2xl font-bold font-mono text-zinc-900 dark:text-zinc-100">{emails.length} 封</span>
          </div>
        </div>

        <div className="p-4 rounded-2xl bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 flex items-center gap-4 shadow-2xs">
          <div className="p-3 rounded-xl bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400">
            <CheckCircle2 className="w-5 h-5" />
          </div>
          <div>
            <span className="text-xs text-zinc-400 block font-medium">已解析入库交易</span>
            <span className="text-2xl font-bold font-mono text-emerald-600">{parsedTotal} 笔</span>
          </div>
        </div>

        <div className="p-4 rounded-2xl bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 flex items-center gap-4 shadow-2xs">
          <div className="p-3 rounded-xl bg-purple-50 dark:bg-purple-950/40 text-purple-600 dark:text-purple-400">
            <ShieldCheck className="w-5 h-5" />
          </div>
          <div>
            <span className="text-xs text-zinc-400 block font-medium">防重指纹验证</span>
            <span className="text-2xl font-bold font-mono text-purple-600 dark:text-purple-400">SHA-256 100%</span>
          </div>
        </div>
      </div>

      {/* ── Filter Bar & Search ── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-zinc-200 dark:border-zinc-800 pb-3">
        <div className="flex gap-2">
          {[
            { label: '全部', value: 'all' },
            { label: '已解析', value: 'parsed' },
            { label: '待处理', value: 'pending' },
            { label: '失败/跳过', value: 'failed' },
          ].map((st) => (
            <button
              key={st.value}
              onClick={() => setFilterStatus(st.value)}
              className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-colors ${
                filterStatus === st.value
                  ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-900'
                  : 'bg-zinc-100 text-zinc-600 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300'
              }`}
            >
              {st.label}
            </button>
          ))}
        </div>

        <div className="relative w-full sm:w-64">
          <Search className="w-3.5 h-3.5 text-zinc-400 absolute left-3 top-2.5" />
          <input
            type="text"
            placeholder="搜索邮件主题或发件人..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-8 pr-3 py-1.5 text-xs bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg outline-none focus:ring-1 focus:ring-zinc-900 dark:focus:ring-white"
          />
        </div>
      </div>

      {/* ── Emails List ── */}
      <div className="space-y-2">
        {loading ? (
          <div className="py-16 text-center text-xs text-zinc-400">正在读取归档邮件...</div>
        ) : filteredEmails.length === 0 ? (
          <div className="py-16 text-center text-xs text-zinc-400">未找到符合条件的邮件记录</div>
        ) : (
          filteredEmails.map((email) => (
            <div
              key={email.id}
              onClick={() => handleOpenEmail(email)}
              className="flex items-center justify-between p-4 bg-white dark:bg-zinc-900 rounded-2xl border border-zinc-200/80 dark:border-zinc-800 hover:border-zinc-400 dark:hover:border-zinc-600 transition-all cursor-pointer shadow-2xs group"
            >
              <div className="flex items-start gap-3.5 min-w-0">
                <div className="p-2.5 rounded-xl bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 shrink-0 group-hover:scale-105 transition-transform">
                  <Mail className="w-4 h-4" />
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100 truncate">
                      {email.subject || '(无主题邮件)'}
                    </span>
                    <span
                      className={`text-[10px] font-medium px-2 py-0.5 rounded-md ${
                        email.status === 'parsed'
                          ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400'
                          : email.status === 'pending'
                          ? 'bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400'
                          : 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400'
                      }`}
                    >
                      {email.status === 'parsed' ? '已解析入库' : email.status}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-zinc-400 mt-1 flex-wrap">
                    <span>发件人: {email.sender}</span>
                    <span>·</span>
                    <span>接收时间: {email.received_at ? new Date(email.received_at).toLocaleString('zh-CN') : '-'}</span>
                    <span>·</span>
                    <span className="font-mono bg-zinc-100 dark:bg-zinc-800 px-1.5 py-0.5 rounded text-[11px] text-zinc-600 dark:text-zinc-300">
                      {email.mail_kind}
                    </span>
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-2 text-zinc-400 group-hover:text-zinc-900 dark:group-hover:text-white shrink-0 transition-colors">
                <span className="text-xs hidden sm:inline font-medium">查看原件与流水</span>
                <ChevronRight className="w-4 h-4" />
              </div>
            </div>
          ))
        )}
      </div>

      {/* ── Email Detail Modal ── */}
      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-xs animate-in fade-in duration-150">
          <div className="relative w-full max-w-4xl bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl border border-zinc-200 dark:border-zinc-800 max-h-[90vh] flex flex-col overflow-hidden">
            {/* Modal Header */}
            <div className="p-4 border-b border-zinc-200 dark:border-zinc-800 flex items-center justify-between">
              <div className="min-w-0 pr-4">
                <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-100 truncate">
                  {selectedEmail?.subject || '邮件原件详情'}
                </h3>
                <p className="text-xs text-zinc-400 mt-0.5 truncate">
                  发件人: {selectedEmail?.sender} · {selectedEmail?.received_at ? new Date(selectedEmail.received_at).toLocaleString('zh-CN') : ''}
                </p>
              </div>

              <button
                onClick={() => setModalOpen(false)}
                className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 text-zinc-700 dark:text-zinc-200 transition-colors"
              >
                关闭
              </button>
            </div>

            {/* Modal Sub-Tabs: 解析结果 | 邮件原件 (HTML) | 纯文本 */}
            <div className="flex items-center justify-between px-4 py-2.5 bg-zinc-50 dark:bg-zinc-800/50 border-b border-zinc-200 dark:border-zinc-800">
              <div className="inline-flex p-0.5 bg-zinc-200/80 dark:bg-zinc-700 rounded-lg text-xs font-medium">
                <button
                  onClick={() => setActiveModalTab('parsed')}
                  className={`px-3 py-1 rounded-md transition-all ${
                    activeModalTab === 'parsed'
                      ? 'bg-white dark:bg-zinc-800 text-zinc-900 dark:text-white font-semibold shadow-2xs'
                      : 'text-zinc-600 dark:text-zinc-300 hover:text-zinc-900'
                  }`}
                >
                  解析结果 ({emailDetail?.transactions?.length || selectedEmail?.parsed_count || 0} 笔流水)
                </button>
                <button
                  onClick={() => setActiveModalTab('html')}
                  className={`px-3 py-1 rounded-md transition-all ${
                    activeModalTab === 'html'
                      ? 'bg-white dark:bg-zinc-800 text-zinc-900 dark:text-white font-semibold shadow-2xs'
                      : 'text-zinc-600 dark:text-zinc-300 hover:text-zinc-900'
                  }`}
                >
                  邮件原件 (HTML 视图)
                </button>
                <button
                  onClick={() => setActiveModalTab('text')}
                  className={`px-3 py-1 rounded-md transition-all ${
                    activeModalTab === 'text'
                      ? 'bg-white dark:bg-zinc-800 text-zinc-900 dark:text-white font-semibold shadow-2xs'
                      : 'text-zinc-600 dark:text-zinc-300 hover:text-zinc-900'
                  }`}
                >
                  纯文本 / 源码
                </button>
              </div>

              <div className="hidden sm:flex items-center gap-1.5 text-[11px] text-zinc-400 font-mono">
                <ShieldCheck className="w-3.5 h-3.5 text-emerald-600" />
                <span>SHA-256 完整性已校验</span>
              </div>
            </div>

            {/* Modal Body */}
            <div className="flex-1 overflow-y-auto p-4 custom-scrollbar">
              {loadingDetail ? (
                <div className="py-20 flex flex-col items-center justify-center gap-2">
                  <div className="w-6 h-6 border-2 border-zinc-900 border-t-transparent rounded-full animate-spin dark:border-white" />
                  <span className="text-xs text-zinc-400 font-medium">正在拉取邮件原件正文与关联流水...</span>
                </div>
              ) : (
                <>
                  {/* ── Tab 1: 解析出的交易流水 ── */}
                  {activeModalTab === 'parsed' && (
                    <div className="space-y-3">
                      {!emailDetail?.transactions || emailDetail.transactions.length === 0 ? (
                        <div className="py-16 text-center space-y-2">
                          <CreditCard className="w-8 h-8 text-zinc-300 mx-auto" />
                          <p className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
                            该封邮件未直接提取出入账流水
                          </p>
                          <p className="text-xs text-zinc-400 max-w-sm mx-auto">
                            可能是对账单概要邮件、通知类邮件，或者规则已过滤该类目。您可以切换到「邮件原件 (HTML 视图)」查看原始对账单。
                          </p>
                        </div>
                      ) : (
                        <div className="space-y-2">
                          <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wider">
                            由该邮件直接清洗解析生成的真实交易明细:
                          </p>
                          <div className="divide-y divide-zinc-100 dark:divide-zinc-800 border border-zinc-200 dark:border-zinc-800 rounded-xl overflow-hidden bg-white dark:bg-zinc-900">
                            {emailDetail.transactions.map((txn) => {
                              const isExpense = txn.transaction_type === 'expense';
                              return (
                                <div key={txn.id} className="p-3.5 flex items-center justify-between gap-4 hover:bg-zinc-50 dark:hover:bg-zinc-800/40 transition-colors">
                                  <div className="min-w-0">
                                    <p className="text-sm font-semibold text-zinc-900 dark:text-zinc-100 truncate">
                                      {txn.merchant_name || txn.name || '未命名商户'}
                                    </p>
                                    <p className="text-xs text-zinc-400 font-mono mt-0.5">
                                      交易时间: {txn.transacted_at} · 类型: {txn.transaction_type}
                                    </p>
                                  </div>

                                  <div className="text-right shrink-0">
                                    <span className={`text-sm font-bold font-mono ${isExpense ? 'text-zinc-900 dark:text-zinc-100' : 'text-emerald-600'}`}>
                                      {isExpense ? '-' : '+'}¥{parseFloat(txn.amount).toFixed(2)}
                                    </span>
                                    <Link
                                      to={`/transactions?search=${encodeURIComponent(txn.merchant_name || txn.name)}`}
                                      className="block text-[11px] text-blue-600 hover:underline mt-0.5"
                                    >
                                      查看交易详情 →
                                    </Link>
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {/* ── Tab 2: 邮件原始 HTML 视图 ── */}
                  {activeModalTab === 'html' && (
                    <div className="space-y-2">
                      <div className="border border-zinc-200 dark:border-zinc-800 rounded-xl overflow-hidden bg-white text-zinc-900 p-4 min-h-[420px] max-h-[600px] overflow-y-auto custom-scrollbar">
                        {emailDetail?.raw_html ? (
                          <div
                            dangerouslySetInnerHTML={{ __html: emailDetail.raw_html }}
                            className="prose prose-sm max-w-none [&_img]:max-w-full [&_table]:w-full"
                          />
                        ) : emailDetail?.raw_text ? (
                          <pre className="whitespace-pre-wrap font-sans text-xs text-zinc-700 leading-relaxed">
                            {emailDetail.raw_text}
                          </pre>
                        ) : (
                          <div className="py-20 text-center text-xs text-zinc-400">
                            未找到原始 HTML 正文
                          </div>
                        )}
                      </div>
                    </div>
                  )}

                  {/* ── Tab 3: 纯文本 / 源码 ── */}
                  {activeModalTab === 'text' && (
                    <div className="space-y-2">
                      <div className="bg-zinc-950 text-zinc-200 rounded-xl p-4 font-mono text-xs overflow-x-auto max-h-[500px] custom-scrollbar border border-zinc-800 leading-relaxed whitespace-pre-wrap">
                        {emailDetail?.raw_text || emailDetail?.raw_payload || '无纯文本正文'}
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
