import React, { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { clsx } from 'clsx';
import {
  Plus,
  Search,
  MoreHorizontal,
  Pencil,
  Trash2,
  MessageSquare,
  X,
} from 'lucide-react';
import type { Session } from '@/types';

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface SessionSidebarProps {
  sessions: Session[];
  currentSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewSession: () => void;
  onDeleteSession: (id: string) => void;
  onRenameSession: (id: string, title: string) => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Return a human-readable relative time string. */
function relativeTime(dateStr: string): string {
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diffMs = now - then;
  const diffSec = Math.floor(diffMs / 1000);

  if (diffSec < 60) return 'just now';
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  if (diffDay === 1) return 'yesterday';
  if (diffDay < 7) return `${diffDay}d ago`;
  return new Date(dateStr).toLocaleDateString();
}

/** Group sessions into time buckets. */
function groupSessions(
  sessions: Session[],
): { label: string; sessions: Session[] }[] {
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const startOfYesterday = startOfToday - 86_400_000;
  const startOf7DaysAgo = startOfToday - 7 * 86_400_000;

  const groups: Record<string, Session[]> = {
    Today: [],
    Yesterday: [],
    'Previous 7 Days': [],
    Older: [],
  };

  for (const s of sessions) {
    const t = new Date(s.updated_at).getTime();
    if (t >= startOfToday) {
      groups['Today'].push(s);
    } else if (t >= startOfYesterday) {
      groups['Yesterday'].push(s);
    } else if (t >= startOf7DaysAgo) {
      groups['Previous 7 Days'].push(s);
    } else {
      groups['Older'].push(s);
    }
  }

  return Object.entries(groups)
    .filter(([, arr]) => arr.length > 0)
    .map(([label, arr]) => ({ label, sessions: arr }));
}

/** Status dot color class. */
function statusDotClass(status: string | null): string {
  switch (status) {
    case 'complete':
      return 'bg-awp-green';
    case 'running':
      return 'bg-awp-blue animate-pulse';
    case 'error':
      return 'bg-awp-red';
    default:
      return 'bg-awp-muted/50';
  }
}

// ---------------------------------------------------------------------------
// Context Menu
// ---------------------------------------------------------------------------

function SessionContextMenu({
  x,
  y,
  onRename,
  onDelete,
  onClose,
}: {
  x: number;
  y: number;
  onRename: () => void;
  onDelete: () => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [onClose]);

  return (
    <div
      ref={ref}
      className="fixed z-50 min-w-[140px] rounded-lg border border-awp-border bg-awp-panel shadow-xl py-1 animate-fade-in"
      style={{ top: y, left: x }}
    >
      <button
        type="button"
        onClick={() => {
          onRename();
          onClose();
        }}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-awp-text hover:bg-awp-bg/60 transition-colors"
      >
        <Pencil className="h-3 w-3" />
        Rename
      </button>
      <button
        type="button"
        onClick={() => {
          onDelete();
          onClose();
        }}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-awp-red hover:bg-awp-red/10 transition-colors"
      >
        <Trash2 className="h-3 w-3" />
        Delete
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Session Item
// ---------------------------------------------------------------------------

function SessionItem({
  session,
  isActive,
  onSelect,
  onRename,
  onDelete,
}: {
  session: Session;
  isActive: boolean;
  onSelect: () => void;
  onRename: (title: string) => void;
  onDelete: () => void;
}) {
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(session.title);
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
  } | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isEditing) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [isEditing]);

  const commitRename = useCallback(() => {
    const trimmed = editValue.trim();
    if (trimmed && trimmed !== session.title) {
      onRename(trimmed);
    }
    setIsEditing(false);
  }, [editValue, session.title, onRename]);

  const handleContextMenu = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      setContextMenu({ x: e.clientX, y: e.clientY });
    },
    [],
  );

  return (
    <>
      <button
        type="button"
        onClick={onSelect}
        onContextMenu={handleContextMenu}
        className={clsx(
          'group w-full text-left rounded-lg px-3 py-2.5 transition-colors relative',
          isActive
            ? 'bg-awp-blue/10 border border-awp-blue/30'
            : 'hover:bg-awp-bg/60 border border-transparent',
        )}
      >
        {isEditing ? (
          <input
            ref={inputRef}
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onBlur={commitRename}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commitRename();
              if (e.key === 'Escape') {
                setEditValue(session.title);
                setIsEditing(false);
              }
            }}
            onClick={(e) => e.stopPropagation()}
            className="w-full bg-awp-bg border border-awp-blue/50 rounded px-1.5 py-0.5 text-xs text-awp-text focus:outline-none focus:ring-1 focus:ring-awp-blue"
          />
        ) : (
          <>
            <div className="flex items-center gap-2">
              <span
                className={clsx(
                  'h-2 w-2 rounded-full shrink-0',
                  statusDotClass(session.last_run_status),
                )}
              />
              <span className="text-xs font-medium text-awp-text truncate flex-1">
                {session.title}
              </span>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setContextMenu({
                    x: e.clientX,
                    y: e.clientY,
                  });
                }}
                className="opacity-0 group-hover:opacity-100 shrink-0 text-awp-muted hover:text-awp-text transition-opacity"
              >
                <MoreHorizontal className="h-3.5 w-3.5" />
              </button>
            </div>
            <div className="flex items-center gap-2 mt-1 ml-4">
              <span className="text-[10px] text-awp-muted">
                {relativeTime(session.updated_at)}
              </span>
              {session.run_count > 0 && (
                <span className="inline-flex items-center gap-0.5 rounded-full bg-awp-border/50 px-1.5 py-0.5 text-[10px] text-awp-muted">
                  <MessageSquare className="h-2.5 w-2.5" />
                  {session.run_count}
                </span>
              )}
            </div>
          </>
        )}
      </button>

      {contextMenu && (
        <SessionContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          onRename={() => {
            setEditValue(session.title);
            setIsEditing(true);
          }}
          onDelete={onDelete}
          onClose={() => setContextMenu(null)}
        />
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export function SessionSidebar({
  sessions,
  currentSessionId,
  onSelectSession,
  onNewSession,
  onDeleteSession,
  onRenameSession,
}: SessionSidebarProps) {
  const [search, setSearch] = useState('');

  const filtered = useMemo(() => {
    if (!search.trim()) return sessions;
    const q = search.toLowerCase();
    return sessions.filter((s) => s.title.toLowerCase().includes(q));
  }, [sessions, search]);

  const sorted = useMemo(
    () =>
      [...filtered].sort(
        (a, b) =>
          new Date(b.updated_at).getTime() -
          new Date(a.updated_at).getTime(),
      ),
    [filtered],
  );

  const groups = useMemo(() => groupSessions(sorted), [sorted]);

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-3 pt-3 pb-2 space-y-2">
        <button
          type="button"
          onClick={onNewSession}
          className="flex w-full items-center justify-center gap-2 rounded-lg border border-awp-border bg-awp-bg px-3 py-2 text-xs font-medium text-awp-text hover:bg-awp-blue/10 hover:border-awp-blue/30 hover:text-awp-blue transition-colors"
        >
          <Plus className="h-3.5 w-3.5" />
          New Session
        </button>
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 h-3 w-3 -translate-y-1/2 text-awp-muted" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search sessions..."
            className="w-full rounded-md border border-awp-border bg-awp-bg pl-7 pr-7 py-1.5 text-xs text-awp-text placeholder:text-awp-muted/50 focus:outline-none focus:ring-1 focus:ring-awp-blue focus:border-awp-blue transition-colors"
          />
          {search && (
            <button
              type="button"
              onClick={() => setSearch('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-awp-muted hover:text-awp-text"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>
      </div>

      {/* Session list */}
      <div className="flex-1 overflow-y-auto px-2 pb-3 space-y-1">
        {groups.length === 0 && (
          <div className="flex flex-col items-center justify-center py-8 text-awp-muted gap-2">
            <MessageSquare className="h-8 w-8 text-awp-border" />
            <p className="text-xs">
              {search ? 'No matching sessions' : 'No sessions yet'}
            </p>
          </div>
        )}
        {groups.map((group) => (
          <div key={group.label}>
            <div className="px-2 py-1.5">
              <span className="text-[10px] font-semibold text-awp-muted uppercase tracking-wider">
                {group.label}
              </span>
            </div>
            <div className="space-y-0.5">
              {group.sessions.map((session) => (
                <SessionItem
                  key={session.id}
                  session={session}
                  isActive={session.id === currentSessionId}
                  onSelect={() => onSelectSession(session.id)}
                  onRename={(title) => onRenameSession(session.id, title)}
                  onDelete={() => onDeleteSession(session.id)}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
