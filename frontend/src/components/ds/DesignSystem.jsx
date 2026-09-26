import React from 'react';
import clsx from 'clsx';

export function Button({
  children,
  variant = 'primary', // primary | secondary | tertiary | destructive | outline
  size = 'md', // sm | md | lg
  icon: Icon,
  className = '',
  disabled = false,
  loading = false,
  onClick,
  type = 'button',
  ...props
}) {
  const baseStyles = 'inline-flex items-center justify-center font-medium transition-all duration-200 focus-ring disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer select-none';

  const sizeStyles = {
    sm: 'text-xs px-2.5 py-1.5 rounded gap-1.5',
    md: 'text-sm px-3.5 py-2 rounded-md gap-2',
    lg: 'text-base px-5 py-2.5 rounded-lg gap-2.5',
  };

  const variantStyles = {
    primary: 'bg-primary text-white hover:opacity-90 shadow-sm active:scale-[0.98]',
    secondary: 'bg-surface-container hover:bg-surface-container-high text-on-surface border border-outline/20 active:scale-[0.98]',
    tertiary: 'bg-transparent hover:bg-surface-container/60 text-on-surface active:scale-[0.98]',
    destructive: 'bg-red-600 text-white hover:bg-red-700 shadow-sm active:scale-[0.98]',
    outline: 'border border-outline/30 hover:border-outline text-on-surface bg-transparent active:scale-[0.98]',
  };

  return (
    <button
      type={type}
      disabled={disabled || loading}
      onClick={onClick}
      className={clsx(baseStyles, sizeStyles[size], variantStyles[variant], className)}
      {...props}
    >
      {loading ? (
        <span className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
      ) : Icon ? (
        <Icon className={clsx(size === 'sm' ? 'w-3.5 h-3.5' : size === 'lg' ? 'w-5 h-5' : 'w-4 h-4')} />
      ) : null}
      {children}
    </button>
  );
}

export function Card({
  children,
  className = '',
  hoverable = false,
  onClick,
  ...props
}) {
  return (
    <div
      onClick={onClick}
      className={clsx(
        'bg-surface-container-lowest border border-outline/15 rounded-xl p-5 shadow-sm transition-all duration-200',
        hoverable && 'hover:shadow-md hover:border-outline/30 cursor-pointer',
        className
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export function Pill({
  label,
  variant = 'default', // default | success | warning | error | info
  icon: Icon,
  onRemove,
  className = '',
}) {
  const styles = {
    default: 'bg-surface-container text-on-surface border-outline/20',
    success: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20',
    warning: 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20',
    error: 'bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/20',
    info: 'bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/20',
    purple: 'bg-purple-500/10 text-purple-600 dark:text-purple-400 border-purple-500/20',
  };

  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium border',
        styles[variant] || styles.default,
        className
      )}
    >
      {Icon && <Icon className="w-3 h-3" />}
      <span>{label}</span>
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          className="hover:opacity-75 focus:outline-none ml-0.5"
        >
          ×
        </button>
      )}
    </span>
  );
}

export function Drawer({
  isOpen,
  onClose,
  title,
  subtitle,
  children,
  footer,
  width = 'max-w-2xl',
}) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 overflow-hidden">
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-xs transition-opacity"
        onClick={onClose}
      />
      <div className="fixed inset-y-0 right-0 flex pl-10 max-w-full">
        <div className={clsx('w-screen bg-surface-container-lowest shadow-2xl flex flex-col', width)}>
          {/* Header */}
          <div className="px-6 py-5 border-b border-outline/15 flex items-center justify-between">
            <div>
              <h3 className="text-lg font-semibold text-on-surface">{title}</h3>
              {subtitle && <p className="text-xs text-on-surface-variant mt-0.5">{subtitle}</p>}
            </div>
            <button
              type="button"
              onClick={onClose}
              className="p-1 rounded-md text-on-surface-variant hover:text-on-surface hover:bg-surface-container focus-ring"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          {/* Body */}
          <div className="flex-1 overflow-y-auto px-6 py-6 custom-scrollbar">
            {children}
          </div>

          {/* Footer */}
          {footer && (
            <div className="px-6 py-4 border-t border-outline/15 bg-surface-container/30 flex items-center justify-end gap-3">
              {footer}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function Modal({
  isOpen,
  onClose,
  title,
  children,
  footer,
  maxWidth = 'max-w-xl',
}) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto flex items-center justify-center p-4">
      <div
        className="fixed inset-0 bg-black/50 backdrop-blur-xs transition-opacity"
        onClick={onClose}
      />
      <div className={clsx('relative bg-surface-container-lowest rounded-2xl shadow-xl w-full border border-outline/20 overflow-hidden', maxWidth)}>
        <div className="px-6 py-5 border-b border-outline/15 flex items-center justify-between">
          <h3 className="text-lg font-semibold text-on-surface">{title}</h3>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded-md text-on-surface-variant hover:text-on-surface hover:bg-surface-container focus-ring"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="px-6 py-6 max-h-[75vh] overflow-y-auto custom-scrollbar">
          {children}
        </div>
        {footer && (
          <div className="px-6 py-4 border-t border-outline/15 bg-surface-container/30 flex items-center justify-end gap-3">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}
