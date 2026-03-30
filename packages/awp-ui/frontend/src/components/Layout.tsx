import React, { useState, useRef, useEffect, useCallback } from 'react';
import { clsx } from 'clsx';
import {
  ChevronDown,
  ChevronRight,
  X,
} from 'lucide-react';

// ---------------------------------------------------------------------------
// Panel -- collapsible section with a header
// ---------------------------------------------------------------------------

interface PanelProps {
  title: string;
  icon?: React.ReactNode;
  defaultOpen?: boolean;
  className?: string;
  headerRight?: React.ReactNode;
  children: React.ReactNode;
}

export function Panel({
  title,
  icon,
  defaultOpen = true,
  className,
  headerRight,
  children,
}: PanelProps) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div
      className={clsx(
        'rounded-xl border border-awp-border bg-awp-panel/60 backdrop-blur-sm overflow-hidden transition-all duration-200',
        className,
      )}
    >
      <button
        type="button"
        className="flex w-full items-center gap-2 px-4 py-3 text-sm font-medium text-awp-text hover:bg-awp-bg/40 transition-colors"
        onClick={() => setOpen((v) => !v)}
      >
        {open ? (
          <ChevronDown className="h-4 w-4 text-awp-muted shrink-0" />
        ) : (
          <ChevronRight className="h-4 w-4 text-awp-muted shrink-0" />
        )}
        {icon && <span className="shrink-0">{icon}</span>}
        <span className="truncate">{title}</span>
        {headerRight && (
          <span className="ml-auto shrink-0">{headerRight}</span>
        )}
      </button>

      {open && (
        <div className="px-4 pb-4 animate-fade-in">{children}</div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// TabBar -- horizontal tab navigation
// ---------------------------------------------------------------------------

interface Tab {
  id: string;
  label: string;
  icon?: React.ReactNode;
  badge?: string | number;
}

interface TabBarProps {
  tabs: Tab[];
  activeTab: string;
  onTabChange: (id: string) => void;
  className?: string;
}

export function TabBar({ tabs, activeTab, onTabChange, className }: TabBarProps) {
  return (
    <div
      className={clsx(
        'flex items-center gap-1 border-b border-awp-border px-2',
        className,
      )}
    >
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          className={clsx(
            'relative flex items-center gap-1.5 px-3 py-2 text-sm font-medium transition-colors',
            activeTab === tab.id
              ? 'text-awp-blue'
              : 'text-awp-muted hover:text-awp-text',
          )}
          onClick={() => onTabChange(tab.id)}
        >
          {tab.icon}
          {tab.label}
          {tab.badge !== undefined && (
            <span className="ml-1 rounded-full bg-awp-blue/20 px-1.5 py-0.5 text-[10px] font-semibold text-awp-blue">
              {tab.badge}
            </span>
          )}
          {activeTab === tab.id && (
            <span className="absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-awp-blue" />
          )}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Badge -- status indicator
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

const badgeColors: Record<BadgeVariant, string> = {
  default: 'bg-awp-muted/20 text-awp-muted border-awp-muted/30',
  blue: 'bg-awp-blue/15 text-awp-blue border-awp-blue/30',
  green: 'bg-awp-green/15 text-awp-green border-awp-green/30',
  yellow: 'bg-awp-yellow/15 text-awp-yellow border-awp-yellow/30',
  orange: 'bg-awp-orange/15 text-awp-orange border-awp-orange/30',
  red: 'bg-awp-red/15 text-awp-red border-awp-red/30',
  purple: 'bg-awp-purple/15 text-awp-purple border-awp-purple/30',
  cyan: 'bg-awp-cyan/15 text-awp-cyan border-awp-cyan/30',
};

interface BadgeProps {
  variant?: BadgeVariant;
  dot?: boolean;
  pulse?: boolean;
  children: React.ReactNode;
  className?: string;
}

export function Badge({
  variant = 'default',
  dot,
  pulse,
  children,
  className,
}: BadgeProps) {
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium',
        badgeColors[variant],
        className,
      )}
    >
      {dot && (
        <span className="relative flex h-2 w-2">
          {pulse && (
            <span
              className={clsx(
                'absolute inline-flex h-full w-full animate-ping rounded-full opacity-75',
                variant === 'blue' && 'bg-awp-blue',
                variant === 'green' && 'bg-awp-green',
                variant === 'red' && 'bg-awp-red',
                variant === 'yellow' && 'bg-awp-yellow',
                variant === 'orange' && 'bg-awp-orange',
                variant === 'purple' && 'bg-awp-purple',
                variant === 'cyan' && 'bg-awp-cyan',
                variant === 'default' && 'bg-awp-muted',
              )}
            />
          )}
          <span
            className={clsx(
              'relative inline-flex h-2 w-2 rounded-full',
              variant === 'blue' && 'bg-awp-blue',
              variant === 'green' && 'bg-awp-green',
              variant === 'red' && 'bg-awp-red',
              variant === 'yellow' && 'bg-awp-yellow',
              variant === 'orange' && 'bg-awp-orange',
              variant === 'purple' && 'bg-awp-purple',
              variant === 'cyan' && 'bg-awp-cyan',
              variant === 'default' && 'bg-awp-muted',
            )}
          />
        </span>
      )}
      {children}
    </span>
  );
}

// ---------------------------------------------------------------------------
// ProgressBar -- animated horizontal progress indicator
// ---------------------------------------------------------------------------

interface ProgressBarProps {
  /** 0-100 */
  value: number;
  max?: number;
  variant?: 'blue' | 'green' | 'yellow' | 'orange' | 'red' | 'purple' | 'cyan';
  label?: string;
  showValue?: boolean;
  className?: string;
}

const progressColors: Record<string, string> = {
  blue: 'bg-awp-blue',
  green: 'bg-awp-green',
  yellow: 'bg-awp-yellow',
  orange: 'bg-awp-orange',
  red: 'bg-awp-red',
  purple: 'bg-awp-purple',
  cyan: 'bg-awp-cyan',
};

export function ProgressBar({
  value,
  max = 100,
  variant = 'blue',
  label,
  showValue,
  className,
}: ProgressBarProps) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100));

  return (
    <div className={clsx('space-y-1', className)}>
      {(label || showValue) && (
        <div className="flex items-center justify-between text-xs text-awp-muted">
          {label && <span>{label}</span>}
          {showValue && (
            <span>
              {value.toLocaleString()} / {max.toLocaleString()}
            </span>
          )}
        </div>
      )}
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-awp-border">
        <div
          className={clsx(
            'h-full rounded-full transition-all duration-500 ease-out',
            progressColors[variant],
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// IconButton -- icon-only button with optional tooltip
// ---------------------------------------------------------------------------

interface IconButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  icon: React.ReactNode;
  tooltip?: string;
  variant?: 'ghost' | 'default' | 'primary' | 'danger';
  size?: 'sm' | 'md' | 'lg';
}

const btnVariants: Record<string, string> = {
  ghost: 'text-awp-muted hover:text-awp-text hover:bg-awp-border/40',
  default:
    'text-awp-text bg-awp-panel border border-awp-border hover:bg-awp-border/60',
  primary:
    'text-awp-bg bg-awp-blue hover:bg-awp-blue/80 font-medium',
  danger:
    'text-white bg-awp-red/80 hover:bg-awp-red font-medium',
};

const btnSizes: Record<string, string> = {
  sm: 'h-7 w-7',
  md: 'h-8 w-8',
  lg: 'h-10 w-10',
};

export function IconButton({
  icon,
  tooltip,
  variant = 'ghost',
  size = 'md',
  className,
  ...rest
}: IconButtonProps) {
  return (
    <Tooltip content={tooltip}>
      <button
        type="button"
        className={clsx(
          'inline-flex items-center justify-center rounded-lg transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-awp-blue/50 disabled:opacity-40 disabled:pointer-events-none',
          btnVariants[variant],
          btnSizes[size],
          className,
        )}
        {...rest}
      >
        {icon}
      </button>
    </Tooltip>
  );
}

// ---------------------------------------------------------------------------
// Tooltip -- floating tooltip (CSS-only, no portal for simplicity)
// ---------------------------------------------------------------------------

interface TooltipProps {
  content?: string;
  side?: 'top' | 'bottom' | 'left' | 'right';
  children: React.ReactNode;
}

export function Tooltip({
  content,
  side = 'bottom',
  children,
}: TooltipProps) {
  if (!content) return <>{children}</>;

  const positionClasses: Record<string, string> = {
    top: 'bottom-full left-1/2 -translate-x-1/2 mb-2',
    bottom: 'top-full left-1/2 -translate-x-1/2 mt-2',
    left: 'right-full top-1/2 -translate-y-1/2 mr-2',
    right: 'left-full top-1/2 -translate-y-1/2 ml-2',
  };

  return (
    <span className="group relative inline-flex">
      {children}
      <span
        className={clsx(
          'pointer-events-none absolute z-50 whitespace-nowrap rounded-md bg-awp-text px-2 py-1 text-xs font-medium text-awp-bg opacity-0 shadow-lg transition-opacity group-hover:opacity-100',
          positionClasses[side],
        )}
      >
        {content}
      </span>
    </span>
  );
}

// ---------------------------------------------------------------------------
// Modal -- overlay dialog
// ---------------------------------------------------------------------------

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: React.ReactNode;
  className?: string;
}

export function Modal({ open, onClose, title, children, className }: ModalProps) {
  const overlayRef = useRef<HTMLDivElement>(null);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  const handleOverlayClick = useCallback(
    (e: React.MouseEvent) => {
      if (e.target === overlayRef.current) onClose();
    },
    [onClose],
  );

  if (!open) return null;

  return (
    <div
      ref={overlayRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in"
      onClick={handleOverlayClick}
    >
      <div
        className={clsx(
          'relative w-full max-w-lg rounded-2xl border border-awp-border bg-awp-panel p-6 shadow-2xl animate-fade-in',
          className,
        )}
      >
        {title && (
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-semibold text-awp-text">{title}</h2>
            <IconButton
              icon={<X className="h-4 w-4" />}
              onClick={onClose}
              tooltip="Close"
            />
          </div>
        )}
        {children}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Drawer -- slide-in side panel
// ---------------------------------------------------------------------------

interface DrawerProps {
  open: boolean;
  onClose: () => void;
  side?: 'left' | 'right';
  title?: string;
  width?: string;
  children: React.ReactNode;
  className?: string;
}

export function Drawer({
  open,
  onClose,
  side = 'right',
  title,
  width = 'w-80',
  children,
  className,
}: DrawerProps) {
  // Close on Escape
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
          className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm animate-fade-in"
          onClick={onClose}
        />
      )}

      {/* Panel */}
      <div
        className={clsx(
          'fixed top-0 z-50 h-full border-awp-border bg-awp-panel shadow-2xl transition-transform duration-300',
          width,
          side === 'right'
            ? 'right-0 border-l'
            : 'left-0 border-r',
          open
            ? 'translate-x-0'
            : side === 'right'
              ? 'translate-x-full'
              : '-translate-x-full',
          className,
        )}
      >
        {title && (
          <div className="flex items-center justify-between border-b border-awp-border px-4 py-3">
            <h3 className="text-sm font-semibold text-awp-text">{title}</h3>
            <IconButton
              icon={<X className="h-4 w-4" />}
              onClick={onClose}
              tooltip="Close"
              size="sm"
            />
          </div>
        )}
        <div className="h-[calc(100%-49px)] overflow-y-auto p-4">
          {children}
        </div>
      </div>
    </>
  );
}
