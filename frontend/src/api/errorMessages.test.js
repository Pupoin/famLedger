import { beforeEach, describe, expect, it } from 'vitest';
import i18n from '../i18n';
import { apiErrorMessage, readJsonResponse } from './errorMessages';

beforeEach(() => i18n.changeLanguage('zh'));

describe('financial input validation messages', () => {
  it('shows ordinary backend explanations', () => expect(apiErrorMessage('原币金额必须大于零')).toBe('原币金额必须大于零'));
  it('renders validation arrays as text without original inputs', async () => {
    await i18n.changeLanguage('en');
    const result=apiErrorMessage([{loc:['body','settlement_amount'],msg:'Input should be greater than 0',input:'private payload'}]);
    expect(result).toBe('settlement_amount: Input should be greater than 0');
    expect(result).not.toContain('private payload');
  });
  it('handles unknown response shapes', () => expect(apiErrorMessage({unexpected:true},'金额输入有误')).toBe('金额输入有误'));
  it.each([
    ['final_payment_day','最后一期还款日只需填写1–31的整数，年月由计划确定。'],
    ['final_payment_date','最后一期还款日期请填写有效的年月日。'],
  ])('explains %s validation without repeating the submitted date', (field, message) => {
    const result = apiErrorMessage([{loc:['body','loan',field],msg:'Extra inputs are not permitted',input:'2024-12-20'}]);
    expect(result).toBe(message);
    expect(result).not.toContain('2024-12-20');
  });
});

describe('API responses that may contain plain server errors', () => {
  it('keeps successful plan JSON unchanged', async () => {
    const body={occurrences:[{due_date:'2024-03-20',total:'1207.74'}]};
    expect(await readJsonResponse(new Response(JSON.stringify(body),{status:200}))).toEqual(body);
  });
  it.each([500,502,503])('reports HTTP %s instead of throwing a JSON parser error', async status => {
    const response=new Response('Internal Server Error',{status,headers:{'Content-Type':'text/plain'}});
    await expect(readJsonResponse(response)).rejects.toThrow(`请求失败（HTTP ${status}），请稍后重试。`);
  });
  it('does not display a proxy HTML error body', async () => {
    const response=new Response('<html><h1>Private upstream diagnostic</h1></html>',{status:502});
    await expect(readJsonResponse(response)).rejects.toThrow('请求失败（HTTP 502），请稍后重试。');
  });
  it('reports an invalid successful response', async () => {
    await expect(readJsonResponse(new Response('not JSON',{status:200}))).rejects.toThrow('服务器响应格式不正确，请刷新后重试。');
  });
  it('preserves the backend error explanation', async () => {
    const response=new Response(JSON.stringify({detail:'最后一期还款日期必须晚于已发生的还款日期'}),{status:422});
    await expect(readJsonResponse(response)).rejects.toThrow('最后一期还款日期必须晚于已发生的还款日期');
  });
  it('shows a clear calendar-date validation message', async () => {
    const response=new Response(JSON.stringify({detail:[{loc:['body','loan','final_payment_date'],msg:'Extra inputs are not permitted',input:'2024-12-20'}]}),{status:422});
    await expect(readJsonResponse(response)).rejects.toThrow('最后一期还款日期请填写有效的年月日。');
  });
  it('keeps the server status when JSON does not contain an explanation', async () => {
    await expect(readJsonResponse(new Response('{}',{status:500}),'请检查计划设置')).rejects.toThrow('请求失败（HTTP 500），请稍后重试。');
  });
  it('explains the server failure and date format in English', async () => {
    await i18n.changeLanguage('en');
    await expect(readJsonResponse(new Response('Internal Server Error',{status:500}))).rejects.toThrow(
      'Request failed (HTTP 500). Please try again later.');
    expect(apiErrorMessage([{loc:['body','loan','final_payment_date'],msg:'Extra inputs are not permitted'}])).toBe(
      'Enter a valid year, month and day for the final payment date.');
  });
});
