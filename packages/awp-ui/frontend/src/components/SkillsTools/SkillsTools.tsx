import { useCallback, useState } from 'react';
import {
  BookOpen,
  Wrench,
  Upload,
  Trash2,
  FolderOpen,
  Plus,
  X,
  Plug,
  PlugZap,
  AlertCircle,
  CheckCircle2,
  Server,
  ChevronDown,
  ChevronRight,
} from 'lucide-react';
import { useWorkflowStore } from '@/stores/workflowStore';
import { TabBar } from '@/components/Layout';
import type { Skill, MCPServer } from '@/types';
import clsx from 'clsx';

// ---------------------------------------------------------------------------
// Skills tab
// ---------------------------------------------------------------------------

function SkillsTab() {
  const skills = useWorkflowStore((s) => s.skills);
  const [pathInput, setPathInput] = useState('');

  const handleUpload = useCallback(() => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.md';
    input.multiple = true;
    input.onchange = () => {
      // In a real app, this would parse and load skill files
      // For now, this is a placeholder for the upload functionality
    };
    input.click();
  }, []);

  const handleLoadFromPath = useCallback(() => {
    if (!pathInput.trim()) return;
    // Placeholder: would call API to load skill from path
    setPathInput('');
  }, [pathInput]);

  return (
    <div className="space-y-4">
      {/* Upload / load */}
      <div className="flex gap-2">
        <button
          onClick={handleUpload}
          className="flex items-center gap-1.5 rounded-lg border border-awp-border bg-awp-bg px-3 py-1.5 text-xs text-awp-muted hover:border-awp-blue/50 hover:text-awp-blue transition-colors"
        >
          <Upload className="h-3 w-3" />
          Upload .md
        </button>
      </div>

      {/* Path input */}
      <div className="flex gap-2">
        <div className="relative flex-1">
          <FolderOpen className="absolute left-2.5 top-1/2 h-3 w-3 -translate-y-1/2 text-awp-muted" />
          <input
            type="text"
            value={pathInput}
            onChange={(e) => setPathInput(e.target.value)}
            placeholder="Path to skill file..."
            className="w-full rounded-lg border border-awp-border bg-awp-bg pl-8 pr-3 py-1.5 text-xs text-awp-text placeholder:text-awp-muted/50 focus:border-awp-blue/60 focus:outline-none focus:ring-1 focus:ring-awp-blue/30 transition-colors"
          />
        </div>
        <button
          onClick={handleLoadFromPath}
          disabled={!pathInput.trim()}
          className="rounded-lg border border-awp-border bg-awp-bg px-3 py-1.5 text-xs text-awp-muted hover:border-awp-blue/50 hover:text-awp-blue disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          Load
        </button>
      </div>

      {/* Skills list */}
      {skills.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-8 text-awp-muted">
          <BookOpen className="h-8 w-8 opacity-40" />
          <p className="text-xs">No skills loaded</p>
          <p className="text-[11px] text-awp-muted/60">
            Upload .md skill files or load from a path
          </p>
        </div>
      ) : (
        <div className="space-y-1.5">
          {skills.map((skill, i) => (
            <SkillCard key={`${skill.name}-${i}`} skill={skill} index={i} />
          ))}
        </div>
      )}
    </div>
  );
}

