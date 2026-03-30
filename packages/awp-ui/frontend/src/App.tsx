import React, { useCallback, useEffect, useRef } from 'react';
import { clsx } from 'clsx';
import {
  Play,
  Square,
  RotateCcw,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  FileText,
  GitBranch,
  Settings,
  History,
  Upload,
  Trash2,
  Cpu,
  Zap,
  Clock,
  Users,
  Wrench,
  ChevronDown,
  Wifi,
  WifiOff,
  CircleDot,
  AlertCircle,
  CheckCircle2,
  Loader2,
  Key,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import { useWorkflowStore } from '@/stores/workflowStore';
import type { ActivePanel, OutputBlock } from '@/types';
import {
  TabBar,
  Panel,
  Badge,
  ProgressBar,
  IconButton,
} from '@/components/Layout';
import { SessionSidebar } from '@/components/SessionSidebar/SessionSidebar';
import { SecretsPanel } from '@/components/SecretsPanel/SecretsPanel';

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------

function statusVariant(status: string) {
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

function statusIcon(status: string) {
  switch (status) {
    case 'running':
      return <Loader2 className="h-3.5 w-3.5 animate-spin" />;
    case 'complete':
      return <CheckCircle2 className="h-3.5 w-3.5" />;
    case 'error':
      return <AlertCircle className="h-3.5 w-3.5" />;
    default:
      return <CircleDot className="h-3.5 w-3.5" />;
  }
}

// ---------------------------------------------------------------------------
// Top Bar
// ---------------------------------------------------------------------------

function TopBar() {
  const {
    runStatus,
    startRun,
    stopRun,
    reset,
    budget,
    activePanel,
    setActivePanel,
    sidebarOpen,
    toggleSidebar,
    inspectorOpen,
    toggleInspector,
    config,
    currentSessionId,
    sessions,
  } = useWorkflowStore();

  const currentSession = sessions.find((s) => s.id === currentSessionId);

  const isRunning = runStatus === 'running';
  const canStart = config.task.trim().length > 0 && !isRunning;

  const tabs = [
    { id: 'output' as const, label: 'Output', icon: <FileText className="h-4 w-4" /> },
    { id: 'graph' as const, label: 'Graph', icon: <GitBranch className="h-4 w-4" /> },
    { id: 'history' as const, label: 'History', icon: <History className="h-4 w-4" /> },
  ];

  const tokensPercent = budget.tokens_max > 0 ? budget.tokens_used / budget.tokens_max : 0;
  const loopsPercent = budget.loops_max > 0 ? budget.loops_used / budget.loops_max : 0;

  return (
    <header className="flex items-center gap-2 border-b border-awp-border bg-awp-panel px-3 h-12 shrink-0">
      {/* Sidebar toggle */}
      <IconButton tooltip="Toggle sidebar" onClick={toggleSidebar} size="sm">
        {sidebarOpen ? (
          <PanelLeftClose className="h-4 w-4" />
        ) : (
          <PanelLeftOpen className="h-4 w-4" />
        )}
      </IconButton>

      {/* Session title */}
      {currentSession && (
        <span className="text-xs font-medium text-awp-muted truncate max-w-[160px]" title={currentSession.title}>
          {currentSession.title}
        </span>
      )}

      {/* Run controls */}
      <div className="flex items-center gap-1.5">
        {isRunning ? (
          <button
            type="button"
            onClick={stopRun}
            className="inline-flex items-center gap-1.5 rounded-md bg-awp-red/15 px-3 py-1.5 text-sm font-medium text-awp-red hover:bg-awp-red/25 transition-colors"
          >
            <Square className="h-3.5 w-3.5" />
            Stop
          </button>
        ) : (
          <button
            type="button"
            onClick={startRun}
            disabled={!canStart}
            className={clsx(
              'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
              canStart
                ? 'bg-awp-blue/15 text-awp-blue hover:bg-awp-blue/25'
                : 'bg-awp-border/30 text-awp-muted cursor-not-allowed',
            )}
          >
            <Play className="h-3.5 w-3.5" />
            Run
          </button>
        )}
        <IconButton tooltip="Reset" onClick={reset} size="sm">
          <RotateCcw className="h-3.5 w-3.5" />
        </IconButton>
      </div>

      {/* Status badge */}
      <Badge variant={statusVariant(runStatus)} dot={isRunning}>
        {statusIcon(runStatus)}
        <span className="ml-1 capitalize">{runStatus}</span>
      </Badge>

      {/* Budget mini-indicators */}
      {isRunning && (
        <div className="hidden md:flex items-center gap-3 ml-2 text-xs text-awp-muted">
          <span className="flex items-center gap-1" title="Tokens used">
            <Zap className="h-3 w-3" />
            {(budget.tokens_used / 1000).toFixed(0)}k
            <ProgressBar value={tokensPercent} className="w-12" />
          </span>
          <span className="flex items-center gap-1" title="Loops">
            <Cpu className="h-3 w-3" />
            {budget.loops_used}/{budget.loops_max}
            <ProgressBar value={loopsPercent} className="w-12" />
          </span>
          <span className="flex items-center gap-1" title="Workers">
            <Users className="h-3 w-3" />
            {budget.workers_used}/{budget.workers_max}
          </span>
        </div>
      )}

      {/* Spacer */}
      <div className="flex-1" />

      {/* Center tabs */}
      <TabBar
        tabs={tabs}
        activeId={activePanel}
        onChange={(id) => setActivePanel(id as ActivePanel)}
        className="border-b-0 bg-transparent"
      />

      <div className="flex-1" />

      {/* Inspector toggle */}
      <IconButton tooltip="Toggle inspector" onClick={toggleInspector} size="sm">
        {inspectorOpen ? (
          <PanelRightClose className="h-4 w-4" />
        ) : (
          <PanelRightOpen className="h-4 w-4" />
        )}
      </IconButton>
    </header>
  );
}

// ---------------------------------------------------------------------------
// Left Sidebar
// ---------------------------------------------------------------------------

function LeftSidebar() {
  const {
    config,
    updateConfig,
    attachedFiles,
    addFiles,
    removeFile,
    runStatus,
    secrets,
    addSecret,
    removeSecret,
  } = useWorkflowStore();

  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files) {
        addFiles(Array.from(e.target.files));
      }
    },
    [addFiles],
  );

  const isRunning = runStatus === 'running';

  return (
    <aside className="flex flex-col gap-3 h-full overflow-y-auto p-3">
      {/* Task input */}
      <Panel title="Task" icon={<FileText className="h-4 w-4 text-awp-blue" />}>
        <textarea
          value={config.task}
          onChange={(e) => updateConfig({ task: e.target.value })}
          placeholder="Describe the task for the agent workflow..."
          disabled={isRunning}
          rows={5}
          className={clsx(
            'w-full resize-none rounded-md border border-awp-border bg-awp-bg px-3 py-2',
            'text-sm text-awp-text placeholder:text-awp-muted/60',
            'focus:outline-none focus:ring-1 focus:ring-awp-blue focus:border-awp-blue',
            'disabled:opacity-50 disabled:cursor-not-allowed',
          )}
        />
      </Panel>

      {/* Files */}
      <Panel title="Files" icon={<Upload className="h-4 w-4 text-awp-purple" />}>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          onChange={handleFileChange}
          className="hidden"
        />
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={isRunning}
          className={clsx(
            'w-full rounded-md border border-dashed border-awp-border py-3 text-sm text-awp-muted',
            'hover:border-awp-blue hover:text-awp-blue transition-colors',
            'disabled:opacity-50 disabled:pointer-events-none',
          )}
        >
          Click to upload files
        </button>
        {attachedFiles.length > 0 && (
          <ul className="mt-2 space-y-1">
            {attachedFiles.map((f, i) => (
              <li
                key={`${f.name}-${i}`}
                className="flex items-center justify-between rounded px-2 py-1 text-xs text-awp-text bg-awp-bg"
              >
                <span className="truncate">{f.name}</span>
                <button
                  type="button"
                  onClick={() => removeFile(i)}
                  className="text-awp-muted hover:text-awp-red transition-colors ml-2 shrink-0"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      {/* Model settings */}
      <Panel
        title="Settings"
        icon={<Settings className="h-4 w-4 text-awp-green" />}
      >
        <div className="space-y-3">
          {/* Model */}
          <label className="block">
            <span className="text-xs text-awp-muted">Model</span>
            <input
              type="text"
              value={config.model}
              onChange={(e) => updateConfig({ model: e.target.value })}
              disabled={isRunning}
              className="mt-1 w-full rounded-md border border-awp-border bg-awp-bg px-2.5 py-1.5 text-sm text-awp-text focus:outline-none focus:ring-1 focus:ring-awp-blue disabled:opacity-50"
            />
          </label>

          {/* Worker model */}
          <label className="block">
            <span className="text-xs text-awp-muted">Worker model</span>
            <input
              type="text"
              value={config.worker_model ?? ''}
              onChange={(e) =>
                updateConfig({
                  worker_model: e.target.value || undefined,
                })
              }
              disabled={isRunning}
              placeholder="Same as model"
              className="mt-1 w-full rounded-md border border-awp-border bg-awp-bg px-2.5 py-1.5 text-sm text-awp-text placeholder:text-awp-muted/50 focus:outline-none focus:ring-1 focus:ring-awp-blue disabled:opacity-50"
            />
          </label>

          {/* Sandbox */}
          <label className="block">
            <span className="text-xs text-awp-muted">Sandbox</span>
            <div className="relative mt-1">
              <select
                value={config.sandbox}
                onChange={(e) =>
                  updateConfig({
                    sandbox: e.target.value as WorkflowConfig['sandbox'],
                  })
                }
                disabled={isRunning}
                className="w-full appearance-none rounded-md border border-awp-border bg-awp-bg px-2.5 py-1.5 pr-8 text-sm text-awp-text focus:outline-none focus:ring-1 focus:ring-awp-blue disabled:opacity-50"
              >
                <option value="subprocess">Subprocess</option>
                <option value="docker">Docker</option>
                <option value="venv">Virtualenv</option>
                <option value="none">None</option>
              </select>
              <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 text-awp-muted" />
            </div>
          </label>

          {/* Budget controls */}
          <div className="grid grid-cols-2 gap-2">
            <label className="block">
              <span className="text-xs text-awp-muted">Max loops</span>
              <input
                type="number"
                min={1}
                value={config.max_loops}
                onChange={(e) =>
                  updateConfig({ max_loops: Number(e.target.value) })
                }
                disabled={isRunning}
                className="mt-1 w-full rounded-md border border-awp-border bg-awp-bg px-2.5 py-1.5 text-sm text-awp-text focus:outline-none focus:ring-1 focus:ring-awp-blue disabled:opacity-50"
              />
            </label>
            <label className="block">
              <span className="text-xs text-awp-muted">Max workers</span>
              <input
                type="number"
                min={1}
                value={config.max_total_workers}
                onChange={(e) =>
                  updateConfig({
                    max_total_workers: Number(e.target.value),
                  })
                }
                disabled={isRunning}
                className="mt-1 w-full rounded-md border border-awp-border bg-awp-bg px-2.5 py-1.5 text-sm text-awp-text focus:outline-none focus:ring-1 focus:ring-awp-blue disabled:opacity-50"
              />
            </label>
            <label className="block">
              <span className="text-xs text-awp-muted">Max tokens</span>
              <input
                type="number"
                min={1000}
                step={10000}
                value={config.max_total_tokens}
                onChange={(e) =>
                  updateConfig({
                    max_total_tokens: Number(e.target.value),
                  })
                }
                disabled={isRunning}
                className="mt-1 w-full rounded-md border border-awp-border bg-awp-bg px-2.5 py-1.5 text-sm text-awp-text focus:outline-none focus:ring-1 focus:ring-awp-blue disabled:opacity-50"
              />
            </label>
            <label className="block">
              <span className="text-xs text-awp-muted">Wall time (s)</span>
              <input
                type="number"
                min={10}
                value={config.max_wall_time}
                onChange={(e) =>
                  updateConfig({ max_wall_time: Number(e.target.value) })
                }
                disabled={isRunning}
                className="mt-1 w-full rounded-md border border-awp-border bg-awp-bg px-2.5 py-1.5 text-sm text-awp-text focus:outline-none focus:ring-1 focus:ring-awp-blue disabled:opacity-50"
              />
            </label>
          </div>

          {/* Toggles */}
          <div className="flex flex-wrap gap-3">
            <label className="flex items-center gap-2 text-xs text-awp-text cursor-pointer">
              <input
                type="checkbox"
                checked={config.code_mode}
                onChange={(e) =>
                  updateConfig({ code_mode: e.target.checked })
                }
                disabled={isRunning}
                className="rounded border-awp-border bg-awp-bg text-awp-blue focus:ring-awp-blue"
              />
              Code mode
            </label>
            <label className="flex items-center gap-2 text-xs text-awp-text cursor-pointer">
              <input
                type="checkbox"
                checked={config.tool_creation}
                onChange={(e) =>
                  updateConfig({ tool_creation: e.target.checked })
                }
                disabled={isRunning}
                className="rounded border-awp-border bg-awp-bg text-awp-blue focus:ring-awp-blue"
              />
              Tool creation
            </label>
            <label className="flex items-center gap-2 text-xs text-awp-text cursor-pointer">
              <input
                type="checkbox"
                checked={config.verbose}
                onChange={(e) =>
                  updateConfig({ verbose: e.target.checked })
                }
                disabled={isRunning}
                className="rounded border-awp-border bg-awp-bg text-awp-blue focus:ring-awp-blue"
              />
              Verbose
            </label>
          </div>
        </div>
      </Panel>

      {/* Secrets */}
      <Panel
        title="Secrets"
        icon={<Key className="h-4 w-4 text-awp-yellow" />}
        defaultOpen={false}
      >
        <SecretsPanel
          secrets={secrets}
          onAdd={addSecret}
          onDelete={removeSecret}
        />
      </Panel>
    </aside>
  );
}

// We need the WorkflowConfig type for the sandbox select
import type { WorkflowConfig } from '@/types';

// ---------------------------------------------------------------------------
// Output Panel
// ---------------------------------------------------------------------------

function OutputPanel() {
  const { outputBlocks, runStatus } = useWorkflowStore();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [outputBlocks.length]);

  if (outputBlocks.length === 0 && runStatus === 'idle') {
    return (
      <div className="flex flex-col items-center justify-center h-full text-awp-muted gap-3">
        <Zap className="h-12 w-12 text-awp-border" />
        <p className="text-sm">Enter a task and click Run to begin</p>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-4 space-y-3">
      {outputBlocks.map((block, i) => (
        <OutputBlockCard key={i} block={block} />
      ))}
      <div ref={bottomRef} />
    </div>
  );
}

function OutputBlockCard({ block }: { block: OutputBlock }) {
  const bgClass =
    block.type === 'error'
      ? 'border-awp-red/30 bg-awp-red/5'
      : 'border-awp-border bg-awp-bg';

  return (
    <div
      className={clsx(
        'rounded-lg border p-4 animate-fade-in',
        bgClass,
      )}
    >
      {block.title && (
        <div className="flex items-center gap-2 mb-2">
          {block.type === 'error' && (
            <AlertCircle className="h-4 w-4 text-awp-red shrink-0" />
          )}
          <span className="text-xs font-medium text-awp-muted uppercase tracking-wider">
            {block.title}
          </span>
        </div>
      )}
      {block.type === 'markdown' && (
        <div className="prose prose-sm max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>
            {block.content}
          </ReactMarkdown>
        </div>
      )}
      {block.type === 'code' && (
        <pre className="text-sm overflow-x-auto">
          <code>{block.content}</code>
        </pre>
      )}
      {block.type === 'json' && (
        <pre className="text-sm overflow-x-auto">
          <code className="text-awp-cyan">{block.content}</code>
        </pre>
      )}
      {block.type === 'error' && (
        <p className="text-sm text-awp-red whitespace-pre-wrap">
          {block.content}
        </p>
      )}
      {block.type === 'image' && (
        <img
          src={block.content}
          alt={block.title ?? 'output'}
          className="max-w-full rounded"
        />
      )}
      {(block.type === 'table' || block.type === 'chart' || block.type === 'file') && (
        <pre className="text-sm overflow-x-auto">
          <code>{block.content}</code>
        </pre>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Graph Panel (placeholder -- requires reactflow setup)
// ---------------------------------------------------------------------------

function GraphPanel() {
  const { graphNodes, graphEdges, selectNode } = useWorkflowStore();

  if (graphNodes.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-awp-muted gap-3">
        <GitBranch className="h-12 w-12 text-awp-border" />
        <p className="text-sm">Agent graph will appear here during a run</p>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-4">
      <div className="space-y-2">
        {graphNodes.map((node) => {
          const data = node.data as Record<string, unknown>;
          const status = (data.status as string) ?? 'pending';
          const nodeType = (data.nodeType as string) ?? 'task';
          const label = (data.label as string) ?? node.id;

          return (
            <button
              key={node.id}
              type="button"
              onClick={() => selectNode(node.id)}
              className={clsx(
                'w-full text-left rounded-lg border p-3 transition-colors',
                'hover:bg-awp-bg/60',
                status === 'running' && 'border-awp-blue/50 glow-blue',
                status === 'complete' && 'border-awp-green/50',
                status === 'error' && 'border-awp-red/50',
                status === 'pending' && 'border-awp-border',
              )}
            >
              <div className="flex items-center gap-2">
                {nodeType === 'manager' && (
                  <Cpu className="h-4 w-4 text-awp-purple shrink-0" />
                )}
                {nodeType === 'worker' && (
                  <Users className="h-4 w-4 text-awp-blue shrink-0" />
                )}
                {nodeType === 'toolCall' && (
                  <Wrench className="h-4 w-4 text-awp-orange shrink-0" />
                )}
                {nodeType === 'task' && (
                  <CircleDot className="h-4 w-4 text-awp-cyan shrink-0" />
                )}
                <span className="text-sm font-medium text-awp-text truncate">
                  {label}
                </span>
                <Badge
                  variant={statusVariant(status)}
                  className="ml-auto shrink-0"
                >
                  {status}
                </Badge>
              </div>
              {data.confidence !== undefined && (
                <ProgressBar
                  value={data.confidence as number}
                  color={
                    (data.confidence as number) >= 0.8
                      ? 'bg-awp-green'
                      : (data.confidence as number) >= 0.5
                        ? 'bg-awp-yellow'
                        : 'bg-awp-red'
                  }
                  showLabel
                  className="mt-2"
                />
              )}
            </button>
          );
        })}
      </div>
      {/* Edge list (compact) */}
      {graphEdges.length > 0 && (
        <div className="mt-4 text-xs text-awp-muted">
          <p className="font-medium mb-1">Edges ({graphEdges.length})</p>
          {graphEdges.map((e) => (
            <div key={e.id} className="flex items-center gap-1">
              <span>{e.source}</span>
              <span className="text-awp-border">&rarr;</span>
              <span>{e.target}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// History Panel
// ---------------------------------------------------------------------------

function HistoryPanel() {
  const { runHistory, loadHistory } = useWorkflowStore();

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  if (runHistory.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-awp-muted gap-3">
        <History className="h-12 w-12 text-awp-border" />
        <p className="text-sm">No previous runs</p>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-4 space-y-2">
      {runHistory.map((entry) => (
        <div
          key={entry.id}
          className="rounded-lg border border-awp-border bg-awp-bg p-3"
        >
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs font-mono text-awp-muted">
              {entry.id.slice(0, 8)}
            </span>
            <Badge variant={statusVariant(entry.status)}>{entry.status}</Badge>
          </div>
          <p className="text-sm text-awp-text line-clamp-2">{entry.task}</p>
          <div className="flex items-center gap-2 mt-2 text-xs text-awp-muted">
            <Clock className="h-3 w-3" />
            {new Date(entry.created_at).toLocaleString()}
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Inspector Panel
// ---------------------------------------------------------------------------

function InspectorPanel() {
  const { selectedNodeId, graphNodes } = useWorkflowStore();
  const node = graphNodes.find((n) => n.id === selectedNodeId);

  if (!node) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-awp-muted gap-3 p-4">
        <Settings className="h-8 w-8 text-awp-border" />
        <p className="text-xs text-center">Select a node in the graph to inspect its details</p>
      </div>
    );
  }

  const data = node.data as Record<string, unknown>;

  return (
    <div className="h-full overflow-y-auto p-3 space-y-3">
      <div>
        <h3 className="text-sm font-semibold text-awp-text">
          {(data.label as string) ?? node.id}
        </h3>
        <Badge variant={statusVariant((data.status as string) ?? 'pending')} className="mt-1">
          {(data.status as string) ?? 'pending'}
        </Badge>
      </div>

      {data.confidence !== undefined && (
        <div>
          <span className="text-xs text-awp-muted">Confidence</span>
          <ProgressBar
            value={data.confidence as number}
            showLabel
            color="bg-awp-green"
            className="mt-1"
          />
        </div>
      )}

      {Array.isArray(data.tools_used) && (
        <div>
          <span className="text-xs text-awp-muted">Tools</span>
          <div className="flex flex-wrap gap-1 mt-1">
            {(data.tools_used as string[]).map((t: string) => (
              <Badge key={t} variant="orange">
                {t}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {typeof data.error === 'string' && (
        <div className="rounded border border-awp-red/30 bg-awp-red/5 p-2 text-xs text-awp-red">
          {String(data.error)}
        </div>
      )}

      {data.inputs != null && (
        <Panel title="Inputs">
          <pre className="text-xs overflow-x-auto text-awp-text">
            {JSON.stringify(data.inputs, null, 2)}
          </pre>
        </Panel>
      )}

      {data.outputs != null && (
        <Panel title="Outputs">
          <pre className="text-xs overflow-x-auto text-awp-text">
            {JSON.stringify(data.outputs, null, 2)}
          </pre>
        </Panel>
      )}

      {data.details != null && typeof data.details === 'object' && Object.keys(data.details as object).length > 0 && (
        <Panel title="Details">
          <pre className="text-xs overflow-x-auto text-awp-text">
            {JSON.stringify(data.details, null, 2)}
          </pre>
        </Panel>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Bottom Bar
// ---------------------------------------------------------------------------

function BottomBar() {
  const { currentRunId, _wsStatus, events, budget } =
    useWorkflowStore();

  const isConnected = _wsStatus === 'open';
  const elapsed = budget.wall_time_ms > 0
    ? (budget.wall_time_ms / 1000).toFixed(1) + 's'
    : '--';

  return (
    <footer className="flex items-center gap-3 border-t border-awp-border bg-awp-panel px-3 h-7 text-xs text-awp-muted shrink-0">
      {/* Connection status */}
      <span className="flex items-center gap-1">
        {isConnected ? (
          <Wifi className="h-3 w-3 text-awp-green" />
        ) : (
          <WifiOff className="h-3 w-3 text-awp-muted" />
        )}
        {_wsStatus}
      </span>

      {/* Run ID */}
      {currentRunId && (
        <span className="font-mono">
          Run: {currentRunId.slice(0, 12)}
        </span>
      )}

      {/* Events count */}
      <span>{events.length} events</span>

      <div className="flex-1" />

      {/* Timing */}
      <span className="flex items-center gap-1">
        <Clock className="h-3 w-3" />
        {elapsed}
      </span>
    </footer>
  );
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

export function App() {
  const {
    sidebarOpen,
    inspectorOpen,
    activePanel,
    sessions,
    currentSessionId,
    selectSession,
    createSession,
    deleteSession,
    renameSession,
    loadSessions,
    loadSecrets,
    loadPersistedSettings,
    saveCurrentSettings,
    config,
  } = useWorkflowStore();

  // Load sessions, secrets, and persisted settings on mount
  useEffect(() => {
    loadSessions();
    loadSecrets();
    loadPersistedSettings();
  }, [loadSessions, loadSecrets, loadPersistedSettings]);

  // Auto-save settings with debounce when config changes (excluding task)
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isFirstRender = useRef(true);
  useEffect(() => {
    // Skip saving on initial render
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }
    if (saveTimerRef.current) {
      clearTimeout(saveTimerRef.current);
    }
    saveTimerRef.current = setTimeout(() => {
      saveCurrentSettings();
    }, 1500);
    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    };
  }, [
    config.model,
    config.worker_model,
    config.max_loops,
    config.max_total_tokens,
    config.max_wall_time,
    config.max_tool_calls,
    config.max_total_workers,
    config.max_depth,
    config.sandbox,
    config.code_mode,
    config.tool_creation,
    config.verbose,
    saveCurrentSettings,
  ]);

  const handleNewSession = useCallback(() => {
    createSession();
  }, [createSession]);

  return (
    <div className="flex flex-col h-screen bg-awp-bg text-awp-text">
      <TopBar />
      <div className="flex flex-1 overflow-hidden">
        {/* Session sidebar */}
        <div className="w-60 shrink-0 border-r border-awp-border bg-awp-panel overflow-hidden">
          <SessionSidebar
            sessions={sessions}
            currentSessionId={currentSessionId}
            onSelectSession={selectSession}
            onNewSession={handleNewSession}
            onDeleteSession={deleteSession}
            onRenameSession={renameSession}
          />
        </div>

        {/* Left config sidebar */}
        {sidebarOpen && (
          <div className="w-80 shrink-0 border-r border-awp-border bg-awp-panel overflow-hidden animate-slide-in-left">
            <LeftSidebar />
          </div>
        )}

        {/* Main content */}
        <main className="flex-1 min-w-0 overflow-hidden">
          {activePanel === 'output' && <OutputPanel />}
          {activePanel === 'graph' && <GraphPanel />}
          {activePanel === 'history' && <HistoryPanel />}
          {activePanel === 'settings' && (
            <div className="p-4 text-awp-muted text-sm">
              Settings are available in the left sidebar.
            </div>
          )}
        </main>

        {/* Right inspector */}
        {inspectorOpen && (
          <div className="w-72 shrink-0 border-l border-awp-border bg-awp-panel overflow-hidden animate-slide-in-right">
            <InspectorPanel />
          </div>
        )}
      </div>
      <BottomBar />
    </div>
  );
}
