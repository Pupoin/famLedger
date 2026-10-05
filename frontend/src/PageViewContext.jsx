import React, {
  createContext, useCallback, useContext, useEffect, useLayoutEffect,
  useRef, useState, useSyncExternalStore,
} from 'react';
import { useLocation } from 'react-router-dom';
import { createPageViewStore } from './utils/pageViewStore';

const PageViewContext = createContext(null);
const useBrowserLayoutEffect = typeof window === 'undefined' ? useEffect : useLayoutEffect;
const sectionSelector = '[data-view-section]';

export function PageViewProvider({ children }) {
  const location = useLocation();
  const [store] = useState(createPageViewStore);
  const previousPath = useRef(location.pathname);

  useBrowserLayoutEffect(() => {
    if (previousPath.current !== location.pathname) window.scrollTo(0, 0);
    previousPath.current = location.pathname;
  }, [location.pathname]);

  return (
    <PageViewContext.Provider value={{ store, entryKey: `${location.pathname}:${location.key}` }}>
      {children}
    </PageViewContext.Provider>
  );
}

// Keep only controls here; financial data is fetched again when a page returns.
export function usePageViewState(name, initialValue) {
  const context = useContext(PageViewContext);
  const [localValue, setLocalValue] = useState(initialValue);
  const getSnapshot = useCallback(
    () => context ? context.store.get(context.entryKey, name, initialValue) : localValue,
    [context?.store, context?.entryKey, name, initialValue, localValue],
  );
  const subscribe = useCallback(
    (listener) => context ? context.store.subscribe(listener) : () => {},
    [context?.store],
  );
  const value = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  const setValue = useCallback((next) => {
    if (context) context.store.set(context.entryKey, name, next);
    else setLocalValue(next);
  }, [context?.store, context?.entryKey, name]);
  return [value, setValue];
}

export function usePageScrollRestoration(ready) {
  const context = useContext(PageViewContext);

  useBrowserLayoutEffect(() => {
    if (!context || !ready) return;
    const { store, entryKey } = context;
    const saved = store.getScroll(entryKey);
    let active = false;
    let frame;

    const remember = (event) => {
      if (!active) return;
      const sections = [...document.querySelectorAll(sectionSelector)];
      const clicked = event?.target instanceof Element ? event.target.closest(sectionSelector) : null;
      const section = clicked || sections.find((element) => {
        const rect = element.getBoundingClientRect();
        return rect.bottom > 100 && rect.top < window.innerHeight;
      });
      store.setScroll(entryKey, {
        x: window.scrollX, y: window.scrollY,
        section: section?.dataset.viewSection,
        top: section?.getBoundingClientRect().top,
      });
    };

    // Loading placeholders are much shorter than the charts. Restore after the
    // actual page has laid out, then listen for scrolling and chart drilldowns.
    frame = window.requestAnimationFrame(() => {
      const section = saved?.section && [...document.querySelectorAll(sectionSelector)]
        .find((element) => element.dataset.viewSection === saved.section);
      const y = section ? window.scrollY + section.getBoundingClientRect().top - saved.top : saved?.y || 0;
      window.scrollTo({ left: saved?.x || 0, top: y, behavior: 'instant' });
      frame = window.requestAnimationFrame(() => {
        active = true;
        remember();
        window.addEventListener('scroll', remember, { passive: true });
        document.addEventListener('click', remember, true);
      });
    });

    return () => {
      active = false;
      window.cancelAnimationFrame(frame);
      window.removeEventListener('scroll', remember);
      document.removeEventListener('click', remember, true);
    };
  }, [context?.store, context?.entryKey, ready]);
}
