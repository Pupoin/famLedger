import { useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { tx } from '../localization';

export function useSettingsShortcuts() {
  const location = useLocation();
  const navigate = useNavigate();
  const returnLocation = useRef(location.state?.settingsReturnTo || null);
  useEffect(() => {
    if (location.pathname !== '/settings') {
      returnLocation.current = {
        pathname: location.pathname, search: location.search, hash: location.hash,
        index: window.history.state?.idx,
      };
    }
  }, [location]);
  useEffect(() => {
    const handler = event => {
      if (event.defaultPrevented || event.repeat || event.isComposing) return;
      const modal = [...document.querySelectorAll('[aria-modal="true"], [role="dialog"], [role="listbox"], [data-settings-modal]')]
        .filter(element => element.getClientRects().length).at(-1);
      if ((event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey && (event.key === ',' || event.code === 'Comma')) {
        event.preventDefault();
        if (!modal && location.pathname !== '/settings') {
          navigate('/settings', { state: { settingsReturnTo: returnLocation.current } });
        }
      } else if (event.key === 'Escape' && location.pathname === '/settings') {
        if (modal) {
          const close = modal.querySelector('button:has(svg.lucide-x)')
            || [...modal.querySelectorAll('button')].find(button => button.textContent.trim() === tx('取消'));
          if (close && !close.disabled) close.click();
          event.preventDefault();
          return;
        }
        event.preventDefault();
        const previous = returnLocation.current;
        const distance = window.history.state?.idx - previous?.index;
        if (previous && Number.isInteger(distance) && distance > 0) navigate(-distance);
        else navigate(previous ? { pathname: previous.pathname, search: previous.search, hash: previous.hash } : '/', { replace: true });
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [location.pathname, navigate]);
}
