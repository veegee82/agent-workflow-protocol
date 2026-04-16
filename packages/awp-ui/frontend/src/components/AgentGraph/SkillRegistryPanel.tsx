import { useState } from 'react';
import { BookOpen, ChevronDown, ChevronRight } from 'lucide-react';
import { useWorkflowStore } from '@/stores/workflowStore';

/**
 * Panel listing persisted skills (workspace/skills/*.md). Rendered inside
 * RegistrySidebar alongside the Tool Registry.
 *
 * Skills are cross-run reusable within an experiment (the runtime
 * symlinks ``shared/skills`` into every run's workspace).
 */
export function SkillRegistryPanel() {
  const skills = useWorkflowStore((s) => s.skillRegistry) ?? [];
  const [collapsed, setCollapsed] = useState(true);

  return (
    <div className="flex flex-col bg-awp-panel/95 backdrop-blur-md border border-awp-border/60 rounded-xl shadow-xl overflow-hidden">
      <button
        onClick={() => setCollapsed((v) => !v)}
        className="flex items-center gap-2 px-3 py-2 border-b border-awp-border/40 hover:bg-awp-border/20"
      >
        <BookOpen className="h-4 w-4 text-awp-yellow shrink-0" />
        <span className="text-xs font-semibold text-awp-text">Skill Registry</span>
        <span className="text-[10px] text-awp-muted ml-auto">{skills.length}</span>
        {collapsed ? (
          <ChevronRight className="h-3 w-3 text-awp-muted" />
        ) : (
          <ChevronDown className="h-3 w-3 text-awp-muted" />
        )}
      </button>
      {!collapsed && skills.length === 0 && (
        <div className="p-3 text-[11px] text-awp-muted italic">
          No persisted skills yet. Skills created via <code>skills_created</code> in a
          worker result land under <code>workspace/skills/*.md</code>.
        </div>
      )}
      {!collapsed && skills.length > 0 && (
        <div className="overflow-y-auto p-2 space-y-2 max-h-72">
          {skills.map((s) => (
            <div
              key={s.name}
              className="rounded-lg border border-awp-yellow/30 bg-awp-yellow/5 p-2 text-xs"
            >
              <div className="min-w-0">
                <div className="font-mono font-semibold text-awp-text truncate">
                  {s.title || s.name}
                </div>
                <div className="text-[10px] text-awp-muted mt-0.5 font-mono">
                  {s.name}.md · {(s.size_bytes / 1024).toFixed(1)} KB
                </div>
                {s.description && (
                  <div className="text-[10px] text-awp-muted/90 mt-1 line-clamp-3">
                    {s.description}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
