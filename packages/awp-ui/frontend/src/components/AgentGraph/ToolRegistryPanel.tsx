import { useState } from 'react';
import { Wrench, ChevronDown, ChevronRight, Sparkles, Repeat } from 'lucide-react';
import clsx from 'clsx';
import { useWorkflowStore } from '@/stores/workflowStore';

/**
 * Panel listing dynamically created tools. Rendered inside RegistrySidebar.
 *
 * The graph stays focused on manager → iter → worker → toolCall, while the
 * tool inventory gets its own affordance (creator, description, reuse count).
 */
export function ToolRegistryPanel() {
  const registry = useWorkflowStore((s) => s.toolRegistry) ?? [];
  // Default collapsed so empty registries don't waste vertical space, but the
  // header button stays rendered as a discoverable toggle.
  const [collapsed, setCollapsed] = useState(true);

  const total = registry.length;
  const calledCount = registry.filter((t) => t.called).length;

  return (
    <div className="flex flex-col bg-awp-panel/95 backdrop-blur-md border border-awp-border/60 rounded-xl shadow-xl overflow-hidden">
      <button
        onClick={() => setCollapsed((v) => !v)}
        className="flex items-center gap-2 px-3 py-2 border-b border-awp-border/40 hover:bg-awp-border/20"
      >
        <Wrench className="h-4 w-4 text-awp-cyan shrink-0" />
        <span className="text-xs font-semibold text-awp-text">Tool Registry</span>
        <span className="text-[10px] text-awp-muted ml-auto">
          {calledCount}/{total} used
        </span>
        {collapsed ? (
          <ChevronRight className="h-3 w-3 text-awp-muted" />
        ) : (
          <ChevronDown className="h-3 w-3 text-awp-muted" />
        )}
      </button>
      {!collapsed && registry.length === 0 && (
        <div className="p-3 text-[11px] text-awp-muted italic">
          No dynamic tools registered yet. Tools created via the factory
          appear here once a worker returns a <code>tools_created</code> array.
        </div>
      )}
      {!collapsed && registry.length > 0 && (
        <div className="overflow-y-auto p-2 space-y-2 max-h-72">
          {registry.map((t) => (
            <div
              key={t.fqn}
              className={clsx(
                'rounded-lg border p-2 text-xs',
                t.called
                  ? 'border-awp-cyan/40 bg-awp-cyan/5'
                  : 'border-awp-border/40 bg-awp-panel/40 opacity-80',
              )}
            >
              <div className="flex items-start gap-1.5">
                <Sparkles
                  className={clsx(
                    'h-3 w-3 mt-0.5 shrink-0',
                    t.called ? 'text-awp-cyan' : 'text-awp-muted',
                  )}
                />
                <div className="min-w-0 flex-1">
                  <div className="font-mono font-semibold text-awp-text truncate">
                    {t.fqn}
                  </div>
                  <div className="text-[10px] text-awp-muted mt-0.5">
                    by <span className="text-awp-text">{t.creator_agent}</span>
                  </div>
                  {t.description && (
                    <div className="text-[10px] text-awp-muted/90 mt-1 line-clamp-3">
                      {t.description}
                    </div>
                  )}
                  {t.call_count > 0 && (
                    <div className="flex items-center gap-1 mt-1.5 text-[10px] text-awp-green">
                      <Repeat className="h-3 w-3" />
                      {t.call_count} {t.call_count === 1 ? 'call' : 'calls'}
                    </div>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
