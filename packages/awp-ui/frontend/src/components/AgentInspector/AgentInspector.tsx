import React, { useCallback, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
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
  Copy,
  Check,
  Zap,
} from 'lucide-react';
import { useWorkflowStore } from '@/stores/workflowStore';
import { Badge } from '@/components/Layout';
import clsx from 'clsx';

// ---------------------------------------------------------------------------
// Copy button for code blocks
// ---------------------------------------------------------------------------

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [text]);

  return (
    <button
      onClick={handleCopy}
      className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-awp-muted hover:bg-awp-border/60 hover:text-awp-text transition-colors"
    >
      {copied ? (
        <>
          <Check className="h-3 w-3 text-awp-green" />
          <span className="text-awp-green">Copied</span>
        </>
      ) : (
        <>
          <Copy className="h-3 w-3" />
          <span>Copy</span>
        </>
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Collapsible JSON viewer (reused from OutputPanel concept)
// ---------------------------------------------------------------------------

function JsonValue({ value, depth = 0, name }: { value: unknown; depth?: number; name?: string }) {
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
    // Detect code-like strings: key is "code" or "source" and multi-line
    const isCode =
      (name === 'code' || name === 'source') && value.includes('\n');
    if (isCode) {
      return (
        <div className="mt-1 w-full">
          <div className="relative group">
            <div className="absolute right-2 top-2 flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity z-10">
              <span className="text-[10px] uppercase tracking-wider text-awp-muted">python</span>
              <CopyButton text={value} />
            </div>
            <SyntaxHighlighter
              style={oneDark}
              language="python"
              PreTag="div"
              customStyle={{
                background: '#0d1117',
                borderRadius: '0.5rem',
                fontSize: '0.75rem',
                border: '1px solid #30363d',
                margin: 0,
              }}
            >
              {value}
            </SyntaxHighlighter>
          </div>
        </div>
      );
    }

    // Detect markdown-rich strings
    const isMarkdown =
      value.includes('\n') &&
      (/^#{1,6}\s/m.test(value) ||
        /^[-*]\s/m.test(value) ||
        /\*\*.+\*\*/m.test(value) ||
        /\[.+\]\(.+\)/m.test(value) ||
        /^>\s/m.test(value) ||
        /^```/m.test(value) ||
        /^\d+\.\s/m.test(value));
    if (isMarkdown) {
      return (
        <div className="mt-1 w-full rounded-lg border border-awp-border/40 bg-awp-bg/50 p-2">
          <div className="prose prose-invert prose-xs max-w-none prose-headings:text-awp-text prose-p:text-awp-text prose-a:text-awp-blue prose-strong:text-awp-text prose-code:text-awp-cyan prose-code:bg-awp-bg prose-code:rounded prose-code:px-1 prose-code:py-0.5 prose-code:before:content-none prose-code:after:content-none prose-pre:bg-transparent prose-pre:p-0">
            <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>
              {value}
            </ReactMarkdown>
          </div>
        </div>
      );
    }

    // Detect embedded JSON strings
    const trimmedStr = value.trim();
    const isJsonStr =
      (trimmedStr.startsWith('{') && trimmedStr.endsWith('}')) ||
      (trimmedStr.startsWith('[') && trimmedStr.endsWith(']'));
    if (isJsonStr && trimmedStr.length > 2) {
      try {
        const inner = JSON.parse(trimmedStr);
        return <JsonValue value={inner} depth={depth + 1} />;
      } catch {
        // not valid JSON, fall through
      }
    }

    // Short strings: inline
    if (value.length <= 200 && !value.includes('\n')) {
      return <span className="text-awp-green break-all">&quot;{value}&quot;</span>;
    }

    // Long plain strings: scrollable block
    return (
      <div className="mt-1 w-full rounded-lg border border-awp-border/40 bg-awp-bg/50 p-2 text-awp-green text-[11px] max-h-48 overflow-y-auto whitespace-pre-wrap break-words">
        {value}
      </div>
    );
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
            {entries.map(([k, v]) => {
              const isCodeField = (k === 'code' || k === 'source') && typeof v === 'string' && v.includes('\n');
              return (
                <div key={k} className={isCodeField ? '' : 'flex items-start gap-1'}>
                  <span className="text-awp-purple text-[11px] shrink-0">{k}:</span>
                  <JsonValue value={v} depth={depth + 1} name={k} />
                </div>
              );
            })}
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
// LLM Trace helpers
// ---------------------------------------------------------------------------

function formatTokens(n: number): string {
  return n.toLocaleString('en-US');
}

function formatLatency(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms)}ms`;
}

const roleBadgeClasses: Record<string, string> = {
  system: 'bg-awp-purple/15 text-awp-purple',
  user: 'bg-awp-blue/15 text-awp-blue',
  assistant: 'bg-awp-green/15 text-awp-green',
  tool: 'bg-awp-yellow/15 text-awp-yellow',
};

function LLMCallCard({ call, index }: { call: Record<string, unknown>; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const usage = (call.usage as Record<string, number>) || {};
  const messages = (call.messages_in as Array<Record<string, string>>) || [];
  const response = (call.response as Record<string, unknown>) || {};
  const model = (call.model as string) || '';
  const latencyMs = call.latency_ms as number | undefined;
  const finishReason = (call.finish_reason as string) || (response.finish_reason as string) || '';
  const totalTokens = usage.total_tokens ?? (usage.prompt_tokens ?? 0) + (usage.completion_tokens ?? 0);

  return (
    <div className="rounded-lg border border-awp-border/40 bg-awp-bg/30 overflow-hidden">
      <button
        onClick={() => setExpanded(v => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-xs text-awp-text hover:bg-awp-bg/60 transition-colors"
      >
        {expanded ? (
          <ChevronDown className="h-3 w-3 text-awp-muted shrink-0" />
        ) : (
          <ChevronRight className="h-3 w-3 text-awp-muted shrink-0" />
        )}
        <span className="font-semibold text-awp-orange shrink-0">#{index + 1}</span>
        {model && <span className="text-awp-muted truncate">{model}</span>}
        {totalTokens > 0 && (
          <span className="rounded-full bg-awp-orange/15 px-1.5 py-0.5 text-[9px] font-semibold text-awp-orange shrink-0">
            {formatTokens(totalTokens)} tok
          </span>
        )}
        {latencyMs != null && (
          <span className="text-awp-muted text-[10px] shrink-0">{formatLatency(latencyMs)}</span>
        )}
        {finishReason && (
          <span className="ml-auto text-awp-muted text-[10px] shrink-0">{finishReason}</span>
        )}
      </button>
      {expanded && (
        <div className="border-t border-awp-border/30 px-3 py-2 space-y-2">
          {/* Messages In */}
          {messages.length > 0 && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-awp-muted mb-1">Messages In</div>
              <div className="space-y-1">
                {messages.map((msg, mi) => {
                  const role = msg.role || 'unknown';
                  const content = msg.content || '';
                  const badgeCls = roleBadgeClasses[role] || 'bg-awp-border/40 text-awp-muted';
                  return (
                    <div key={mi} className="rounded-md border border-awp-border/30 bg-awp-bg/40 p-2">
                      <span className={clsx('inline-block rounded px-1.5 py-0.5 text-[9px] font-semibold mb-1', badgeCls)}>
                        {role}
                      </span>
                      <div className="text-[11px] text-awp-text whitespace-pre-wrap break-words max-h-40 overflow-y-auto">
                        {content.length > 500 ? content.slice(0, 500) + '...' : content}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
          {/* Response */}
          {response.content != null && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-awp-muted mb-1">Response</div>
              <div className="rounded-md border border-awp-border/30 bg-awp-bg/40 p-2">
                <span className={clsx('inline-block rounded px-1.5 py-0.5 text-[9px] font-semibold mb-1', roleBadgeClasses.assistant)}>
                  assistant
                </span>
                <div className="text-[11px] text-awp-text whitespace-pre-wrap break-words max-h-40 overflow-y-auto">
                  {String(response.content).length > 500
                    ? String(response.content).slice(0, 500) + '...'
                    : String(response.content)}
                </div>
                {response.tool_calls != null && (
                  <div className="mt-1 rounded bg-awp-bg p-1.5 font-mono text-[10px]">
                    <JsonValue value={response.tool_calls} />
                  </div>
                )}
              </div>
            </div>
          )}
          {/* Usage details */}
          {Object.keys(usage).length > 0 && (
            <div className="flex items-center gap-3 text-[10px] text-awp-muted">
              {usage.prompt_tokens != null && <span>Prompt: {formatTokens(usage.prompt_tokens)}</span>}
              {usage.completion_tokens != null && <span>Completion: {formatTokens(usage.completion_tokens)}</span>}
              {usage.total_tokens != null && <span>Total: {formatTokens(usage.total_tokens)}</span>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function LLMTraceSection({ data }: { data: Record<string, unknown> }) {
  const [traceData, setTraceData] = useState<{
    calls: Record<string, unknown>[];
    summary: Record<string, unknown> | null;
  } | null>(null);
  const [loadingTrace, setLoadingTrace] = useState(false);

  const llmCallCount = data.llmCallCount as number;
  const llmTotalTokens = data.llmTotalTokens as number | undefined;
  const llmLatencyMs = data.llmLatencyMs as number | undefined;
  const llmModel = data.llmModel as string | undefined;

  const loadTrace = useCallback(async () => {
    setLoadingTrace(true);
    try {
      const workerId = data.worker_id as string;
      const iteration = String(data.iteration || '001').padStart(3, '0');
      const runId = useWorkflowStore.getState().currentRunId;
      if (!runId) return;
      const res = await fetch(`/api/runs/${runId}/trace/${iteration}/${workerId}`);
      if (res.ok) {
        const json = await res.json();
        setTraceData(json);
      }
    } finally {
      setLoadingTrace(false);
    }
  }, [data.worker_id, data.iteration]);

  return (
    <Section
      title="LLM Trace"
      icon={<Zap className="h-3 w-3 text-awp-orange" />}
      defaultOpen={false}
      badge={
        <span className="rounded-full bg-awp-orange/15 px-1.5 py-0.5 text-[9px] font-semibold text-awp-orange">
          {llmCallCount} {llmCallCount === 1 ? 'call' : 'calls'}
        </span>
      }
    >
      <div className="space-y-2">
        {/* Summary line */}
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {llmTotalTokens != null && (
            <span className="text-awp-muted">
              {formatTokens(llmTotalTokens)} tokens
            </span>
          )}
          {llmLatencyMs != null && (
            <span className="text-awp-muted">
              {formatLatency(llmLatencyMs)}
            </span>
          )}
          {llmModel && (
            <span className="text-awp-muted truncate max-w-[140px]" title={llmModel}>
              {llmModel}
            </span>
          )}
        </div>

        {/* Load / display trace */}
        {!traceData ? (
          <button
            onClick={loadTrace}
            disabled={loadingTrace}
            className="flex items-center gap-1.5 rounded-md bg-awp-orange/10 px-3 py-1.5 text-xs font-medium text-awp-orange hover:bg-awp-orange/20 transition-colors disabled:opacity-50"
          >
            <Zap className="h-3 w-3" />
            {loadingTrace ? 'Loading...' : 'View Trace'}
          </button>
        ) : (
          <div className="space-y-1.5">
            {traceData.calls.map((call, i) => (
              <LLMCallCard key={i} call={call} index={i} />
            ))}
            {traceData.calls.length === 0 && (
              <div className="text-xs text-awp-muted italic">No trace calls found.</div>
            )}
          </div>
        )}
      </div>
    </Section>
  );
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

        {/* LLM Trace */}
        {(data.llmCallCount as number) > 0 && (
          <LLMTraceSection data={data} />
        )}

        {/* Errors */}
        {error && (
          <Section
            title="Errors"
            icon={<AlertTriangle className="h-3 w-3 text-awp-red" />}
          >
            <div className="rounded-lg border border-awp-red/30 overflow-hidden">
              <SyntaxHighlighter
                language="text"
                style={oneDark}
                customStyle={{ margin: 0, padding: '0.625rem', background: 'rgba(248,81,73,0.05)', fontSize: '0.6875rem', lineHeight: '1.5', color: 'rgba(248,81,73,0.9)' }}
                wrapLines
                wrapLongLines
              >
                {error}
              </SyntaxHighlighter>
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
