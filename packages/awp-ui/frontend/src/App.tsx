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
  LayoutDashboard,
  FolderOpen,
  Upload,
  Trash2,
  Cpu,
  Zap,
  Clock,
  Users,
  Wrench,
  ChevronDown,
  ChevronRight,
  Wifi,
  WifiOff,
  CircleDot,
  AlertCircle,
  CheckCircle2,
  Loader2,
  Key,
  Network,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { useWorkflowStore } from '@/stores/workflowStore';
import * as api from '@/api/client';
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
import { GraphVisPanel } from '@/components/AgentGraph/GraphVisPanel';

// ---------------------------------------------------------------------------
// Code block with syntax highlighting
// ---------------------------------------------------------------------------

/** Detect language from file extension or content */
function detectLang(content: string, filename?: string): string {
  if (filename) {
    const ext = filename.split('.').pop()?.toLowerCase();
    if (ext === 'py') return 'python';
    if (ext === 'js') return 'javascript';
    if (ext === 'ts' || ext === 'tsx') return 'typescript';
    if (ext === 'json') return 'json';
    if (ext === 'yaml' || ext === 'yml') return 'yaml';
    if (ext === 'sh' || ext === 'bash') return 'bash';
    if (ext === 'html' || ext === 'htm') return 'html';
    if (ext === 'css') return 'css';
    if (ext === 'sql') return 'sql';
    if (ext === 'md') return 'markdown';
  }
  // Auto-detect from content
  const trimmed = content.trimStart();
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) return 'json';
  if (trimmed.startsWith('import ') || trimmed.startsWith('def ') || trimmed.startsWith('class ') || trimmed.includes('print(')) return 'python';
  if (trimmed.startsWith('function ') || trimmed.startsWith('const ') || trimmed.startsWith('let ')) return 'javascript';
  if (trimmed.startsWith('---')) return 'yaml';
  if (trimmed.startsWith('SELECT ') || trimmed.startsWith('CREATE ')) return 'sql';
  return 'text';
}

