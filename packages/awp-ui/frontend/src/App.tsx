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
  ClipboardList,
  BookOpen,
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
  Plus,
  Pencil,
  X,
  Tag,
  FlaskConical,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { useWorkflowStore } from '@/stores/workflowStore';
import * as api from '@/api/client';
import type { ActivePanel, OutputBlock, ExperimentStatus, Session } from '@/types';
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
// JSON Viewer — syntax highlighted, fully formatted, no height limit
// ---------------------------------------------------------------------------

/** Render any value as pretty-printed JSON with syntax highlighting.
 *  Large JSON (>30KB) is truncated by default with a "Show all" toggle. */
function JsonViewer({ data }: { data: unknown }) {
  const [showFull, setShowFull] = React.useState(false);
  const TRUNCATE_THRESHOLD = 30_000;

  let text: string;
  if (typeof data === 'string') {
    try {
      text = JSON.stringify(JSON.parse(data), null, 2);
    } catch {
      text = data;
    }
  } else {
    text = JSON.stringify(data, null, 2);
  }

  const isLarge = text.length > TRUNCATE_THRESHOLD;
  const displayText = isLarge && !showFull ? text.slice(0, TRUNCATE_THRESHOLD) + '\n// ... truncated' : text;

  return (
    <div>
      <CodeBlock content={displayText} language="json" maxHeight="24rem" />
      {isLarge && (
        <button
          type="button"
          onClick={() => setShowFull((v) => !v)}
          className="mt-1 text-[11px] text-awp-blue hover:underline"
        >
          {showFull ? 'Show less' : `Show all (${(text.length / 1024).toFixed(0)} KB)`}
        </button>
      )}
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
    { id: 'protocol' as const, label: 'Protocol', icon: <ClipboardList className="h-4 w-4" /> },
    { id: 'output' as const, label: 'Output', icon: <FileText className="h-4 w-4" /> },
    { id: 'results' as const, label: 'Results', icon: <FolderOpen className="h-4 w-4" /> },
    { id: 'graph' as const, label: 'Graph', icon: <GitBranch className="h-4 w-4" /> },
    { id: 'graphvis' as const, label: 'Graph Vis', icon: <Network className="h-4 w-4" /> },
    { id: 'memory' as const, label: 'Memory', icon: <BookOpen className="h-4 w-4" /> },
    { id: 'history' as const, label: 'History', icon: <History className="h-4 w-4" /> },
  ];

  const tokensPercent = budget.tokens_max > 0 ? budget.tokens_used / budget.tokens_max : 0;
  const loopsPercent = budget.loops_max > 0 ? budget.loops_used / budget.loops_max : 0;

  return (
    <header className="flex items-center gap-2 border-b border-awp-border bg-awp-panel px-3 h-12 shrink-0">
      {/* Sidebar toggle */}
      <IconButton tooltip="Toggle experiments" onClick={toggleSidebar} size="sm">
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
            <p className="text-[10px] text-awp-muted/70 mt-0.5 mb-1">
              Auto-routes: <span className="font-mono">provider/model</span> → OpenRouter, <span className="font-mono">gpt-*</span> → OpenAI, <span className="font-mono">claude-*</span> → Anthropic, <span className="font-mono">ollama/*</span> → local
            </p>
            <input
              type="text"
              value={config.model}
              onChange={(e) => updateConfig({ model: e.target.value })}
              disabled={isRunning}
              placeholder="nvidia/nemotron-3-super-120b-a12b:free"
              className="w-full rounded-md border border-awp-border bg-awp-bg px-2.5 py-1.5 text-sm font-mono text-awp-text placeholder:text-awp-muted/50 focus:outline-none focus:ring-1 focus:ring-awp-blue disabled:opacity-50"
            />
          </label>

          <label className="block">
            <span className="text-xs text-awp-muted">Worker model</span>
            <p className="text-[10px] text-awp-muted/70 mt-0.5 mb-1">
              Used for sub-agents. Leave empty to use the main model.
            </p>
            <input
              type="text"
              value={config.worker_model ?? ''}
              onChange={(e) =>
                updateConfig({
                  worker_model: e.target.value || undefined,
                })
              }
              disabled={isRunning}
              placeholder="Same as main model"
              className="w-full rounded-md border border-awp-border bg-awp-bg px-2.5 py-1.5 text-sm font-mono text-awp-text placeholder:text-awp-muted/50 focus:outline-none focus:ring-1 focus:ring-awp-blue disabled:opacity-50"
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
            <JsonViewer data={data.inputs} />
          </div>
        </div>
      )}

      {data.outputs != null && (
        <div>
          <span className="text-xs text-awp-muted">Outputs</span>
          <div className="mt-1">
            <JsonViewer data={data.outputs} />
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Protocol Panel — Experiment overview (Lab Notebook)
// ---------------------------------------------------------------------------

function useAutoSave(sessionId: string | null, field: string, value: string, delay = 800) {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const prevRef = useRef(value);
  const updateSessionMetadata = useWorkflowStore((s) => s.updateSessionMetadata);

  useEffect(() => {
    if (!sessionId || value === prevRef.current) return;
    prevRef.current = value;
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      updateSessionMetadata(sessionId, { [field]: value } as Partial<Session>);
    }, delay);
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [sessionId, field, value, delay, updateSessionMetadata]);
}

function ProtocolPanel() {
  const {
    currentSessionId,
    sessions,
    runStatus,
    outputBlocks,
    budget,
    config,
    runHistory,
    updateSessionMetadata,
  } = useWorkflowStore();

  const currentSession = sessions.find((s) => s.id === currentSessionId);

  const [title, setTitle] = React.useState(currentSession?.title ?? '');
  const [hypothesis, setHypothesis] = React.useState(currentSession?.hypothesis ?? '');
  const [description, setDescription] = React.useState(currentSession?.description ?? '');
  const [status, setStatus] = React.useState<string>(currentSession?.status ?? 'draft');
  const [tags, setTags] = React.useState<string[]>(currentSession?.tags ?? []);
  const [baseDir, setBaseDir] = React.useState(currentSession?.base_dir ?? '');
  const [newTag, setNewTag] = React.useState('');

  // Sync when session changes
  useEffect(() => {
    setTitle(currentSession?.title ?? '');
    setHypothesis(currentSession?.hypothesis ?? '');
    setDescription(currentSession?.description ?? '');
    setStatus(currentSession?.status ?? 'draft');
    setTags(currentSession?.tags ?? []);
    setBaseDir(currentSession?.base_dir ?? '');
  }, [currentSessionId, currentSession?.title, currentSession?.hypothesis, currentSession?.description, currentSession?.status, currentSession?.tags, currentSession?.base_dir]);

  useAutoSave(currentSessionId, 'title', title);
  useAutoSave(currentSessionId, 'hypothesis', hypothesis);
  useAutoSave(currentSessionId, 'description', description);
  useAutoSave(currentSessionId, 'base_dir', baseDir);

  const handleStatusChange = useCallback((newStatus: string) => {
    setStatus(newStatus);
    if (currentSessionId) {
      updateSessionMetadata(currentSessionId, { status: newStatus as ExperimentStatus });
    }
  }, [currentSessionId, updateSessionMetadata]);

  const handleAddTag = useCallback(() => {
    const tag = newTag.trim();
    if (!tag || tags.includes(tag)) { setNewTag(''); return; }
    const updated = [...tags, tag];
    setTags(updated);
    setNewTag('');
    if (currentSessionId) {
      updateSessionMetadata(currentSessionId, { tags: updated });
    }
  }, [newTag, tags, currentSessionId, updateSessionMetadata]);

  const handleRemoveTag = useCallback((tag: string) => {
    const updated = tags.filter((t) => t !== tag);
    setTags(updated);
    if (currentSessionId) {
      updateSessionMetadata(currentSessionId, { tags: updated });
    }
  }, [tags, currentSessionId, updateSessionMetadata]);

  const finalResult = outputBlocks.find((b) => b.title === 'Final Result' || b.title === 'Agent Result');
  const errorBlock = outputBlocks.find((b) => b.type === 'error');

  // Compute aggregated stats from run history
  const totalRuns = runHistory.length;

  const statusColors: Record<string, string> = {
    draft: 'text-awp-muted border-awp-border',
    running: 'text-awp-blue border-awp-blue/50',
    complete: 'text-awp-green border-awp-green/50',
    failed: 'text-awp-red border-awp-red/50',
    archived: 'text-awp-muted border-awp-muted/50',
  };

  if (!currentSessionId) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-awp-muted gap-3">
        <FlaskConical className="h-12 w-12 text-awp-border" />
        <p className="text-sm">Select or create an experiment to begin</p>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-4 space-y-4">
      {/* Title */}
      <input
        type="text"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        className="w-full bg-transparent text-xl font-semibold text-awp-text border-none outline-none placeholder:text-awp-muted/50"
        placeholder="Experiment title..."
      />

      {/* Status selector */}
      <div className="flex items-center gap-3">
        <select
          value={status}
          onChange={(e) => handleStatusChange(e.target.value)}
          className={clsx(
            'text-xs font-medium px-2 py-1 rounded border bg-transparent cursor-pointer',
            statusColors[status] ?? statusColors.draft,
          )}
        >
          <option value="draft">Draft</option>
          <option value="running">Running</option>
          <option value="complete">Complete</option>
          <option value="failed">Failed</option>
          <option value="archived">Archived</option>
        </select>

        {runStatus === 'running' && (
          <div className="flex items-center gap-1 text-awp-blue text-xs">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Run in progress
          </div>
        )}
      </div>

      {/* Hypothesis */}
      <div>
        <label className="text-xs font-medium text-awp-muted uppercase tracking-wider block mb-1">
          Hypothesis
        </label>
        <textarea
          value={hypothesis}
          onChange={(e) => setHypothesis(e.target.value)}
          rows={2}
          className="w-full bg-awp-bg border border-awp-border rounded-md px-3 py-2 text-sm text-awp-text resize-y placeholder:text-awp-muted/50 focus:outline-none focus:ring-1 focus:ring-awp-blue/50"
          placeholder="What do you expect to find?"
        />
      </div>

      {/* Description */}
      <div>
        <label className="text-xs font-medium text-awp-muted uppercase tracking-wider block mb-1">
          Description
        </label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={3}
          className="w-full bg-awp-bg border border-awp-border rounded-md px-3 py-2 text-sm text-awp-text resize-y placeholder:text-awp-muted/50 focus:outline-none focus:ring-1 focus:ring-awp-blue/50"
          placeholder="Describe the experiment setup, methodology, context..."
        />
      </div>

      {/* Tags */}
      <div>
        <label className="text-xs font-medium text-awp-muted uppercase tracking-wider block mb-1">
          Tags
        </label>
        <div className="flex flex-wrap items-center gap-1.5">
          {tags.map((tag) => (
            <span
              key={tag}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-awp-blue/10 text-awp-blue text-xs"
            >
              <Tag className="h-2.5 w-2.5" />
              {tag}
              <button
                type="button"
                onClick={() => handleRemoveTag(tag)}
                className="hover:text-awp-red transition-colors"
              >
                <X className="h-2.5 w-2.5" />
              </button>
            </span>
          ))}
          <div className="inline-flex items-center gap-1">
            <input
              type="text"
              value={newTag}
              onChange={(e) => setNewTag(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); handleAddTag(); } }}
              className="w-20 bg-transparent border-b border-awp-border text-xs text-awp-text outline-none placeholder:text-awp-muted/40"
              placeholder="+ Add"
            />
          </div>
        </div>
      </div>

      {/* Base Directory */}
      <div>
        <label className="text-xs font-medium text-awp-muted uppercase tracking-wider block mb-1">
          Base Directory
        </label>
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={baseDir}
            onChange={(e) => setBaseDir(e.target.value)}
            className="flex-1 bg-awp-bg border border-awp-border rounded-md px-3 py-1.5 text-xs font-mono text-awp-text placeholder:text-awp-muted/50 focus:outline-none focus:ring-1 focus:ring-awp-blue/50"
            placeholder="/path/to/experiments"
          />
          {baseDir && (
            <button
              type="button"
              onClick={() => api.openDirectory(baseDir).catch(() => {})}
              className="shrink-0 flex items-center gap-1 px-2 py-1.5 text-xs text-awp-muted hover:text-awp-blue border border-awp-border rounded-md hover:border-awp-blue/30 hover:bg-awp-blue/5 transition-colors"
              title="Open in file explorer"
            >
              <FolderOpen className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Config Summary */}
      <div className="rounded-lg border border-awp-border bg-awp-bg p-4">
        <span className="text-xs font-medium text-awp-muted uppercase tracking-wider block mb-3">Configuration</span>
        <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
          <div>
            <span className="text-awp-muted">Model</span>
            <p className="text-awp-text font-mono truncate">{config.model?.split('/').pop() ?? '-'}</p>
          </div>
          <div>
            <span className="text-awp-muted">Sandbox</span>
            <p className="text-awp-text font-mono">{config.sandbox}</p>
          </div>
          <div>
            <span className="text-awp-muted">Max Loops</span>
            <p className="text-awp-text font-mono">{config.max_loops}</p>
          </div>
          <div>
            <span className="text-awp-muted">Token Budget</span>
            <p className="text-awp-text font-mono">{(config.max_total_tokens / 1000).toFixed(0)}k</p>
          </div>
        </div>
      </div>

      {/* Stats */}
      <div className="rounded-lg border border-awp-border bg-awp-bg p-4">
        <span className="text-xs font-medium text-awp-muted uppercase tracking-wider block mb-3">Statistics</span>
        <div className="grid grid-cols-3 gap-3 text-xs">
          <div className="text-center">
            <p className="text-lg font-semibold text-awp-text">{totalRuns}</p>
            <span className="text-awp-muted">Runs</span>
          </div>
          <div className="text-center">
            <p className="text-lg font-semibold text-awp-text">{budget.tokens_used > 0 ? `${(budget.tokens_used / 1000).toFixed(0)}k` : '-'}</p>
            <span className="text-awp-muted">Tokens</span>
          </div>
          <div className="text-center">
            <p className="text-lg font-semibold text-awp-text">{budget.wall_time_ms > 0 ? `${(budget.wall_time_ms / 1000).toFixed(1)}s` : '-'}</p>
            <span className="text-awp-muted">Wall Time</span>
          </div>
        </div>

        {/* Budget bars */}
        {(budget.loops_used > 0 || budget.tokens_used > 0) ? (
          <div className="grid grid-cols-2 gap-3 text-xs mt-3 pt-3 border-t border-awp-border">
            <div>
              <span className="text-awp-muted">Iterations</span>
              <p className="text-awp-text font-mono">{budget.loops_used} / {budget.loops_max}</p>
              <ProgressBar value={budget.loops_max > 0 ? budget.loops_used / budget.loops_max : 0} className="mt-1" />
            </div>
            <div>
              <span className="text-awp-muted">Workers</span>
              <p className="text-awp-text font-mono">{budget.workers_used} / {budget.workers_max}</p>
            </div>
          </div>
        ) : null}
      </div>

      {/* Last Result */}
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
            <JsonViewer data={finalResult.content} />
          )}
        </div>
      ) : null}

      {errorBlock && !finalResult ? (
        <div className="rounded-lg border border-awp-red/30 bg-awp-red/5 p-4">
          <div className="flex items-center gap-2 mb-2">
            <AlertCircle className="h-4 w-4 text-awp-red shrink-0" />
            <span className="text-xs font-medium text-awp-muted uppercase tracking-wider">Error</span>
          </div>
          <p className="text-sm text-awp-red whitespace-pre-wrap break-words">{errorBlock.content}</p>
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Results Panel — all output artifacts (images, tables, HTML, text, code, data)
// ---------------------------------------------------------------------------

/** Collapsible section for artifact groups — lazy-loads content on expand. */
function ArtifactSection({
  title,
  count,
  defaultOpen = false,
  children,
}: {
  title: string;
  count: number;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(defaultOpen);
  if (count === 0) return null;
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 w-full text-left group"
      >
        {open ? (
          <ChevronDown className="h-3 w-3 text-awp-muted shrink-0" />
        ) : (
          <ChevronRight className="h-3 w-3 text-awp-muted shrink-0" />
        )}
        <span className="text-xs font-medium text-awp-muted uppercase tracking-wider group-hover:text-awp-text transition-colors">
          {title} ({count})
        </span>
      </button>
      {open && <div className="mt-2">{children}</div>}
    </div>
  );
}

/** Paginated list — shows PAGE_SIZE items with a "Show more" button. */
function PaginatedList<T>({
  items,
  pageSize = 10,
  renderItem,
}: {
  items: T[];
  pageSize?: number;
  renderItem: (item: T, index: number) => React.ReactNode;
}) {
  const [visibleCount, setVisibleCount] = React.useState(pageSize);
  const visible = items.slice(0, visibleCount);
  const remaining = items.length - visibleCount;
  return (
    <>
      {visible.map((item, i) => renderItem(item, i))}
      {remaining > 0 && (
        <button
          type="button"
          onClick={() => setVisibleCount((v) => v + pageSize)}
          className="w-full py-2 text-[11px] text-awp-blue hover:underline text-center"
        >
          Show {Math.min(remaining, pageSize)} more ({remaining} remaining)
        </button>
      )}
    </>
  );
}

/** Lazy text content loader — fetches file content only when rendered. */
function LazyTextArtifact({
  artifact,
  render,
}: {
  artifact: { name: string; path: string; relative: string; kind: string; size: number };
  render: (content: string) => React.ReactNode;
}) {
  const [content, setContent] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);

  useEffect(() => {
    setLoading(true);
    fetch(api.fileServeUrl(artifact.path))
      .then((r) => r.text())
      .then(setContent)
      .catch(() => setContent(''))
      .finally(() => setLoading(false));
  }, [artifact.path]);

  if (loading || content === null) {
    return (
      <div className="flex items-center gap-2 text-awp-muted text-xs py-2">
        <Loader2 className="h-3 w-3 animate-spin" /> Loading {artifact.name}...
      </div>
    );
  }
  return <>{render(content)}</>;
}

function ResultsPanel() {
  const { currentRunId, runStatus } = useWorkflowStore();
  const [artifacts, setArtifacts] = React.useState<Array<{
    name: string; path: string; relative: string; kind: string; size: number;
  }>>([]);
  const [loading, setLoading] = React.useState(false);

  useEffect(() => {
    if (!currentRunId) return;
    setLoading(true);
    api.getRunArtifacts(currentRunId)
      .then(setArtifacts)
      .catch(() => {})
      .finally(() => setLoading(false));
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

  // Derive the workspace directory from the first artifact path
  const workspaceDir = artifacts.length > 0
    ? artifacts[0].path.substring(0, artifacts[0].path.lastIndexOf('/'))
    : null;

  return (
    <div className="h-full overflow-y-auto p-4 space-y-4">
      {/* Header with open-in-explorer button */}
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-awp-muted uppercase tracking-wider">
          Artifacts ({artifacts.length})
        </span>
        {workspaceDir && (
          <button
            type="button"
            onClick={() => api.openDirectory(workspaceDir).catch(() => {})}
            className="shrink-0 flex items-center gap-1 px-2 py-1.5 text-xs text-awp-muted hover:text-awp-blue border border-awp-border rounded-md hover:border-awp-blue/30 hover:bg-awp-blue/5 transition-colors"
            title={`Open ${workspaceDir}`}
          >
            <FolderOpen className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-awp-muted text-sm">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading artifacts...
        </div>
      ) : null}

      {/* Images — collapsed by default, paginated */}
      <ArtifactSection title="Images" count={images.length} defaultOpen={images.length <= 8}>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <PaginatedList items={images} pageSize={8} renderItem={(img) => {
            const url = `/api/files/serve?path=${encodeURIComponent(img.path)}`;
            return (
              <div key={img.path} className="rounded-lg border border-awp-border bg-awp-bg p-2">
                <img src={url} alt={img.name} className="max-w-full rounded" loading="lazy" />
                <p className="text-[10px] text-awp-muted mt-1 truncate">{img.relative}</p>
              </div>
            );
          }} />
        </div>
      </ArtifactSection>

      {/* HTML visualizations — collapsed, paginated */}
      <ArtifactSection title="Visualizations" count={htmlFiles.length}>
        <PaginatedList items={htmlFiles} pageSize={4} renderItem={(f) => {
          const url = `/api/files/serve?path=${encodeURIComponent(f.path)}`;
          return (
            <div key={f.path} className="rounded-lg border border-awp-border bg-awp-bg overflow-hidden mb-3">
              <div className="px-3 py-1.5 border-b border-awp-border flex items-center justify-between">
                <span className="text-xs text-awp-muted truncate">{f.name}</span>
                <a href={url} target="_blank" rel="noopener noreferrer" className="text-[10px] text-awp-blue hover:underline">Open</a>
              </div>
              <iframe src={url} className="w-full h-96 border-0" title={f.name} sandbox="allow-scripts" loading="lazy" />
            </div>
          );
        }} />
      </ArtifactSection>

      {/* Tables (CSV/TSV) — collapsed, lazy content loading */}
      <ArtifactSection title="Tables" count={tables.length}>
        <PaginatedList items={tables} pageSize={5} renderItem={(f) => (
          <LazyTextArtifact key={f.path} artifact={f} render={(content) => {
            const rows = content.split('\n').filter(Boolean);
            const header = rows[0]?.split(',') ?? [];
            const dataRows = rows.slice(1, 101);
            return (
              <div className="rounded-lg border border-awp-border bg-awp-bg overflow-hidden mb-3">
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
          }} />
        )} />
      </ArtifactSection>

      {/* Documents — collapsed, lazy content loading, paginated */}
      <ArtifactSection title="Documents" count={textFiles.length}>
        <PaginatedList items={textFiles} pageSize={5} renderItem={(f) => (
          <LazyTextArtifact key={f.path} artifact={f} render={(content) => {
            const isMd = f.name.endsWith('.md');
            const isJson = f.name.endsWith('.json');
            const isYaml = f.name.endsWith('.yaml') || f.name.endsWith('.yml');
            return (
              <div className="rounded-lg border border-awp-border bg-awp-bg p-3 mb-3">
                <span className="text-xs text-awp-muted block mb-2">{f.relative}</span>
                {isMd ? (
                  <div className="prose prose-sm prose-invert max-w-none break-words">
                    <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>
                      {content}
                    </ReactMarkdown>
                  </div>
                ) : isJson ? (
                  <JsonViewer data={content} />
                ) : (
                  <CodeBlock content={content} language={isYaml ? 'yaml' : undefined} filename={f.name} />
                )}
              </div>
            );
          }} />
        )} />
      </ArtifactSection>

      {/* Code files — collapsed, lazy content loading, paginated */}
      <ArtifactSection title="Code" count={codeFiles.length}>
        <PaginatedList items={codeFiles} pageSize={5} renderItem={(f) => (
          <LazyTextArtifact key={f.path} artifact={f} render={(content) => (
            <div className="mb-3">
              <CodeBlock content={content} filename={f.relative} />
            </div>
          )} />
        )} />
      </ArtifactSection>

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
  const INITIAL_VISIBLE = 30;
  const [showAll, setShowAll] = React.useState(false);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [outputBlocks.length]);

  // Reset showAll when switching runs
  useEffect(() => { setShowAll(false); }, [runStatus]);

  if (outputBlocks.length === 0 && runStatus === 'idle') {
    return (
      <div className="flex flex-col items-center justify-center h-full text-awp-muted gap-3">
        <Zap className="h-12 w-12 text-awp-border" />
        <p className="text-sm">Enter a task and click Run to begin</p>
      </div>
    );
  }

  const hiddenCount = showAll ? 0 : Math.max(0, outputBlocks.length - INITIAL_VISIBLE);
  const visibleBlocks = showAll ? outputBlocks : outputBlocks.slice(hiddenCount);

  return (
    <div className="h-full overflow-y-auto p-4 space-y-3">
      {hiddenCount > 0 && (
        <button
          type="button"
          onClick={() => setShowAll(true)}
          className="w-full py-2 rounded-lg border border-awp-border bg-awp-bg text-[11px] text-awp-blue hover:bg-awp-blue/5 transition-colors"
        >
          Show {hiddenCount} earlier blocks
        </button>
      )}
      {visibleBlocks.map((block, i) => (
        <OutputBlockCard key={showAll ? i : hiddenCount + i} block={block} />
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
        <JsonViewer data={block.content} />
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
        <CodeBlock content={block.content} maxHeight="none" />
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
                <JsonViewer data={toolArgs} />
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
                <JsonViewer data={outputs} />
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
                <JsonViewer data={(details as Record<string, unknown>).budget} />
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
// Memory Panel — Experiment notes, observations, findings, decisions
// ---------------------------------------------------------------------------

const MEMORY_TYPE_CONFIG: Record<string, { label: string; color: string; dotColor: string }> = {
  finding: { label: 'FINDING', color: 'text-awp-green', dotColor: 'bg-awp-green' },
  note: { label: 'NOTE', color: 'text-awp-blue', dotColor: 'bg-awp-blue' },
  observation: { label: 'OBSERVATION', color: 'text-yellow-400', dotColor: 'bg-yellow-400' },
  decision: { label: 'DECISION', color: 'text-purple-400', dotColor: 'bg-purple-400' },
};

function MemoryPanel() {
  const {
    currentSessionId,
    experimentMemory,
    addMemoryEntry,
    updateMemoryEntry: storeUpdateMemory,
    deleteMemoryEntry: storeDeleteMemory,
    loadExperimentMemory,
  } = useWorkflowStore();

  const [showAdd, setShowAdd] = React.useState(false);
  const [newType, setNewType] = React.useState<string>('note');
  const [newContent, setNewContent] = React.useState('');
  const [editingId, setEditingId] = React.useState<number | null>(null);
  const [editContent, setEditContent] = React.useState('');
  const [filter, setFilter] = React.useState<string>('all');

  useEffect(() => {
    if (currentSessionId) loadExperimentMemory();
  }, [currentSessionId, loadExperimentMemory]);

  const handleAdd = useCallback(() => {
    if (!newContent.trim()) return;
    addMemoryEntry(newType, newContent.trim());
    setNewContent('');
    setShowAdd(false);
  }, [newType, newContent, addMemoryEntry]);

  const handleSaveEdit = useCallback((id: number) => {
    if (!editContent.trim()) return;
    storeUpdateMemory(id, editContent.trim());
    setEditingId(null);
  }, [editContent, storeUpdateMemory]);

  const filtered = filter === 'all'
    ? experimentMemory
    : experimentMemory.filter((m) => m.type === filter);

  if (!currentSessionId) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-awp-muted gap-3">
        <BookOpen className="h-12 w-12 text-awp-border" />
        <p className="text-sm">Select an experiment to view its memory</p>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="text-xs bg-awp-bg border border-awp-border rounded px-2 py-1 text-awp-text"
          >
            <option value="all">All ({experimentMemory.length})</option>
            <option value="finding">Findings</option>
            <option value="note">Notes</option>
            <option value="observation">Observations</option>
            <option value="decision">Decisions</option>
          </select>
        </div>
        <button
          type="button"
          onClick={() => setShowAdd(!showAdd)}
          className="flex items-center gap-1 px-2 py-1 text-xs font-medium text-awp-blue hover:bg-awp-blue/10 rounded transition-colors"
        >
          <Plus className="h-3.5 w-3.5" /> Add Note
        </button>
      </div>

      {/* Add form */}
      {showAdd && (
        <div className="rounded-lg border border-awp-blue/30 bg-awp-blue/5 p-3 space-y-2">
          <div className="flex items-center gap-2">
            <select
              value={newType}
              onChange={(e) => setNewType(e.target.value)}
              className="text-xs bg-awp-bg border border-awp-border rounded px-2 py-1 text-awp-text"
            >
              <option value="note">Note</option>
              <option value="observation">Observation</option>
              <option value="finding">Finding</option>
              <option value="decision">Decision</option>
            </select>
          </div>
          <textarea
            value={newContent}
            onChange={(e) => setNewContent(e.target.value)}
            rows={3}
            className="w-full bg-awp-bg border border-awp-border rounded-md px-3 py-2 text-sm text-awp-text resize-y placeholder:text-awp-muted/50 focus:outline-none focus:ring-1 focus:ring-awp-blue/50"
            placeholder="Write your note... (Markdown supported)"
            autoFocus
          />
          <div className="flex items-center gap-2 justify-end">
            <button
              type="button"
              onClick={() => { setShowAdd(false); setNewContent(''); }}
              className="px-2 py-1 text-xs text-awp-muted hover:text-awp-text transition-colors"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleAdd}
              disabled={!newContent.trim()}
              className="px-3 py-1 text-xs font-medium bg-awp-blue text-white rounded hover:bg-awp-blue/80 disabled:opacity-50 transition-colors"
            >
              Save
            </button>
          </div>
        </div>
      )}

      {/* Memory entries */}
      {filtered.length === 0 ? (
        <div className="text-center text-awp-muted text-sm py-8">
          No memory entries yet. Run an experiment or add notes manually.
        </div>
      ) : (
        filtered.map((entry) => {
          const typeConfig = MEMORY_TYPE_CONFIG[entry.type] ?? MEMORY_TYPE_CONFIG.note;
          const isEditing = editingId === entry.id;

          return (
            <div
              key={entry.id}
              className="rounded-lg border border-awp-border bg-awp-bg p-3 space-y-2"
            >
              {/* Header */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className={clsx('w-2 h-2 rounded-full', typeConfig.dotColor)} />
                  <span className={clsx('text-[10px] font-bold uppercase tracking-wider', typeConfig.color)}>
                    {typeConfig.label}
                  </span>
                  <span className="text-[10px] text-awp-muted">
                    ({entry.source}{entry.run_id ? `, Run ${entry.run_id.slice(0, 8)}` : ''})
                  </span>
                </div>
                <div className="flex items-center gap-1">
                  {entry.source === 'user' && !isEditing && (
                    <>
                      <button
                        type="button"
                        onClick={() => { setEditingId(entry.id); setEditContent(entry.content); }}
                        className="p-0.5 text-awp-muted hover:text-awp-text transition-colors"
                      >
                        <Pencil className="h-3 w-3" />
                      </button>
                      <button
                        type="button"
                        onClick={() => storeDeleteMemory(entry.id)}
                        className="p-0.5 text-awp-muted hover:text-awp-red transition-colors"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </>
                  )}
                </div>
              </div>

              {/* Content */}
              {isEditing ? (
                <div className="space-y-2">
                  <textarea
                    value={editContent}
                    onChange={(e) => setEditContent(e.target.value)}
                    rows={3}
                    className="w-full bg-awp-panel border border-awp-border rounded-md px-3 py-2 text-sm text-awp-text resize-y focus:outline-none focus:ring-1 focus:ring-awp-blue/50"
                    autoFocus
                  />
                  <div className="flex gap-2 justify-end">
                    <button
                      type="button"
                      onClick={() => setEditingId(null)}
                      className="px-2 py-1 text-xs text-awp-muted hover:text-awp-text"
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      onClick={() => handleSaveEdit(entry.id)}
                      className="px-2 py-1 text-xs font-medium bg-awp-blue text-white rounded hover:bg-awp-blue/80"
                    >
                      Save
                    </button>
                  </div>
                </div>
              ) : (
                <div className="prose prose-sm prose-invert max-w-none text-sm break-words">
                  <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>
                    {entry.content}
                  </ReactMarkdown>
                </div>
              )}

              {/* Timestamp */}
              <div className="text-[10px] text-awp-muted">
                {new Date(entry.created_at).toLocaleString()}
              </div>
            </div>
          );
        })
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// History Panel — Experiment-scoped run history
// ---------------------------------------------------------------------------

function HistoryPanel() {
  const { runHistory, loadHistory, currentRunId, currentSessionId, loadRunGraph } = useWorkflowStore();

  useEffect(() => {
    loadHistory();
  }, [loadHistory, currentSessionId]);

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
        <p className="text-sm">{currentSessionId ? 'No runs in this experiment yet' : 'No previous runs'}</p>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-4 space-y-2">
      <div className="text-xs font-medium text-awp-muted uppercase tracking-wider mb-3">
        Experiment Runs ({runHistory.length})
      </div>
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
  const [version, setVersion] = React.useState('');

  useEffect(() => {
    api.getVersion().then(setVersion);
  }, []);

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

      {/* Version */}
      {version && (
        <span className="text-awp-muted/50 font-mono">v{version}</span>
      )}
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
              onOpenFolder={(session) => {
                // Derive base_dir: session's own > current session's > any session with base_dir
                const currentBase = sessions.find((s) => s.id === currentSessionId)?.base_dir;
                const anyBase = sessions.find((s) => s.base_dir)?.base_dir;
                const base = session.base_dir || currentBase || anyBase;
                if (!base) return;
                const slug = (session.title || 'experiment')
                  .toLowerCase()
                  .replace(/ /g, '_')
                  .slice(0, 40)
                  .replace(/[^a-z0-9_-]/g, '') || 'experiment';
                const folderPath = `${base}/${slug}_${session.id}`;
                api.openDirectory(folderPath).catch(() => {});
              }}
            />
          </div>
        )}

        {/* Main content + task input */}
        <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
          <main className="flex-1 min-h-0 overflow-hidden">
            {activePanel === 'protocol' && <ProtocolPanel />}
            {activePanel === 'output' && <OutputPanel />}
            {activePanel === 'results' && <ResultsPanel />}
            {activePanel === 'graph' && <GraphPanel />}
            {activePanel === 'graphvis' && <GraphVisPanel />}
            {activePanel === 'memory' && <MemoryPanel />}
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
