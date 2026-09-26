import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
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
} from 'lucide-react';
import { Button, Card, Pill, Modal } from '../components/ds/DesignSystem';
import { fetchWithAuth } from '../api/fetchWithAuth';

export default function EmailsPage() {
  const { t } = useTranslation();
  const [emails, setEmails] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedEmail, setSelectedEmail] = useState(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [filterStatus, setFilterStatus] = useState('all');

  const fetchEmails = async () => {
    try {
      setLoading(true);
      const res = await fetchWithAuth('/api/v1/imports/emails');
      if (res.ok) {
        const data = await res.json();
        setEmails(data);
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

  const filteredEmails = emails.filter((m) => {
    if (filterStatus === 'all') return true;
    return m.status === filterStatus;
  });

  const parsedTotal = emails.reduce((sum, m) => sum + (m.parsed_count || 0), 0);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-on-surface">
            {t('emails.title')}
          </h1>
          <p className="text-sm text-on-surface-variant mt-1">
            {t('emails.subtitle')}
          </p>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Card className="flex items-center gap-4">
          <div className="p-3 rounded-xl bg-primary/10 text-primary">
            <Mail className="w-6 h-6" />
          </div>
          <div>
            <span className="text-xs text-on-surface-variant block font-medium">已归档原始邮件</span>
            <span className="text-2xl font-bold font-mono text-on-surface">{emails.length} 封</span>
          </div>
        </Card>

        <Card className="flex items-center gap-4">
          <div className="p-3 rounded-xl bg-emerald-500/10 text-emerald-600">
            <CheckCircle2 className="w-6 h-6" />
          </div>
          <div>
            <span className="text-xs text-on-surface-variant block font-medium">已解析入库交易</span>
            <span className="text-2xl font-bold font-mono text-emerald-600">{parsedTotal} 笔</span>
          </div>
        </Card>

        <Card className="flex items-center gap-4">
          <div className="p-3 rounded-xl bg-blue-500/10 text-blue-600">
            <ShieldCheck className="w-6 h-6" />
          </div>
          <div>
            <span className="text-xs text-on-surface-variant block font-medium">防重指纹验证</span>
            <span className="text-2xl font-bold font-mono text-blue-600">SHA-256 100%</span>
          </div>
        </Card>
      </div>

      {/* Filter Tabs */}
      <div className="flex border-b border-outline/15 gap-4">
        {['all', 'parsed', 'pending', 'failed'].map((st) => (
          <button
            key={st}
            onClick={() => setFilterStatus(st)}
            className={`pb-3 text-sm font-semibold border-b-2 transition-colors capitalize ${
              filterStatus === st
                ? 'border-primary text-primary'
                : 'border-transparent text-on-surface-variant hover:text-on-surface'
            }`}
          >
            {st === 'all' ? '全部邮件' : st === 'parsed' ? '已解析' : st === 'pending' ? '待处理' : '失败'}
          </button>
        ))}
      </div>

      {/* List */}
      <div className="space-y-3">
        {loading ? (
          <div className="py-12 flex items-center justify-center">
            <span className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
          </div>
        ) : filteredEmails.length === 0 ? (
          <div className="py-12 text-center text-on-surface-variant">暂无相关邮件记录</div>
        ) : (
          filteredEmails.map((email) => (
            <Card
              key={email.id}
              hoverable
              onClick={() => {
                setSelectedEmail(email);
                setModalOpen(true);
              }}
              className="flex items-center justify-between gap-4"
            >
              <div className="flex items-center gap-4">
                <div className="p-2.5 rounded-lg bg-surface-container text-on-surface-variant">
                  <Mail className="w-5 h-5" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h4 className="font-semibold text-on-surface text-sm sm:text-base">{email.subject}</h4>
                    <Pill
                      label={
                        email.status === 'parsed'
                          ? `已解析 ${email.parsed_count} 笔`
                          : email.status === 'pending'
                          ? '待处理'
                          : '失败'
                      }
                      variant={
                        email.status === 'parsed'
                          ? 'success'
                          : email.status === 'pending'
                          ? 'warning'
                          : 'error'
                      }
                    />
                  </div>
                  <div className="flex items-center gap-4 text-xs text-on-surface-variant mt-1">
                    <span>发件人: {email.sender}</span>
                    <span>接收时间: {new Date(email.received_at).toLocaleString('zh-CN')}</span>
                    <span className="font-mono bg-surface-container px-1.5 py-0.5 rounded text-[11px]">
                      {email.mail_kind}
                    </span>
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-2 text-on-surface-variant">
                <span className="text-xs hidden sm:inline">查看原件</span>
                <ChevronRight className="w-4 h-4" />
              </div>
            </Card>
          ))
        )}
      </div>

      {/* Email Detail Modal */}
      <Modal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        title={selectedEmail?.subject || '邮件原件详情'}
        maxWidth="max-w-4xl"
        footer={
          <Button variant="primary" onClick={() => setModalOpen(false)}>
            关闭
          </Button>
        }
      >
        {selectedEmail && (
          <div className="space-y-4">
            {/* Meta info */}
            <div className="bg-surface-container p-3 rounded-lg text-xs space-y-1.5 font-mono">
              <div className="flex justify-between">
                <span className="text-on-surface-variant">Message ID:</span>
                <span className="text-on-surface font-semibold truncate max-w-lg">{selectedEmail.message_id}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-on-surface-variant">内容指纹 (SHA-256):</span>
                <span className="text-on-surface truncate max-w-lg">{selectedEmail.content_fingerprint}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-on-surface-variant">发件方:</span>
                <span className="text-on-surface">{selectedEmail.sender}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-on-surface-variant">解析状态:</span>
                <span className="text-on-surface font-semibold">{selectedEmail.status} (流水数: {selectedEmail.parsed_count})</span>
              </div>
            </div>

            {/* Email HTML / Text View */}
            <div className="border border-outline/20 rounded-xl p-4 bg-white text-black min-h-[300px] max-h-[500px] overflow-y-auto custom-scrollbar">
              {selectedEmail.raw_html ? (
                <div dangerouslySetInnerHTML={{ __html: selectedEmail.raw_html }} />
              ) : selectedEmail.raw_text ? (
                <pre className="whitespace-pre-wrap font-sans text-sm">{selectedEmail.raw_text}</pre>
              ) : (
                <div className="text-gray-400 text-center py-12">未保存原始文本内容</div>
              )}
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