function CodeBlock({ content, language, filename, maxHeight = '24rem' }: {
  content: string;
  language?: string;
  filename?: string;
  maxHeight?: string;
}) {
  const lang = language ?? detectLang(content, filename);
  return (
    <div className="rounded-md overflow-hidden border border-awp-border">
      {filename ? (
        <div className="px-3 py-1 bg-awp-panel border-b border-awp-border text-[10px] text-awp-muted font-mono">
          {filename}
        </div>
      ) : null}
      <div style={{ maxHeight }} className="overflow-y-auto">
        <SyntaxHighlighter
          language={lang}
          style={oneDark}
          customStyle={{
            margin: 0,
            padding: '0.75rem',
            background: '#0d1117',
            fontSize: '0.75rem',
            lineHeight: '1.5',
          }}
          wrapLines
          wrapLongLines
        >
          {content}
        </SyntaxHighlighter>
      </div>
    </div>
  );
}

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
    budget,
    activePanel,
    setActivePanel,
    sidebarOpen,
    toggleSidebar,
    inspectorOpen,
    toggleInspector,
    currentSessionId,
    sessions,
  } = useWorkflowStore();

  const currentSession = sessions.find((s) => s.id === currentSessionId);

  const isRunning = runStatus === 'running';

  const tabs = [
    { id: 'state' as const, label: 'State', icon: <LayoutDashboard className="h-4 w-4" /> },
    { id: 'final' as const, label: 'Final', icon: <FolderOpen className="h-4 w-4" /> },
    { id: 'output' as const, label: 'Output', icon: <FileText className="h-4 w-4" /> },
    { id: 'graph' as const, label: 'Graph', icon: <GitBranch className="h-4 w-4" /> },
    { id: 'graphvis' as const, label: 'Graph Vis', icon: <Network className="h-4 w-4" /> },
    { id: 'history' as const, label: 'History', icon: <History className="h-4 w-4" /> },
  ];

  const tokensPercent = budget.tokens_max > 0 ? budget.tokens_used / budget.tokens_max : 0;
  const loopsPercent = budget.loops_max > 0 ? budget.loops_used / budget.loops_max : 0;

  return (
    <header className="flex items-center gap-2 border-b border-awp-border bg-awp-panel px-3 h-12 shrink-0">
      {/* Sidebar toggle */}
      <IconButton tooltip="Toggle sessions" onClick={toggleSidebar} size="sm">
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

      {/* Settings toggle */}
      <IconButton tooltip="Toggle settings" onClick={toggleInspector} size="sm">
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

// We need the WorkflowConfig type for the sandbox select
import type { WorkflowConfig } from '@/types';

// ---------------------------------------------------------------------------
// Task Input Bar (bottom center)
// ---------------------------------------------------------------------------

function TaskInputBar() {
  const {
    config,
    updateConfig,
    attachedFiles,
    addFiles,
    removeFile,
    runStatus,
    startRun,
    stopRun,
  } = useWorkflowStore();

  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files) {
        addFiles(Array.from(e.target.files));
        e.target.value = '';
      }
    },
    [addFiles],
  );

  const isRunning = runStatus === 'running';
  const canStart = config.task.trim().length > 0 && !isRunning;

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey && canStart) {
        e.preventDefault();
        startRun();
      }
    },
    [canStart, startRun],
  );

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = 'auto';
      el.style.height = Math.min(el.scrollHeight, 300) + 'px';
    }
  }, [config.task]);

  return (
    <div className="border-t border-awp-border bg-awp-panel px-4 py-3 shrink-0">
      {/* Attached files */}
      {attachedFiles.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-2 max-w-3xl mx-auto">
          {attachedFiles.map((f, i) => (
            <span
              key={`${f.name}-${i}`}
              className="inline-flex items-center gap-1 rounded-md bg-awp-bg border border-awp-border px-2 py-0.5 text-xs text-awp-text"
            >
              <Upload className="h-3 w-3 text-awp-muted shrink-0" />
              <span className="truncate max-w-[120px]">{f.name}</span>
              <button
                type="button"
                onClick={() => removeFile(i)}
                className="text-awp-muted hover:text-awp-red transition-colors ml-0.5 shrink-0"
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Input row */}
      <div className="flex items-end gap-2 max-w-3xl mx-auto">
        {/* File attach button */}
        <label
          className={clsx(
            'inline-flex items-center justify-center h-8 w-8 rounded-md transition-colors cursor-pointer shrink-0',
            'text-awp-muted hover:text-awp-text hover:bg-awp-border/50',
            isRunning && 'opacity-40 pointer-events-none',
          )}
          title="Attach files"
        >
          <Upload className="h-4 w-4" />
          <input
            ref={fileInputRef}
            type="file"
            multiple
            onChange={handleFileChange}
            disabled={isRunning}
            className="sr-only"
          />
        </label>

        {/* Textarea */}
        <div className="flex-1 relative">
          <textarea
            ref={textareaRef}
            value={config.task}
            onChange={(e) => updateConfig({ task: e.target.value })}
            onKeyDown={handleKeyDown}
            placeholder="Describe the task for the agent workflow..."
            disabled={isRunning}
            rows={3}
            className={clsx(
              'w-full resize-none rounded-lg border border-awp-border bg-awp-bg px-3 py-2.5 pr-10',
              'text-sm text-awp-text placeholder:text-awp-muted/60',
              'focus:outline-none focus:ring-1 focus:ring-awp-blue focus:border-awp-blue',
              'disabled:opacity-50 disabled:cursor-not-allowed',
            )}
          />
        </div>

        {/* Run / Stop button */}
        {isRunning ? (
          <button
            type="button"
            onClick={stopRun}
            className="inline-flex items-center justify-center h-9 w-9 rounded-lg bg-awp-red/15 text-awp-red hover:bg-awp-red/25 transition-colors shrink-0"
          >
            <Square className="h-4 w-4" />
          </button>
        ) : (
          <button
            type="button"
            onClick={startRun}
            disabled={!canStart}
            className={clsx(
              'inline-flex items-center justify-center h-9 w-9 rounded-lg transition-colors shrink-0',
              canStart
                ? 'bg-awp-blue/15 text-awp-blue hover:bg-awp-blue/25'
                : 'bg-awp-border/30 text-awp-muted cursor-not-allowed',
            )}
          >
            <Play className="h-4 w-4" />
          </button>
        )}
      </div>

      <p className="text-center text-[10px] text-awp-muted/50 mt-1.5 max-w-3xl mx-auto">
        Enter to run &middot; Shift+Enter for new line
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Right Sidebar (Settings + Inspector)
// ---------------------------------------------------------------------------

function RightSidebar() {
  const {
    config,
    updateConfig,
    runStatus,
    secrets,
    addSecret,
    removeSecret,
    selectedNodeId,
    graphNodes,
  } = useWorkflowStore();

  const isRunning = runStatus === 'running';
  const selectedNode = graphNodes.find((n) => n.id === selectedNodeId);

  return (
    <aside className="flex flex-col gap-3 h-full overflow-y-auto p-3">
      {/* Model settings */}
      <Panel
        title="Settings"
        icon={<Settings className="h-4 w-4 text-awp-green" />}
      >
        <div className="space-y-3">
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

          {/* Output directory */}
          <label className="block">
            <span className="text-xs text-awp-muted">Output directory</span>
            <input
              type="text"
              value={config.output_dir}
              onChange={(e) => updateConfig({ output_dir: e.target.value })}
              disabled={isRunning}
              placeholder="/tmp/awp-output"
              className="mt-1 w-full rounded-md border border-awp-border bg-awp-bg px-2.5 py-1.5 text-sm text-awp-text placeholder:text-awp-muted/50 focus:outline-none focus:ring-1 focus:ring-awp-blue disabled:opacity-50"
            />
          </label>
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

      {/* Inspector (shown when a node is selected) */}
      {selectedNode && (
        <Panel
          title="Inspector"
          icon={<Cpu className="h-4 w-4 text-awp-purple" />}
        >
          <InspectorContent node={selectedNode} />
        </Panel>
      )}
    </aside>
  );
}

function InspectorContent({ node }: { node: { id: string; data: Record<string, unknown> } }) {
  const data = node.data;
  const status = (data.status as string) ?? 'pending';

  return (
    <div className="space-y-3">
      <div>
        <h3 className="text-sm font-semibold text-awp-text">
          {(data.label as string) ?? node.id}
        </h3>
        <Badge variant={statusVariant(status)} className="mt-1">
          {status}
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
        <div>
          <span className="text-xs text-awp-muted">Inputs</span>
          <div className="mt-1">
            <CodeBlock content={JSON.stringify(data.inputs, null, 2)} language="json" maxHeight="12rem" />
          </div>
        </div>
      )}

      {data.outputs != null && (
        <div>
          <span className="text-xs text-awp-muted">Outputs</span>
          <div className="mt-1">
            <CodeBlock content={JSON.stringify(data.outputs, null, 2)} language="json" maxHeight="12rem" />
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// State Panel — final result + run status overview
// ---------------------------------------------------------------------------

function StatePanel() {
  const { currentRunId, runStatus, outputBlocks, budget } = useWorkflowStore();

  const finalResult = outputBlocks.find((b) => b.title === 'Final Result' || b.title === 'Agent Result');
  const errorBlock = outputBlocks.find((b) => b.type === 'error');

  if (!currentRunId && !finalResult) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-awp-muted gap-3">
        <LayoutDashboard className="h-12 w-12 text-awp-border" />
        <p className="text-sm">Run status will appear here</p>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-4 space-y-4">
      {/* Running indicator */}
      {runStatus === 'running' ? (
        <div className="flex items-center gap-2 text-awp-blue text-sm">
          <Loader2 className="h-4 w-4 animate-spin" /> Running...
        </div>
      ) : null}

      {/* Final result */}
      {finalResult ? (
        <div className="rounded-lg border border-awp-green/30 bg-awp-green/5 p-4">
          <div className="flex items-center gap-2 mb-2">
            <CheckCircle2 className="h-4 w-4 text-awp-green shrink-0" />
            <span className="text-xs font-medium text-awp-muted uppercase tracking-wider">
              {finalResult.title}
            </span>
          </div>
          {finalResult.type === 'markdown' ? (
            <div className="prose prose-sm prose-invert max-w-none break-words">
              <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>
                {finalResult.content}
              </ReactMarkdown>
            </div>
          ) : (
            <CodeBlock content={finalResult.content} language="json" />
          )}
        </div>
      ) : null}

      {/* Error */}
      {errorBlock && !finalResult ? (
        <div className="rounded-lg border border-awp-red/30 bg-awp-red/5 p-4">
          <div className="flex items-center gap-2 mb-2">
            <AlertCircle className="h-4 w-4 text-awp-red shrink-0" />
            <span className="text-xs font-medium text-awp-muted uppercase tracking-wider">Error</span>
          </div>
          <p className="text-sm text-awp-red whitespace-pre-wrap break-words">{errorBlock.content}</p>
        </div>
      ) : null}

      {/* Budget summary */}
      {(budget.loops_used > 0 || budget.tokens_used > 0) ? (
        <div className="rounded-lg border border-awp-border bg-awp-bg p-4">
          <span className="text-xs font-medium text-awp-muted uppercase tracking-wider block mb-3">Budget</span>
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div>
              <span className="text-awp-muted">Iterations</span>
              <p className="text-awp-text font-mono">{budget.loops_used} / {budget.loops_max}</p>
              <ProgressBar value={budget.loops_max > 0 ? budget.loops_used / budget.loops_max : 0} className="mt-1" />
            </div>
            <div>
              <span className="text-awp-muted">Tokens</span>
              <p className="text-awp-text font-mono">{(budget.tokens_used / 1000).toFixed(1)}k / {(budget.tokens_max / 1000).toFixed(0)}k</p>
              <ProgressBar value={budget.tokens_max > 0 ? budget.tokens_used / budget.tokens_max : 0} className="mt-1" />
            </div>
            <div>
              <span className="text-awp-muted">Workers</span>
              <p className="text-awp-text font-mono">{budget.workers_used} / {budget.workers_max}</p>
            </div>
            <div>
              <span className="text-awp-muted">Wall time</span>
              <p className="text-awp-text font-mono">{(budget.wall_time_ms / 1000).toFixed(1)}s / {(budget.wall_time_max_ms / 1000).toFixed(0)}s</p>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Final Panel — all output artifacts (images, tables, HTML, text, code, data)
// ---------------------------------------------------------------------------

function FinalPanel() {
  const { currentRunId, runStatus } = useWorkflowStore();
  const [artifacts, setArtifacts] = React.useState<Array<{
    name: string; path: string; relative: string; kind: string; size: number;
  }>>([]);
  const [textContents, setTextContents] = React.useState<Record<string, string>>({});
  const [loading, setLoading] = React.useState(false);

  useEffect(() => {
    if (!currentRunId) return;
    setLoading(true);
    api.getRunArtifacts(currentRunId).then((arts) => {
      setArtifacts(arts);
      const textArts = arts.filter((a) => ['text', 'code', 'table'].includes(a.kind));
      Promise.all(
        textArts.map((a) =>
          fetch(api.fileServeUrl(a.path)).then((r) => r.text()).then((txt) => [a.path, txt] as const)
        )
      ).then((entries) => {
        setTextContents(Object.fromEntries(entries));
      });
    }).catch(() => {}).finally(() => setLoading(false));
  }, [currentRunId, runStatus]);

  if (!currentRunId) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-awp-muted gap-3">
        <FolderOpen className="h-12 w-12 text-awp-border" />
        <p className="text-sm">Final outputs will appear here after a run</p>
      </div>
    );
  }

  const images = artifacts.filter((a) => a.kind === 'image');
  const tables = artifacts.filter((a) => a.kind === 'table');
  const htmlFiles = artifacts.filter((a) => a.kind === 'html');
  const textFiles = artifacts.filter((a) => a.kind === 'text');
  const codeFiles = artifacts.filter((a) => a.kind === 'code');

  return (
    <div className="h-full overflow-y-auto p-4 space-y-4">
      {loading ? (
        <div className="flex items-center gap-2 text-awp-muted text-sm">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading artifacts...
        </div>
      ) : null}

      {/* Images */}
      {images.length > 0 ? (
        <div>
          <h3 className="text-xs font-medium text-awp-muted uppercase tracking-wider mb-2">
            Images ({images.length})
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {images.map((img) => {
              const url = `/api/files/serve?path=${encodeURIComponent(img.path)}`;
              return (
                <div key={img.path} className="rounded-lg border border-awp-border bg-awp-bg p-2">
                  <img src={url} alt={img.name} className="max-w-full rounded" />
                  <p className="text-[10px] text-awp-muted mt-1 truncate">{img.relative}</p>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      {/* HTML visualizations */}
      {htmlFiles.length > 0 ? (
        <div>
          <h3 className="text-xs font-medium text-awp-muted uppercase tracking-wider mb-2">
            Visualizations ({htmlFiles.length})
          </h3>
          {htmlFiles.map((f) => {
            const url = `/api/files/serve?path=${encodeURIComponent(f.path)}`;
            return (
              <div key={f.path} className="rounded-lg border border-awp-border bg-awp-bg overflow-hidden mb-3">
                <div className="px-3 py-1.5 border-b border-awp-border flex items-center justify-between">
                  <span className="text-xs text-awp-muted truncate">{f.name}</span>
                  <a href={url} target="_blank" rel="noopener noreferrer" className="text-[10px] text-awp-blue hover:underline">Open</a>
                </div>
                <iframe src={url} className="w-full h-96 border-0" title={f.name} sandbox="allow-scripts" />
              </div>
            );
          })}
        </div>
      ) : null}

      {/* Tables (CSV/TSV) */}
      {tables.length > 0 ? (
        <div>
          <h3 className="text-xs font-medium text-awp-muted uppercase tracking-wider mb-2">
            Tables ({tables.length})
          </h3>
          {tables.map((f) => {
            const content = textContents[f.path] ?? '';
            const rows = content.split('\n').filter(Boolean);
            const header = rows[0]?.split(',') ?? [];
            const dataRows = rows.slice(1, 101);
            return (
              <div key={f.path} className="rounded-lg border border-awp-border bg-awp-bg overflow-hidden mb-3">
                <div className="px-3 py-1.5 border-b border-awp-border">
                  <span className="text-xs text-awp-muted">{f.name} ({rows.length - 1} rows)</span>
                </div>
                <div className="overflow-x-auto max-h-96">
                  <table className="w-full text-xs">
                    <thead className="bg-awp-panel sticky top-0">
                      <tr>
                        {header.map((h, i) => (
                          <th key={i} className="px-2 py-1.5 text-left text-awp-muted font-medium border-b border-awp-border whitespace-nowrap">{h.trim()}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {dataRows.map((row, i) => (
                        <tr key={i} className="hover:bg-awp-bg/60">
                          {row.split(',').map((cell, j) => (
                            <td key={j} className="px-2 py-1 text-awp-text border-b border-awp-border/50 whitespace-nowrap">{cell.trim()}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {rows.length > 101 ? (
                  <div className="px-3 py-1 text-[10px] text-awp-muted border-t border-awp-border">Showing first 100 of {rows.length - 1} rows</div>
                ) : null}
              </div>
            );
          })}
        </div>
      ) : null}

      {/* Documents (Markdown / text / JSON / YAML) */}
      {textFiles.length > 0 ? (
        <div>
          <h3 className="text-xs font-medium text-awp-muted uppercase tracking-wider mb-2">
            Documents ({textFiles.length})
          </h3>
          {textFiles.map((f) => {
            const content = textContents[f.path] ?? '';
            const isMd = f.name.endsWith('.md');

            return (
              <div key={f.path} className="rounded-lg border border-awp-border bg-awp-bg p-3 mb-3">
                <span className="text-xs text-awp-muted block mb-2">{f.relative}</span>
                {isMd ? (
                  <div className="prose prose-sm prose-invert max-w-none break-words">
                    <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>
                      {content}
                    </ReactMarkdown>
                  </div>
                ) : (
                  <CodeBlock content={content} filename={f.name} maxHeight="20rem" />
                )}
              </div>
            );
          })}
        </div>
      ) : null}

      {/* Code files */}
      {codeFiles.length > 0 ? (
        <div>
          <h3 className="text-xs font-medium text-awp-muted uppercase tracking-wider mb-2">
            Code ({codeFiles.length})
          </h3>
          {codeFiles.map((f) => {
            const content = textContents[f.path] ?? '';
            return (
              <div key={f.path} className="mb-3">
                <CodeBlock content={content} filename={f.relative} maxHeight="24rem" />
              </div>
            );
          })}
        </div>
      ) : null}

      {/* Empty state */}
      {!loading && artifacts.length === 0 && runStatus !== 'running' ? (
        <div className="text-center text-awp-muted text-sm mt-8">
          No artifacts generated by this run
        </div>
      ) : null}
    </div>
  );
}

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
        <div className="prose prose-sm prose-invert max-w-none break-words">
          <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>
            {block.content}
          </ReactMarkdown>
        </div>
      )}
      {block.type === 'code' && (
        <CodeBlock content={block.content} />
      )}
      {block.type === 'json' && (
        <CodeBlock content={block.content} language="json" />
      )}
      {block.type === 'error' && (
        <p className="text-sm text-awp-red whitespace-pre-wrap break-words">
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
        <pre className="text-sm whitespace-pre-wrap break-words">
          <code>{block.content}</code>
        </pre>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Graph Panel — hierarchical agent tree
// ---------------------------------------------------------------------------

// Local types matching the store's Node/Edge shape
type GraphNode = { id: string; type?: string; data: Record<string, unknown>; position?: { x: number; y: number } };
type GraphEdge = { id: string; source: string; target: string };

/** Map node type to icon */
function nodeIcon(nodeType: string) {
  switch (nodeType) {
    case 'manager':    return <Cpu className="h-4 w-4 text-awp-purple shrink-0" />;
    case 'worker':     return <Users className="h-4 w-4 text-awp-blue shrink-0" />;
    case 'toolCall':   return <Wrench className="h-4 w-4 text-awp-orange shrink-0" />;
    case 'iteration':  return <RotateCcw className="h-4 w-4 text-awp-yellow shrink-0" />;
    case 'completion': return <CheckCircle2 className="h-4 w-4 text-awp-green shrink-0" />;
    default:           return <CircleDot className="h-4 w-4 text-awp-cyan shrink-0" />;
  }
}

/** Build parent→children map from edges */
function buildTree(
  nodes: GraphNode[],
  edges: GraphEdge[],
): { roots: string[]; children: Record<string, string[]> } {
  const childMap: Record<string, string[]> = {};
  const hasParent = new Set<string>();
  for (const e of edges) {
    if (!childMap[e.source]) childMap[e.source] = [];
    childMap[e.source].push(e.target);
    hasParent.add(e.target);
  }
  const roots = nodes.filter((n) => !hasParent.has(n.id)).map((n) => n.id);
  return { roots, children: childMap };
}

/** Expandable detail row */
function DetailRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mt-1">
      <span className="text-[10px] uppercase tracking-wider text-awp-muted font-medium">{label}</span>
      <div className="mt-0.5 text-xs text-awp-text">{children}</div>
    </div>
  );
}

/** Single graph tree node */
function GraphTreeNode({
  nodeId,
  nodes,
  childMap,
  depth,
}: {
  nodeId: string;
  nodes: Map<string, GraphNode>;
  childMap: Record<string, string[]>;
  depth: number;
}): React.ReactElement | null {
  const [expanded, setExpanded] = React.useState(true);
  const node = nodes.get(nodeId);
  if (!node) return null;

  const data = node.data;
  const status = (data.status as string) ?? 'pending';
  const nodeType = (data.nodeType as string) ?? node.type ?? 'task';
  const label = (data.label as string) ?? nodeId;
  const confidence = data.confidence as number | undefined;
  const reasoning = data.reasoning as string | undefined;
  const decision = data.decision as string | undefined;
  const details = data.details as Record<string, unknown> | undefined;
  const outputs = data.outputs as Record<string, unknown> | undefined;
  const error = data.error as string | undefined;
  const toolsUsed: string[] = Array.isArray(data.tools_used) ? data.tools_used.map(String) : [];
  const toolsCreated: string[] = Array.isArray(data.tools_created) ? data.tools_created.map(String) : [];
  const instructions = data.instructions as string | undefined;
  const delegations = data.delegations as Array<Record<string, unknown>> | undefined;
  const toolArgs = data.arguments as Record<string, unknown> | undefined;
  const iteration = data.iteration as string | undefined;
  const kids = childMap[nodeId] ?? [];
  const hasKids = kids.length > 0;

  // Indent based on depth
  const indent = depth * 20;

  return (
    <div style={{ marginLeft: indent }}>
      {/* Node header */}
      <div
        className={clsx(
          'rounded-lg border p-2.5 mb-1.5 transition-colors',
          status === 'running' && 'border-awp-blue/50 bg-awp-blue/5',
          status === 'complete' && 'border-awp-green/30 bg-awp-green/5',
          status === 'error' && 'border-awp-red/30 bg-awp-red/5',
          status === 'pending' && 'border-awp-border bg-awp-bg',
        )}
      >
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="w-full text-left"
        >
          <div className="flex items-center gap-2">
            {/* Expand/collapse */}
            {hasKids ? (
              expanded
                ? <ChevronDown className="h-3.5 w-3.5 text-awp-muted shrink-0" />
                : <ChevronRight className="h-3.5 w-3.5 text-awp-muted shrink-0" />
            ) : (
              <span className="w-3.5 shrink-0" />
            )}
            {nodeIcon(nodeType)}
            <span className="text-xs font-medium text-awp-text truncate flex-1">
              {label}
            </span>
            {status === 'running' && <Loader2 className="h-3 w-3 text-awp-blue animate-spin shrink-0" />}
            <Badge variant={statusVariant(status)} className="shrink-0 text-[10px]">
              {status}
            </Badge>
          </div>
        </button>

        {/* Expanded details */}
        {expanded && (
          <div className="mt-2 ml-9 space-y-1">
            {/* Confidence bar */}
            {confidence !== undefined && (
              <DetailRow label="Confidence">
                <ProgressBar
                  value={confidence}
                  color={confidence >= 0.8 ? 'bg-awp-green' : confidence >= 0.5 ? 'bg-awp-yellow' : 'bg-awp-red'}
                  showLabel
                />
              </DetailRow>
            )}

            {/* Decision + reasoning (iterations) */}
            {decision && (
              <DetailRow label="Decision">
                <Badge variant={decision === 'complete' ? 'green' : decision === 'delegate' ? 'blue' : 'yellow'} className="text-[10px]">
                  {decision}
                </Badge>
              </DetailRow>
            )}
            {reasoning && (
              <DetailRow label="Reasoning">
                <p className="text-xs text-awp-muted whitespace-pre-wrap break-words leading-relaxed">
                  {reasoning}
                </p>
              </DetailRow>
            )}

            {/* Tools used */}
            {toolsUsed.length > 0 ? (
              <DetailRow label="Tools">
                <div className="flex flex-wrap gap-1">
                  {toolsUsed.map((t: string) => (
                    <Badge key={t} variant="orange" className="text-[10px]">{t}</Badge>
                  ))}
                </div>
              </DetailRow>
            ) : null}

            {/* Worker instructions (full text) */}
            {instructions ? (
              <DetailRow label="Instructions">
                <p className="text-xs text-awp-text whitespace-pre-wrap break-words leading-relaxed bg-awp-bg rounded p-1.5 max-h-32 overflow-y-auto">
                  {instructions}
                </p>
              </DetailRow>
            ) : null}

            {/* Delegations from iteration decision */}
            {delegations && delegations.length > 0 ? (
              <DetailRow label={`Delegations (${delegations.length})`}>
                <div className="space-y-1">
                  {delegations.map((d, i) => (
                    <div key={i} className="rounded bg-awp-bg p-1.5 text-[11px]">
                      <span className="font-mono text-awp-purple">{String(d.worker)}</span>
                      <p className="text-awp-muted mt-0.5">{String(d.task)}</p>
                      {Array.isArray(d.tools) && (d.tools as string[]).length > 0 ? (
                        <div className="flex flex-wrap gap-0.5 mt-0.5">
                          {(d.tools as string[]).map((t: string) => (
                            <span key={t} className="text-[9px] bg-awp-orange/10 text-awp-orange rounded px-1">{t}</span>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              </DetailRow>
            ) : null}

            {/* Tool call arguments */}
            {toolArgs != null && Object.keys(toolArgs).length > 0 ? (
              <DetailRow label="Arguments">
                <CodeBlock content={JSON.stringify(toolArgs, null, 2)} language="json" maxHeight="8rem" />
              </DetailRow>
            ) : null}

            {/* Error */}
            {error ? (
              <DetailRow label="Error">
                <p className="text-xs text-awp-red whitespace-pre-wrap break-words">{error}</p>
              </DetailRow>
            ) : null}

            {/* Outputs */}
            {outputs != null && Object.keys(outputs).length > 0 ? (
              <DetailRow label="Output">
                <CodeBlock content={JSON.stringify(outputs, null, 2)} language="json" maxHeight="12rem" />
              </DetailRow>
            ) : null}

            {/* Tools created by worker */}
            {toolsCreated.length > 0 ? (
              <DetailRow label="Tools Created">
                <div className="flex flex-wrap gap-1">
                  {toolsCreated.map((t: string) => (
                    <Badge key={t} variant="green" className="text-[10px]">{t}</Badge>
                  ))}
                </div>
              </DetailRow>
            ) : null}

            {/* Iteration badge */}
            {iteration ? (
              <span className="inline-block mt-1 text-[10px] text-awp-muted">Iteration {iteration}</span>
            ) : null}

            {/* Budget info (task root / completion) */}
            {details != null && typeof (details as Record<string, unknown>).budget === 'object' ? (
              <DetailRow label="Budget">
                <CodeBlock content={JSON.stringify((details as Record<string, unknown>).budget, null, 2)} language="json" maxHeight="10rem" />
              </DetailRow>
            ) : null}
          </div>
        )}
      </div>

      {/* Children */}
      {expanded && kids.map((childId) => (
        <GraphTreeNode
          key={childId}
          nodeId={childId}
          nodes={nodes}
          childMap={childMap}
          depth={depth + 1}
        />
      ))}
    </div>
  );
}

function GraphPanel() {
  const { graphNodes, graphEdges, currentRunId, loadRunGraph, runStatus } = useWorkflowStore();

  // Load graph from backend if we have a run but no nodes yet
  useEffect(() => {
    if (currentRunId && graphNodes.length === 0 && runStatus !== 'running') {
      loadRunGraph(currentRunId);
    }
  }, [currentRunId, graphNodes.length, runStatus, loadRunGraph]);

  if (graphNodes.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-awp-muted gap-3">
        <GitBranch className="h-12 w-12 text-awp-border" />
        <p className="text-sm">Agent graph will appear here during a run</p>
      </div>
    );
  }

  // Build tree structure
  const gNodes = graphNodes as unknown as GraphNode[];
  const gEdges = graphEdges as unknown as GraphEdge[];
  const nodeMap = new Map(gNodes.map((n) => [n.id, n]));
  const { roots, children } = buildTree(gNodes, gEdges);

  // Stats
  const totalWorkers = gNodes.filter((n) => (n.data.nodeType ?? n.type) === 'worker').length;
  const totalTools = gNodes.filter((n) => (n.data.nodeType ?? n.type) === 'toolCall').length;
  const totalIterations = gNodes.filter((n) => (n.data.nodeType ?? n.type) === 'iteration').length;

  return (
    <div className="h-full overflow-y-auto p-4">
      {/* Stats bar */}
      <div className="flex items-center gap-4 mb-3 text-xs text-awp-muted">
        <span className="flex items-center gap-1"><CircleDot className="h-3 w-3" /> {graphNodes.length} nodes</span>
        <span className="flex items-center gap-1"><RotateCcw className="h-3 w-3" /> {totalIterations} iterations</span>
        <span className="flex items-center gap-1"><Users className="h-3 w-3" /> {totalWorkers} workers</span>
        <span className="flex items-center gap-1"><Wrench className="h-3 w-3" /> {totalTools} tool calls</span>
      </div>

      {/* Tree */}
      {roots.map((rootId) => (
        <GraphTreeNode
          key={rootId}
          nodeId={rootId}
          nodes={nodeMap}
          childMap={children}
          depth={0}
        />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// History Panel
// ---------------------------------------------------------------------------

function HistoryPanel() {
  const { runHistory, loadHistory, currentRunId, loadRunGraph } = useWorkflowStore();

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  const handleSelectRun = useCallback((runId: string) => {
    useWorkflowStore.setState({
      currentRunId: runId,
      activePanel: 'graph' as ActivePanel,
    });
    loadRunGraph(runId);
  }, [loadRunGraph]);

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
        <button
          key={entry.run_id}
          type="button"
          onClick={() => handleSelectRun(entry.run_id)}
          className={clsx(
            'w-full text-left rounded-lg border p-3 transition-colors',
            entry.run_id === currentRunId
              ? 'border-awp-blue/50 bg-awp-blue/5'
              : 'border-awp-border bg-awp-bg hover:bg-awp-bg/60',
          )}
        >
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs font-mono text-awp-muted">
              {entry.run_id.slice(0, 8)}
            </span>
            <Badge variant={statusVariant(entry.status)}>{entry.status}</Badge>
          </div>
          <p className="text-sm text-awp-text line-clamp-2">{entry.task}</p>
          <div className="flex items-center gap-2 mt-2 text-xs text-awp-muted">
            <Clock className="h-3 w-3" />
            {new Date(entry.created_at).toLocaleString()}
          </div>
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Inspector Panel
// ---------------------------------------------------------------------------

// InspectorPanel has been merged into RightSidebar

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
    // UI state
    sidebarOpen,
    inspectorOpen,
    activePanel,
    currentSessionId,
    saveCurrentSettings,
  ]);

  const handleNewSession = useCallback(() => {
    createSession();
  }, [createSession]);

  return (
    <div className="flex flex-col h-screen bg-awp-bg text-awp-text">
      <TopBar />
      <div className="flex flex-1 overflow-hidden">
        {/* Session sidebar (left) */}
        {sidebarOpen && (
          <div className="w-60 shrink-0 border-r border-awp-border bg-awp-panel overflow-hidden animate-slide-in-left">
            <SessionSidebar
              sessions={sessions}
              currentSessionId={currentSessionId}
              onSelectSession={selectSession}
              onNewSession={handleNewSession}
              onDeleteSession={deleteSession}
              onRenameSession={renameSession}
            />
          </div>
        )}

        {/* Main content + task input */}
        <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
          <main className="flex-1 min-h-0 overflow-hidden">
            {activePanel === 'state' && <StatePanel />}
            {activePanel === 'final' && <FinalPanel />}
            {activePanel === 'output' && <OutputPanel />}
            {activePanel === 'graph' && <GraphPanel />}
            {activePanel === 'graphvis' && <GraphVisPanel />}
            {activePanel === 'history' && <HistoryPanel />}
          </main>
          <TaskInputBar />
        </div>

        {/* Settings sidebar (right) */}
        {inspectorOpen && (
          <div className="w-80 shrink-0 border-l border-awp-border bg-awp-panel overflow-hidden animate-slide-in-right">
            <RightSidebar />
          </div>
        )}
      </div>
      <BottomBar />
    </div>
  );
}