function SkillCard({ skill }: { skill: Skill; index: number }) {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-awp-border bg-awp-bg px-3 py-2.5">
      <BookOpen className="mt-0.5 h-4 w-4 shrink-0 text-awp-purple" />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-awp-text truncate">
            {skill.name}
          </span>
          {skill.loaded && (
            <span className="rounded-full bg-awp-green/15 px-1.5 py-0.5 text-[9px] font-medium text-awp-green">
              Loaded
            </span>
          )}
        </div>
        {skill.description && (
          <p className="mt-0.5 text-[11px] text-awp-muted line-clamp-2">
            {skill.description}
          </p>
        )}
        {skill.path && (
          <p className="mt-0.5 text-[10px] font-mono text-awp-muted/60 truncate">
            {skill.path}
          </p>
        )}
      </div>
      <button className="shrink-0 rounded p-1 text-awp-muted hover:bg-awp-border hover:text-awp-red transition-colors">
        <Trash2 className="h-3 w-3" />
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tools tab
// ---------------------------------------------------------------------------

const BUILTIN_TOOLS = [
  { name: 'code.execute', description: 'Execute Python code in sandbox' },
  { name: 'file.read', description: 'Read file contents' },
  { name: 'file.write', description: 'Write to a file' },
  { name: 'file.list', description: 'List directory contents' },
  { name: 'web.search', description: 'Search the web' },
  { name: 'web.fetch', description: 'Fetch a URL' },
  { name: 'web.scrape', description: 'Scrape web page content' },
  { name: 'data.query', description: 'Query structured data' },
  { name: 'math.eval', description: 'Evaluate math expressions' },
];

function ToolsTab() {
  const { config, updateConfig, mcpServers } = useWorkflowStore();
  const [showAddServer, setShowAddServer] = useState(false);

  const toggleTool = useCallback(
    (tool: string) => {
      const tools = config.tools.includes(tool)
        ? config.tools.filter((t) => t !== tool)
        : [...config.tools, tool];
      updateConfig({ tools });
    },
    [config.tools, updateConfig],
  );

  return (
    <div className="space-y-5">
      {/* Built-in tools */}
      <div className="space-y-2">
        <h4 className="text-xs font-medium text-awp-muted uppercase tracking-wide">
          Built-in Tools
        </h4>
        <div className="space-y-0.5">
          {BUILTIN_TOOLS.map((tool) => (
            <label
              key={tool.name}
              className="flex items-start gap-2.5 rounded-lg px-2 py-1.5 hover:bg-awp-bg/50 cursor-pointer transition-colors"
            >
              <input
                type="checkbox"
                checked={config.tools.includes(tool.name)}
                onChange={() => toggleTool(tool.name)}
                className="mt-0.5 rounded border-awp-border bg-awp-bg text-awp-blue focus:ring-awp-blue/30 h-3.5 w-3.5 accent-awp-blue"
              />
              <div className="flex-1 min-w-0">
                <span className="text-xs font-mono text-awp-text">
                  {tool.name}
                </span>
                <p className="text-[10px] text-awp-muted">{tool.description}</p>
              </div>
            </label>
          ))}
        </div>
      </div>

      {/* MCP Servers */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <h4 className="text-xs font-medium text-awp-muted uppercase tracking-wide">
            MCP Servers
          </h4>
          <button
            onClick={() => setShowAddServer((v) => !v)}
            className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-awp-muted hover:text-awp-blue hover:bg-awp-blue/10 transition-colors"
          >
            {showAddServer ? (
              <X className="h-3 w-3" />
            ) : (
              <Plus className="h-3 w-3" />
            )}
            {showAddServer ? 'Cancel' : 'Add Server'}
          </button>
        </div>

        {showAddServer && (
          <MCPServerForm onClose={() => setShowAddServer(false)} />
        )}

        {mcpServers.length === 0 && !showAddServer ? (
          <div className="flex flex-col items-center gap-2 py-6 text-awp-muted">
            <Server className="h-6 w-6 opacity-40" />
            <p className="text-xs">No MCP servers connected</p>
          </div>
        ) : (
          <div className="space-y-1.5">
            {mcpServers.map((server, i) => (
              <MCPServerCard key={`${server.name}-${i}`} server={server} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// MCP Server form
// ---------------------------------------------------------------------------

function MCPServerForm({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState('');
  const [command, setCommand] = useState('');
  const [args, setArgs] = useState('');
  const [envVars, setEnvVars] = useState('');

  const handleConnect = useCallback(() => {
    if (!name.trim() || !command.trim()) return;
    // Placeholder: would call API to connect MCP server
    onClose();
  }, [name, command, args, envVars, onClose]);

  return (
    <div className="space-y-3 rounded-lg border border-awp-border bg-awp-bg p-3 animate-fade-in">
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium text-awp-muted">
          Server Name
        </label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="my-mcp-server"
          className="w-full rounded-md border border-awp-border bg-awp-panel px-2.5 py-1.5 text-xs text-awp-text placeholder:text-awp-muted/50 focus:border-awp-blue/60 focus:outline-none focus:ring-1 focus:ring-awp-blue/30 transition-colors"
        />
      </div>

      <div className="space-y-1.5">
        <label className="text-[11px] font-medium text-awp-muted">
          Command
        </label>
        <input
          type="text"
          value={command}
          onChange={(e) => setCommand(e.target.value)}
          placeholder="npx -y @modelcontextprotocol/server"
          className="w-full rounded-md border border-awp-border bg-awp-panel px-2.5 py-1.5 text-xs text-awp-text font-mono placeholder:text-awp-muted/50 focus:border-awp-blue/60 focus:outline-none focus:ring-1 focus:ring-awp-blue/30 transition-colors"
        />
      </div>

      <div className="space-y-1.5">
        <label className="text-[11px] font-medium text-awp-muted">
          Arguments
        </label>
        <input
          type="text"
          value={args}
          onChange={(e) => setArgs(e.target.value)}
          placeholder="--port 3000 --stdio"
          className="w-full rounded-md border border-awp-border bg-awp-panel px-2.5 py-1.5 text-xs text-awp-text font-mono placeholder:text-awp-muted/50 focus:border-awp-blue/60 focus:outline-none focus:ring-1 focus:ring-awp-blue/30 transition-colors"
        />
      </div>

      <div className="space-y-1.5">
        <label className="text-[11px] font-medium text-awp-muted">
          Environment Variables
        </label>
        <textarea
          value={envVars}
          onChange={(e) => setEnvVars(e.target.value)}
          placeholder="KEY=value&#10;ANOTHER_KEY=value"
          rows={2}
          className="w-full resize-none rounded-md border border-awp-border bg-awp-panel px-2.5 py-1.5 text-xs text-awp-text font-mono placeholder:text-awp-muted/50 focus:border-awp-blue/60 focus:outline-none focus:ring-1 focus:ring-awp-blue/30 transition-colors"
        />
      </div>

      <div className="flex justify-end gap-2">
        <button
          onClick={onClose}
          className="rounded-md px-3 py-1.5 text-xs text-awp-muted hover:text-awp-text transition-colors"
        >
          Cancel
        </button>
        <button
          onClick={handleConnect}
          disabled={!name.trim() || !command.trim()}
          className="flex items-center gap-1.5 rounded-md bg-awp-blue/20 px-3 py-1.5 text-xs font-medium text-awp-blue hover:bg-awp-blue/30 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          <Plug className="h-3 w-3" />
          Connect
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// MCP Server card
// ---------------------------------------------------------------------------

function MCPServerCard({ server }: { server: MCPServer }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded-lg border border-awp-border bg-awp-bg overflow-hidden">
      <div className="flex items-center gap-2.5 px-3 py-2">
        <Server className="h-3.5 w-3.5 shrink-0 text-awp-muted" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-awp-text truncate">
              {server.name}
            </span>
            {server.connected ? (
              <span className="flex items-center gap-1 text-[9px] text-awp-green">
                <CheckCircle2 className="h-2.5 w-2.5" />
                Connected
              </span>
            ) : (
              <span className="flex items-center gap-1 text-[9px] text-awp-red">
                <AlertCircle className="h-2.5 w-2.5" />
                Disconnected
              </span>
            )}
          </div>
        </div>

        {server.tools.length > 0 && (
          <button
            onClick={() => setExpanded((v) => !v)}
            className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-awp-muted hover:text-awp-text transition-colors"
          >
            {expanded ? (
              <ChevronDown className="h-2.5 w-2.5" />
            ) : (
              <ChevronRight className="h-2.5 w-2.5" />
            )}
            {server.tools.length} tool{server.tools.length !== 1 ? 's' : ''}
          </button>
        )}

        <button
          className={clsx(
            'shrink-0 rounded p-1 text-xs transition-colors',
            server.connected
              ? 'text-awp-red hover:bg-awp-red/10'
              : 'text-awp-green hover:bg-awp-green/10',
          )}
        >
          {server.connected ? (
            <PlugZap className="h-3 w-3" />
          ) : (
            <Plug className="h-3 w-3" />
          )}
        </button>
      </div>

      {expanded && server.tools.length > 0 && (
        <div className="border-t border-awp-border/50 px-3 py-2 animate-fade-in">
          <div className="flex flex-wrap gap-1">
            {server.tools.map((tool) => (
              <span
                key={tool}
                className="rounded-md bg-awp-panel px-2 py-0.5 text-[10px] font-mono text-awp-muted"
              >
                {tool}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

const TABS = [
  { id: 'skills', label: 'Skills', icon: <BookOpen className="h-3 w-3" /> },
  { id: 'tools', label: 'Tools', icon: <Wrench className="h-3 w-3" /> },
];

export function SkillsTools() {
  const [activeTab, setActiveTab] = useState('skills');

  return (
    <div className="flex h-full flex-col">
      <TabBar
        tabs={TABS}
        activeTab={activeTab}
        onTabChange={setActiveTab}
      />
      <div className="flex-1 overflow-y-auto p-4">
        {activeTab === 'skills' ? <SkillsTab /> : <ToolsTab />}
      </div>
    </div>
  );
}
