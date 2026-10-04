/**
 * 报销与朋友代垫工具函数库
 * 规范化处理往来对象名称解析与英文状态中文映射，杜绝 [object Object] 与 pending
 */

export const REIMBURSEMENT_STATUS_MAP = {
  pending: '审批中',
  unclaimed: '待申报',
  claimed: '审批中',
  approving: '审批中',
  approved: '已批准',
  settled: '已打款',
  paid: '已结清',
  rejected: '已驳回',
  '待还款': '待还款',
  '部分已还': '部分已还',
  '已结清': '已结清',
  '未提报': '未提报',
  '审批中': '审批中',
  '已打款': '已打款',
};

/**
 * 安全解析往来对象名称 (防止对象类型导致 [object Object])
 */
export function resolveCounterpartyName(cp, fallback = '') {
  if (!cp) return fallback;
  if (typeof cp === 'string') {
    const trimmed = cp.trim();
    return trimmed || fallback;
  }
  if (typeof cp === 'object' && cp !== null) {
    return cp.name || cp.title || cp.label || cp.value || fallback;
  }
  return String(cp);
}

/**
 * 格式化报销或还款状态为自然中文
 */
export function formatReimbursementStatus(status, isCorporate = true) {
  if (!status) {
    return isCorporate ? '审批中' : '待还款';
  }
  return REIMBURSEMENT_STATUS_MAP[status] || status;
}

/**
 * 提取交易的报销完整摘要对象
 */
export function getReimbursementSummary(txn) {
  if (!txn) {
    return {
      isReimbursable: false,
      reimbursementType: 'corporate',
      isCorporate: true,
      counterparty: '公司',
      status: '审批中',
      isSettled: false,
      badgeText: '',
    };
  }

  const isReimbursable = Boolean(txn.is_reimbursable || txn.extra?.reimbursement_type);
  const reimbursementType =
    txn.extra?.reimbursement_type ||
    ((txn.narration || '').includes('航空') || (txn.narration || '').includes('商务') ? 'corporate' : 'personal_advance');
  const isCorporate = reimbursementType === 'corporate';

  const rawCp = txn.counterparty || txn.extra?.counterparty;
  const counterparty = resolveCounterpartyName(rawCp, isCorporate ? '公司' : '张三');

  const rawStatus = txn.reimbursement_status || (isCorporate ? '审批中' : '待还款');
  const status = formatReimbursementStatus(rawStatus, isCorporate);
  const isSettled = status === '已打款' || status === '已结清';

  const badgePrefix = isCorporate ? `待报销·${counterparty}` : `待收回·${counterparty}`;
  const badgeText = `${badgePrefix} · ${status}`;

  return {
    isReimbursable,
    reimbursementType,
    isCorporate,
    counterparty,
    status,
    isSettled,
    badgeText,
    badgePrefix,
  };
}
