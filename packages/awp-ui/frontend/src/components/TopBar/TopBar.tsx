import {
  MessageSquare,
  GitBranch,
  History,
  Wifi,
  WifiOff,
  Loader2,
  CheckCircle2,
  AlertCircle,
  Circle,
  Zap,
  FileText,
  FolderCog,
  Brain,
} from 'lucide-react';
import { useWorkflowStore } from '@/stores/workflowStore';
import { BudgetMonitorCompact } from '@/components/BudgetMonitor/BudgetMonitor';
import type { ActivePanel } from '@/types';
import clsx from 'clsx';

// ---------------------------------------------------------------------------
// Tab configuration
// ---------------------------------------------------------------------------

interface TabDef {
  id: ActivePanel;
  label: string;
  icon: React.ReactNode;
}

const TABS: TabDef[] = [
  { id: 'output', label: 'Output', icon: <MessageSquare className="h-3.5 w-3.5" /> },
  { id: 'results', label: 'Results', icon: <FileText className="h-3.5 w-3.5" /> },
  { id: 'workspace', label: 'Workspace', icon: <FolderCog className="h-3.5 w-3.5" /> },
  { id: 'memory', label: 'Memory', icon: <Brain className="h-3.5 w-3.5" /> },
  { id: 'graph', label: 'Agent Graph', icon: <GitBranch className="h-3.5 w-3.5" /> },
  { id: 'history', label: 'History', icon: <History className="h-3.5 w-3.5" /> },
];

// ---------------------------------------------------------------------------
// Status configs
// ---------------------------------------------------------------------------

const runStatusConfig: Record<
  string,
  { dot: string; label: string; icon: React.ReactNode }
> = {
  idle: {
    dot: 'bg-awp-muted',
    label: 'Idle',
    icon: <Circle className="h-2 w-2 fill-awp-muted text-awp-muted" />,
  },
  running: {
    dot: 'bg-awp-blue',
    label: 'Running',
    icon: <Loader2 className="h-3 w-3 text-awp-blue animate-spin" />,
  },
  complete: {
    dot: 'bg-awp-green',
    label: 'Complete',
    icon: <CheckCircle2 className="h-3 w-3 text-awp-green" />,
  },
  error: {
    dot: 'bg-awp-red',
    label: 'Error',
    icon: <AlertCircle className="h-3 w-3 text-awp-red" />,
  },
};

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

export function TopBar() {
  const activePanel = useWorkflowStore((s) => s.activePanel);
  const setActivePanel = useWorkflowStore((s) => s.setActivePanel);
  const runStatus = useWorkflowStore((s) => s.runStatus);
  const wsStatus = useWorkflowStore((s) => s._wsStatus);

  const status = runStatusConfig[runStatus] ?? runStatusConfig.idle;
  const wsConnected = wsStatus === 'open';

  return (
    <header className="flex h-12 items-center border-b border-awp-border bg-awp-panel/80 backdrop-blur-md px-4 gap-4">
      {/* Logo / title */}
      <div className="flex items-center gap-2 shrink-0">
        <div className="flex items-center justify-center h-7 w-7 rounded-lg bg-gradient-to-br from-awp-blue to-awp-purple">
          <Zap className="h-4 w-4 text-white" />
        </div>
        <h1 className="text-sm font-bold text-awp-text tracking-tight hidden lg:block">
          AWP Workflow Studio
        </h1>
      </div>

      {/* Center tabs */}
      <nav className="flex items-center gap-0.5 mx-auto">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActivePanel(tab.id)}
            className={clsx(
              'relative flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors',
              activePanel === tab.id
                ? 'bg-awp-blue/10 text-awp-blue'
                : 'text-awp-muted hover:text-awp-text hover:bg-awp-bg/50',
            )}
          >
            {tab.icon}
            <span className="hidden sm:inline">{tab.label}</span>
            {activePanel === tab.id && (
              <span className="absolute inset-x-2 -bottom-[9px] h-0.5 rounded-full bg-awp-blue" />
            )}
          </button>
        ))}
      </nav>

      {/* Right side */}
      <div className="flex items-center gap-4 shrink-0">
        {/* Budget (compact) */}
        <div className="hidden xl:flex">
          <BudgetMonitorCompact />
        </div>

        {/* Run status */}
        <div className="flex items-center gap-1.5">
          {status.icon}
          <span className="text-[11px] font-medium text-awp-muted hidden md:inline">
            {status.label}
          </span>
        </div>

        {/* WebSocket status */}
        <div
          className={clsx(
            'flex items-center gap-1 rounded-md px-2 py-1 text-[10px] font-medium',
            wsConnected
              ? 'text-awp-green/80'
              : 'text-awp-muted/60',
          )}
          title={wsConnected ? 'WebSocket connected' : 'WebSocket disconnected'}
        >
          {wsConnected ? (
            <Wifi className="h-3 w-3" />
          ) : (
            <WifiOff className="h-3 w-3" />
          )}
          <span className="hidden lg:inline">
            {wsConnected ? 'Connected' : 'Disconnected'}
          </span>
        </div>
      </div>
    </header>
  );
}
