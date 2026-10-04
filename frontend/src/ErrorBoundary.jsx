import { tx } from "./localization.js";
import { Component } from "react";
import i18n from './i18n';

export function isChunkLoadError(error) {
  return error?.name === "ChunkLoadError" || /Failed to fetch dynamically imported module|error loading dynamically imported module|Importing a module script failed|Loading chunk .* failed/i.test(error?.message || "");
}

export default class ErrorBoundary extends Component {
  state = { error: null };

  refreshLanguage = () => this.forceUpdate();

  componentDidMount() {
    i18n.on('languageChanged', this.refreshLanguage);
  }

  componentWillUnmount() {
    i18n.off('languageChanged', this.refreshLanguage);
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      const chunkError = isChunkLoadError(this.state.error);
      return (
        <div className="flex flex-col items-center justify-center h-64 text-error">
          <p className="font-bold mb-2">{chunkError ? tx("页面资源加载失败") : tx("页面加载失败")}</p>
          <p className="text-sm text-on-surface-variant mb-4">
            {chunkError ? tx("请刷新页面以加载最新资源。") : this.state.error.message}
          </p>
          <button
            onClick={() => chunkError ? window.location.reload() : this.setState({ error: null })}
            className="px-4 py-2 rounded-full bg-primary text-on-primary font-bold text-sm hover:shadow-lg transition-all"
          >
            {chunkError ? tx("刷新页面") : tx("重试")}
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
