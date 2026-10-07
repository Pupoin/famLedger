// One active request per mounted page. Refreshes replace it; pagination waits.
export function createLatestRequest() {
  let active = null;
  return {
    start({ replace = false } = {}) {
      if (active && !replace) return null;
      active?.controller.abort();
      const controller = new AbortController();
      const request = {
        controller,
        signal: controller.signal,
        isCurrent: () => active === request && !controller.signal.aborted,
        finish() { if (active === request) active = null; },
      };
      active = request;
      return request;
    },
    cancel() {
      active?.controller.abort();
      active = null;
    },
  };
}
