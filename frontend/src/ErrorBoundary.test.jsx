import i18n from './i18n';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ErrorBoundary, { isChunkLoadError } from './ErrorBoundary';

afterEach(() => vi.unstubAllGlobals());

beforeEach(() => i18n.changeLanguage('zh'));

describe('failed lazy report route recovery', () => {
  it('recognizes network chunk errors without treating component bugs as stale files', () => {
    expect(isChunkLoadError(new Error('Failed to fetch dynamically imported module: /Analytics.jsx'))).toBe(true);
    expect(isChunkLoadError(new Error('Importing a module script failed.'))).toBe(true);
    expect(isChunkLoadError(new Error('Cannot read properties of undefined'))).toBe(false);
  });
  it('reloads the document instead of retrying a permanently rejected React.lazy promise', () => {
    const reload = vi.fn();
    vi.stubGlobal('window', {location:{reload}});
    const boundary = new ErrorBoundary({});
    boundary.state = {error:new Error('Failed to fetch dynamically imported module: /Analytics.jsx')};
    const button = boundary.render().props.children.find(child => child.type === 'button');
    expect(button.props.children).toBe('刷新页面');
    button.props.onClick();
    expect(reload).toHaveBeenCalledOnce();
  });
});
