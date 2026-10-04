import { useCallback, useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

// Keep the drawer in router history so browser Back closes it, while Forward
// can reopen it. The page URL, filters and list component remain unchanged.
export default function useTransactionDrawer() {
  const location = useLocation();
  const navigate = useNavigate();
  const locationRef = useRef(location);
  const closingRef = useRef(false);
  locationRef.current = location;

  useEffect(() => {
    closingRef.current = false;
  }, [location.key]);

  const setTransactionId = useCallback((id) => {
    const current = locationRef.current;
    const drawer = current.state?.transactionDrawer;
    if (!id) {
      if (!drawer || closingRef.current) return;
      closingRef.current = true;
      if (drawer.backgroundKey) {
        navigate(-1);
      } else {
        const state = { ...current.state };
        delete state.transactionDrawer;
        navigate(`${current.pathname}${current.search}${current.hash}`, { replace: true, state });
      }
      return;
    }

    navigate(`${current.pathname}${current.search}${current.hash}`, {
      replace: Boolean(drawer),
      state: {
        ...current.state,
        transactionDrawer: { id, backgroundKey: drawer?.backgroundKey || current.key },
      },
    });
  }, [navigate]);

  return [location.state?.transactionDrawer?.id || null, setTransactionId];
}
