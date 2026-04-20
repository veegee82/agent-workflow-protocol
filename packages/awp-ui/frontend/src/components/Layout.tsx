import React, { useState, useRef, useEffect, useCallback } from 'react';
import { clsx } from 'clsx';
import { X, ChevronDown, ChevronRight } from 'lucide-react';

// ---------------------------------------------------------------------------
// Panel
// ---------------------------------------------------------------------------

interface PanelProps {
  title: React.ReactNode;
  /** Whether the panel body is visible. Controlled externally when provided. */
  collapsed?: boolean;
  /** Called when the user toggles the panel. */
  onToggle?: () => void;
  /** If true the panel starts expanded (uncontrolled mode). */
  defaultOpen?: boolean;
  /** Optional icon rendered before the title. */
  icon?: React.ReactNode;
  /** Extra class names on the outer wrapper. */
  className?: string;
  /** Optional actions rendered in the header bar. */
  headerActions?: React.ReactNode;
  children: React.ReactNode;
}

export function Panel({
  title,
  collapsed: controlledCollapsed,
  onToggle,
  defaultOpen = true,
  icon,
  className,
  headerActions,
  children,
}: PanelProps) {
  const [internalCollapsed, setInternalCollapsed] = useState(!defaultOpen);
  const collapsed = controlledCollapsed ?? internalCollapsed;
  const toggle = onToggle ?? (() => setInternalCollapsed((c) => !c));

  return (
    <div
      className={clsx(
        'rounded-lg border border-awp-border bg-awp-panel overflow-hidden',
        className,
      )}
    >
      <button
        type="button"
        onClick={toggle}
        className="flex w-full items-center gap-2 px-3 py-2 text-sm font-medium text-awp-text hover:bg-awp-bg/50 transition-colors"
      >
        {collapsed ? (
          <ChevronRight className="h-4 w-4 text-awp-muted shrink-0" />
        ) : (
          <ChevronDown className="h-4 w-4 text-awp-muted shrink-0" />
        )}
        {icon && <span className="shrink-0">{icon}</span>}
        <span className="truncate">{title}</span>
        {headerActions && (
          <span
            className="ml-auto flex items-center gap-1"
            onClick={(e) => e.stopPropagation()}
          >
            {headerActions}
          </span>
        )}
      </button>
      {!collapsed && <div className="px-3 pb-3">{children}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// TabBar
// ---------------------------------------------------------------------------

interface Tab {
  id: string;
  label: string;
  icon?: React.ReactNode;
}

interface TabBarProps {
  tabs: Tab[];
  /** Active tab ID. */
  activeId?: string;
  /** Alias for activeId (backward compat). */
  activeTab?: string;
  /** Called when a tab is selected. */
  onChange?: (id: string) => void;
  /** Alias for onChange (backward compat). */
  onTabChange?: (id: string) => void;
  className?: string;
}

export function TabBar({ tabs, activeId, activeTab, onChange, onTabChange, className }: TabBarProps) {
  const currentId = activeId ?? activeTab ?? '';
  const handleChange = onChange ?? onTabChange ?? (() => {});
  return (
    <div
      className={clsx(
        'flex items-center gap-1 border-b border-awp-border bg-awp-panel px-2',
        className,
      )}
    >
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          onClick={() => handleChange(tab.id)}
          className={clsx(
            'flex items-center gap-1.5 px-3 py-2 text-sm font-medium transition-colors relative',
            tab.id === currentId
              ? 'text-awp-text'
              : 'text-awp-muted hover:text-awp-text',
          )}
        >
          {tab.icon}
          {tab.label}
          {tab.id === currentId && (
            <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-awp-blue rounded-full" />
          )}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Badge
// ---------------------------------------------------------------------------

type BadgeVariant =
  | 'default'
  | 'blue'
  | 'green'
  | 'yellow'
  | 'orange'
  | 'red'
  | 'purple'
  | 'cyan';

const BADGE_CLASSES: Record<BadgeVariant, string> = {
  default: 'bg-awp-border/50 text-awp-muted',
  blue: 'bg-awp-blue/15 text-awp-blue',
  green: 'bg-awp-green/15 text-awp-green',
  yellow: 'bg-awp-yellow/15 text-awp-yellow',
  orange: 'bg-awp-orange/15 text-awp-orange',
  red: 'bg-awp-red/15 text-awp-red',
  purple: 'bg-awp-purple/15 text-awp-purple',
  cyan: 'bg-awp-cyan/15 text-awp-cyan',
};

interface BadgeProps {
  children: React.ReactNode;
  variant?: BadgeVariant;
  /** Show a pulsing dot before the label. */
  dot?: boolean;
  className?: string;
}

export function Badge({
  children,
  variant = 'default',
  dot,
  className,
}: BadgeProps) {
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium',
        BADGE_CLASSES[variant],
        className,
      )}
    >
      {dot && (
        <span
          className={clsx('h-1.5 w-1.5 rounded-full', {
            'bg-awp-blue animate-pulse': variant === 'blue',
            'bg-awp-green': variant === 'green',
            'bg-awp-yellow': variant === 'yellow',
            'bg-awp-orange': variant === 'orange',
            'bg-awp-red': variant === 'red',
            'bg-awp-purple': variant === 'purple',
            'bg-awp-cyan': variant === 'cyan',
            'bg-awp-muted': variant === 'default',
          })}
        />
      )}
      {children}
    </span>
  );
}

// ---------------------------------------------------------------------------
// ProgressBar
// ---------------------------------------------------------------------------

interface ProgressBarProps {
  /** 0 to 1 */
  value: number;
  /** Bar fill color class, e.g. "bg-awp-blue" */
  color?: string;
  /** Show percentage label. */
  showLabel?: boolean;
  className?: string;
}

export function ProgressBar({
  value,
  color = 'bg-awp-blue',
  showLabel = false,
  className,
}: ProgressBarProps) {
  const pct = Math.min(Math.max(value, 0), 1) * 100;
  return (
    <div className={clsx('flex items-center gap-2', className)}>
      <div className="relative h-1.5 flex-1 rounded-full bg-awp-border/50 overflow-hidden">
        <div
          className={clsx(
            'absolute inset-y-0 left-0 rounded-full transition-all duration-500 ease-out',
            color,
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      {showLabel && (
        <span className="text-xs text-awp-muted tabular-nums w-10 text-right">
          {Math.round(pct)}%
        </span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// IconButton
// ---------------------------------------------------------------------------

interface IconButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** Tooltip text shown on hover. */
  tooltip?: string;
  /** Size variant. */
  size?: 'sm' | 'md' | 'lg';
  /** Active / toggled appearance. */
  active?: boolean;
}

export function IconButton({
  tooltip,
  size = 'md',
  active,
  className,
  children,
  ...rest
}: IconButtonProps) {
  const sizeClasses = {
    sm: 'h-7 w-7',
    md: 'h-8 w-8',
    lg: 'h-9 w-9',
  };

  return (
    <Tooltip content={tooltip}>
      <button
        type="button"
        {...rest}
        className={clsx(
          'inline-flex items-center justify-center rounded-md transition-colors',
          'text-awp-muted hover:text-awp-text hover:bg-awp-border/50',
          'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-awp-blue',
          'disabled:opacity-40 disabled:pointer-events-none',
          active && 'bg-awp-border/50 text-awp-text',
          sizeClasses[size],
          className,
        )}
      >
        {children}
      </button>
    </Tooltip>
  );
}

// ---------------------------------------------------------------------------
// Tooltip
// ---------------------------------------------------------------------------

interface TooltipProps {
  content?: string;
  children: React.ReactNode;
  side?: 'top' | 'bottom' | 'left' | 'right';
}

export function Tooltip({
  content,
  children,
  side = 'bottom',
}: TooltipProps) {
  const [visible, setVisible] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const show = useCallback(() => {
    timerRef.current = setTimeout(() => setVisible(true), 400);
  }, []);

  const hide = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    setVisible(false);
  }, []);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  if (!content) {
    return <>{children}</>;
  }

  const positionClasses: Record<string, string> = {
    top: 'bottom-full left-1/2 -translate-x-1/2 mb-2',
    bottom: 'top-full left-1/2 -translate-x-1/2 mt-2',
    left: 'right-full top-1/2 -translate-y-1/2 mr-2',
    right: 'left-full top-1/2 -translate-y-1/2 ml-2',
  };

  return (
    <div
      ref={ref}
      className="relative inline-flex"
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
    >
      {children}
      {visible && (
        <div
          role="tooltip"
          className={clsx(
            'absolute z-50 whitespace-nowrap rounded-md px-2 py-1 text-xs font-medium',
            'bg-awp-text text-awp-bg shadow-lg',
            'animate-fade-in pointer-events-none',
            positionClasses[side],
          )}
        >
          {content}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Modal
// ---------------------------------------------------------------------------

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  className?: string;
  children: React.ReactNode;
}

export function Modal({ open, onClose, title, className, children }: ModalProps) {
  const overlayRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      ref={overlayRef}
      className="fixed inset-0 z-50 flex items-center justify-center"
      onClick={(e) => {
        if (e.target === overlayRef.current) onClose();
      }}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm animate-fade-in" />
      {/* Content */}
      <div
        className={clsx(
          'relative z-10 w-full max-w-lg rounded-xl border border-awp-border',
          'bg-awp-panel shadow-2xl animate-fade-in',
          className,
        )}
      >
        {title && (
          <div className="flex items-center justify-between border-b border-awp-border px-5 py-3">
            <h2 className="text-sm font-semibold text-awp-text">{title}</h2>
            <button
              type="button"
              onClick={onClose}
              className="text-awp-muted hover:text-awp-text transition-colors"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        )}
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Drawer
// ---------------------------------------------------------------------------

interface DrawerProps {
  open: boolean;
  onClose: () => void;
  /** Which side the drawer slides in from. */
  side?: 'left' | 'right';
  title?: string;
  /** Width class, e.g. "w-80". */
  width?: string;
  children: React.ReactNode;
}

export function Drawer({
  open,
  onClose,
  side = 'right',
  title,
  width = 'w-80',
  children,
}: DrawerProps) {
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  return (
    <>
      {/* Backdrop */}
      {open && (
        <div
          className="fixed inset-0 z-40 bg-black/40 animate-fade-in"
          onClick={onClose}
        />
      )}
      {/* Drawer panel */}
      <div
        className={clsx(
          'fixed top-0 z-50 h-full border-awp-border bg-awp-panel shadow-2xl transition-transform duration-300 ease-out',
          width,
          side === 'right'
            ? 'right-0 border-l'
            : 'left-0 border-r',
          open
            ? 'translate-x-0'
            : side === 'right'
              ? 'translate-x-full'
              : '-translate-x-full',
        )}
      >
        {title && (
          <div className="flex items-center justify-between border-b border-awp-border px-4 py-3">
            <h2 className="text-sm font-semibold text-awp-text">{title}</h2>
            <button
              type="button"
              onClick={onClose}
              className="text-awp-muted hover:text-awp-text transition-colors"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        )}
        <div className="h-full overflow-y-auto p-4">{children}</div>
      </div>
    </>
  );
}
