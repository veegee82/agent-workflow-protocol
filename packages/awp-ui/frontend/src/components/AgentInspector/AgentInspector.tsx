import React, { useMemo, useState } from 'react';
import {
  X,
  Diamond,
  Star,
  RefreshCw,
  Circle,
  Wrench,
  CheckSquare,
  ChevronDown,
  ChevronRight,
  AlertTriangle,
  GitBranch,
  Activity,
} from 'lucide-react';
import { useWorkflowStore } from '@/stores/workflowStore';
import { Badge } from '@/components/Layout';
import clsx from 'clsx';

// ---------------------------------------------------------------------------
// Collapsible JSON viewer (reused from OutputPanel concept)
// ---------------------------------------------------------------------------

function JsonValue({ value, depth = 0 }: { value: unknown; depth?: number }) {
  const [open, setOpen] = useState(depth < 2);

  if (value === null || value === undefined) {
    return <span className="text-awp-muted italic">null</span>;
  }
  if (typeof value === 'boolean') {
    return <span className="text-awp-orange">{String(value)}</span>;
  }
  if (typeof value === 'number') {
    return <span className="text-awp-cyan">{value}</span>;
  }
  if (typeof value === 'string') {
    return <span className="text-awp-green break-all">&quot;{value}&quot;</span>;
  }

  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-awp-muted">[]</span>;
    return (
      <div style={{ paddingLeft: depth > 0 ? 12 : 0 }}>
        <button
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-1 text-awp-text hover:text-awp-blue transition-colors"
        >
          {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          <span className="text-awp-muted text-[10px]">[{value.length}]</span>
        </button>
        {open && (
          <div className="ml-3 border-l border-awp-border/40 pl-2 mt-0.5">
            {value.map((item, i) => (
              <div key={i} className="flex items-start gap-1">
                <span className="text-awp-muted text-[10px] shrink-0 mt-0.5">{i}:</span>
                <JsonValue value={item} depth={depth + 1} />
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return <span className="text-awp-muted">{'{}'}</span>;
    return (
      <div style={{ paddingLeft: depth > 0 ? 12 : 0 }}>
        <button
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-1 text-awp-text hover:text-awp-blue transition-colors"
        >
          {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          <span className="text-awp-muted text-[10px]">{'{'}...{'}'}</span>
        </button>
        {open && (
          <div className="ml-3 border-l border-awp-border/40 pl-2 mt-0.5">
            {entries.map(([k, v]) => (
              <div key={k} className="flex items-start gap-1">
                <span className="text-awp-purple text-[11px] shrink-0">{k}:</span>
                <JsonValue value={v} depth={depth + 1} />
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  return <span className="text-awp-text">{String(value)}</span>;
}

// ---------------------------------------------------------------------------
// Collapsible section
// ---------------------------------------------------------------------------

function Section({
  title,
  icon,
  defaultOpen = true,
  children,
  badge,
}: {
  title: string;
  icon: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
  badge?: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="border-b border-awp-border/40 last:border-b-0">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-4 py-2.5 text-xs font-medium text-awp-text hover:bg-awp-bg/40 transition-colors"
      >
        {open ? (
          <ChevronDown className="h-3 w-3 text-awp-muted shrink-0" />
        ) : (
          <ChevronRight className="h-3 w-3 text-awp-muted shrink-0" />
        )}
        <span className="shrink-0">{icon}</span>
        <span className="truncate">{title}</span>
        {badge && <span className="ml-auto shrink-0">{badge}</span>}
      </button>
      {open && (
        <div className="px-4 pb-3 animate-fade-in">
          {children}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Node type icons
// ---------------------------------------------------------------------------

const nodeTypeIcons: Record<string, React.ReactNode> = {
  task: <Diamond className="h-4 w-4 text-awp-blue" />,
  manager: <Star className="h-4 w-4 text-awp-purple" />,
  iteration: <RefreshCw className="h-4 w-4 text-awp-yellow" />,
  worker: <Circle className="h-4 w-4 text-awp-cyan" />,
  toolCall: <Wrench className="h-4 w-4 text-awp-green" />,
  completion: <CheckSquare className="h-4 w-4 text-awp-green" />,
};

function statusBadgeVariant(status: string) {
  switch (status) {
    case 'running':
      return 'blue' as const;
    case 'complete':
      return 'green' as const;
    case 'error':
      return 'red' as const;
    default:
      return 'default' as const;
  }
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function AgentInspector() {
  const selectedNodeId = useWorkflowStore((s) => s.selectedNodeId);
  const inspectorOpen = useWorkflowStore((s) => s.inspectorOpen);
  const toggleInspector = useWorkflowStore((s) => s.toggleInspector);
  const selectNode = useWorkflowStore((s) => s.selectNode);
  const graphNodes = useWorkflowStore((s) => s.graphNodes);
  const graphEdges = useWorkflowStore((s) => s.graphEdges);

  const selectedNode = useMemo(
    () => graphNodes.find((n) => n.id === selectedNodeId),
    [graphNodes, selectedNodeId],
  );

  const childNodes = useMemo(() => {
    if (!selectedNodeId) return [];
    const childIds = graphEdges
      .filter((e) => e.source === selectedNodeId)
      .map((e) => e.target);
    return graphNodes.filter((n) => childIds.includes(n.id));
  }, [graphNodes, graphEdges, selectedNodeId]);

  if (!inspectorOpen || !selectedNode) return null;

  const data = selectedNode.data as Record<string, unknown>;
  const nodeType = (data.nodeType as string) ?? 'task';
  const status = (data.status as string) ?? 'pending';
  const label = (data.label as string) ?? selectedNode.id;
  const confidence = data.confidence as number | undefined;
  const inputs: Record<string, unknown> | undefined = data.inputs as Record<string, unknown> | undefined;
  const outputs: Record<string, unknown> | undefined = data.outputs as Record<string, unknown> | undefined;
  const timing = data.timing as Record<string, unknown> | undefined;
  const error = data.error as string | undefined;
  const toolsUsed = data.tools_used as string[] | undefined;
  const hasInputs = inputs != null && Object.keys(inputs).length > 0;
  const hasOutputs = outputs != null && Object.keys(outputs).length > 0;

  const handleClose = () => {
    selectNode(null);
    toggleInspector();
  };

  return (
    <div className="flex h-full w-80 flex-col border-l border-awp-border bg-awp-panel animate-slide-in-right">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-awp-border px-4 py-3">
        {nodeTypeIcons[nodeType] ?? <Circle className="h-4 w-4 text-awp-muted" />}
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold text-awp-text truncate">
            {label}
          </h3>
          <div className="flex items-center gap-2 mt-0.5">
            <span className="text-[10px] text-awp-muted capitalize">{nodeType}</span>
            <Badge
              variant={statusBadgeVariant(status)}
              dot
            >
              {status}
            </Badge>
          </div>
        </div>
        <button
          onClick={handleClose}
          className="rounded-lg p-1.5 text-awp-muted hover:bg-awp-border hover:text-awp-text transition-colors"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Sections */}
      <div className="flex-1 overflow-y-auto">
        {/* Overview */}
        <Section
          title="Overview"
          icon={<Activity className="h-3 w-3 text-awp-blue" />}
        >
          <div className="space-y-2 text-xs">
            <div className="flex items-center justify-between">
              <span className="text-awp-muted">Type</span>
              <span className="text-awp-text capitalize">{nodeType}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-awp-muted">Status</span>
              <Badge variant={statusBadgeVariant(status)} dot>
                {status}
              </Badge>
            </div>
            {confidence !== undefined && (
              <div className="flex items-center justify-between">
                <span className="text-awp-muted">Confidence</span>
                <span
                  className={clsx(
                    'font-mono font-semibold',
                    confidence >= 0.8
                      ? 'text-awp-green'
                      : confidence >= 0.5
                        ? 'text-awp-yellow'
                        : confidence >= 0.3
                          ? 'text-awp-orange'
                          : 'text-awp-red',
                  )}
                >
                  {(confidence * 100).toFixed(1)}%
                </span>
              </div>
            )}
            {timing != null && (
              <>
                {timing.start != null && (
                  <div className="flex items-center justify-between">
                    <span className="text-awp-muted">Started</span>
                    <span className="text-awp-text font-mono text-[10px]">
                      {new Date(timing.start as string).toLocaleTimeString()}
                    </span>
                  </div>
                )}
                {timing.end != null && (
                  <div className="flex items-center justify-between">
                    <span className="text-awp-muted">Ended</span>
                    <span className="text-awp-text font-mono text-[10px]">
                      {new Date(timing.end as string).toLocaleTimeString()}
                    </span>
                  </div>
                )}
                {timing.duration_ms !== undefined && (
                  <div className="flex items-center justify-between">
                    <span className="text-awp-muted">Duration</span>
                    <span className="text-awp-text font-mono">
                      {Number(timing.duration_ms) >= 1000
                        ? `${(Number(timing.duration_ms) / 1000).toFixed(1)}s`
                        : `${Number(timing.duration_ms)}ms`}
                    </span>
                  </div>
                )}
              </>
            )}
          </div>
        </Section>

        {/* Inputs */}
        {hasInputs && (
            <Section
              title="Inputs"
              icon={<ChevronRight className="h-3 w-3 text-awp-cyan" />}
              defaultOpen={false}
            >
              <div className="rounded-lg bg-awp-bg p-2 font-mono text-[11px] overflow-x-auto">
                <JsonValue value={inputs ?? {}} />
              </div>
            </Section>
        )}

        {/* Outputs */}
        {hasOutputs && (
          <Section
            title="Outputs"
            icon={<ChevronRight className="h-3 w-3 text-awp-green" />}
            defaultOpen={false}
          >
            <div className="rounded-lg bg-awp-bg p-2 font-mono text-[11px] overflow-x-auto">
              <JsonValue value={outputs ?? {}} />
            </div>
          </Section>
        )}

        {/* Internal State */}
        {(confidence !== undefined || data.decision != null) && (
          <Section
            title="Internal State"
            icon={<Activity className="h-3 w-3 text-awp-purple" />}
            defaultOpen={false}
          >
            <div className="space-y-2 text-xs">
              {confidence !== undefined && (
                <div>
                  <span className="text-awp-muted">Confidence: </span>
                  <span
                    className={clsx(
                      'font-mono font-semibold',
                      confidence >= 0.8
                        ? 'text-awp-green'
                        : confidence >= 0.5
                          ? 'text-awp-yellow'
                          : 'text-awp-orange',
                    )}
                  >
                    {confidence.toFixed(3)}
                  </span>
                </div>
              )}
              {data.decision != null && (
                <div>
                  <span className="text-awp-muted">Decision: </span>
                  <span className="text-awp-text capitalize">
                    {String(data.decision)}
                  </span>
                </div>
              )}
            </div>
          </Section>
        )}

        {/* Tools Used */}
        {toolsUsed && toolsUsed.length > 0 && (
          <Section
            title="Tools Used"
            icon={<Wrench className="h-3 w-3 text-awp-yellow" />}
            defaultOpen={false}
            badge={
              <span className="rounded-full bg-awp-yellow/15 px-1.5 py-0.5 text-[9px] font-semibold text-awp-yellow">
                {toolsUsed.length}
              </span>
            }
          >
            <div className="space-y-1">
              {toolsUsed.map((tool, i) => (
                <div
                  key={`${tool}-${i}`}
                  className="flex items-center gap-2 rounded-md bg-awp-bg px-2 py-1"
                >
                  <Wrench className="h-3 w-3 text-awp-muted" />
                  <span className="text-[11px] font-mono text-awp-text">{tool}</span>
                </div>
              ))}
            </div>
          </Section>
        )}

        {/* Errors */}
        {error && (
          <Section
            title="Errors"
            icon={<AlertTriangle className="h-3 w-3 text-awp-red" />}
          >
            <div className="rounded-lg border border-awp-red/30 bg-awp-red/5 p-2.5">
              <pre className="whitespace-pre-wrap break-words text-[11px] text-awp-red/90 font-mono">
                {error}
              </pre>
            </div>
          </Section>
        )}

        {/* Sub-delegations */}
        {childNodes.length > 0 && (
          <Section
            title="Sub-delegations"
            icon={<GitBranch className="h-3 w-3 text-awp-purple" />}
            defaultOpen={false}
            badge={
              <span className="rounded-full bg-awp-purple/15 px-1.5 py-0.5 text-[9px] font-semibold text-awp-purple">
                {childNodes.length}
              </span>
            }
          >
            <div className="space-y-1">
              {childNodes.map((child) => {
                const cData = child.data as Record<string, unknown>;
                const cStatus = (cData.status as string) ?? 'pending';
                return (
                  <button
                    key={child.id}
                    onClick={() => {
                      const store = useWorkflowStore.getState();
                      store.selectNode(child.id);
                    }}
                    className="flex w-full items-center gap-2 rounded-md bg-awp-bg px-2.5 py-1.5 text-left hover:bg-awp-border/40 transition-colors"
                  >
                    {nodeTypeIcons[(cData.nodeType as string) ?? 'task'] ?? (
                      <Circle className="h-3 w-3 text-awp-muted" />
                    )}
                    <span className="flex-1 text-[11px] text-awp-text truncate">
                      {(cData.label as string) ?? child.id}
                    </span>
                    <Badge variant={statusBadgeVariant(cStatus)} dot>
                      {cStatus}
                    </Badge>
                  </button>
                );
              })}
            </div>
          </Section>
        )}
      </div>
    </div>
  );
}
