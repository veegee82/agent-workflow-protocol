import React, { useCallback } from 'react';
import {
  Gauge,
  Shield,
  Code2,
  Wrench,
  Settings2,
  Zap,
  Rocket,
  Infinity,
  Feather,
} from 'lucide-react';
import { useWorkflowStore } from '@/stores/workflowStore';
import { Panel } from '@/components/Layout';
import clsx from 'clsx';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function SliderInput({
  label,
  description,
  value,
  min,
  max,
  step,
  onChange,
  format,
}: {
  label: string;
  description?: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
  format?: (v: number) => string;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <label className="text-xs font-medium text-awp-text">{label}</label>
        <span className="text-xs font-mono text-awp-blue">
          {format ? format(value) : value.toLocaleString()}
        </span>
      </div>
      {description && (
        <p className="text-[11px] text-awp-muted">{description}</p>
      )}
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full h-1.5 rounded-full appearance-none bg-awp-border cursor-pointer accent-awp-blue [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:h-3.5 [&::-webkit-slider-thumb]:w-3.5 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-awp-blue [&::-webkit-slider-thumb]:shadow-md [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-awp-panel"
      />
      <div className="flex items-center justify-between text-[10px] text-awp-muted">
        <span>{format ? format(min) : min}</span>
        <span>{format ? format(max) : max}</span>
      </div>
    </div>
  );
}

function ToggleSwitch({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="flex-1">
        <label className="text-xs font-medium text-awp-text">{label}</label>
        {description && (
          <p className="text-[11px] text-awp-muted mt-0.5">{description}</p>
        )}
      </div>
      <button
        type="button"
        onClick={() => onChange(!checked)}
        className={clsx(
          'relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border-2 border-transparent transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-awp-blue/50',
          checked ? 'bg-awp-blue' : 'bg-awp-border',
        )}
      >
        <span
          className={clsx(
            'inline-block h-3.5 w-3.5 rounded-full bg-white shadow-sm transition-transform duration-200',
            checked ? 'translate-x-4' : 'translate-x-0.5',
          )}
        />
      </button>
    </div>
  );
}

function RadioGroup({
  label,
  description,
  options,
  value,
  onChange,
}: {
  label: string;
  description?: string;
  options: { value: string; label: string }[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="space-y-2">
      <div>
        <label className="text-xs font-medium text-awp-text">{label}</label>
        {description && (
          <p className="text-[11px] text-awp-muted mt-0.5">{description}</p>
        )}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {options.map((opt) => (
          <button
            key={opt.value}
            type="button"
            onClick={() => onChange(opt.value)}
            className={clsx(
              'rounded-md border px-2.5 py-1 text-xs font-medium transition-colors',
              value === opt.value
                ? 'border-awp-blue bg-awp-blue/15 text-awp-blue'
                : 'border-awp-border text-awp-muted hover:border-awp-muted hover:text-awp-text',
            )}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function TextInput({
  label,
  description,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  description?: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <div className="space-y-1.5">
      <label className="text-xs font-medium text-awp-text">{label}</label>
      {description && (
        <p className="text-[11px] text-awp-muted">{description}</p>
      )}
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-lg border border-awp-border bg-awp-bg px-3 py-1.5 text-xs text-awp-text placeholder:text-awp-muted/50 focus:border-awp-blue/60 focus:outline-none focus:ring-1 focus:ring-awp-blue/30 transition-colors"
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Presets
// ---------------------------------------------------------------------------

interface Preset {
  name: string;
  icon: React.ReactNode;
  values: Record<string, unknown>;
}

const PRESETS: Preset[] = [
  {
    name: 'Light',
    icon: <Feather className="h-3 w-3" />,
    values: {
      max_loops: 5,
      max_total_tokens: 200_000,
      max_wall_time: 60,
      max_total_workers: 2,
      max_tool_calls: 20,
      max_depth: 1,
    },
  },
  {
    name: 'Standard',
    icon: <Zap className="h-3 w-3" />,
    values: {
      max_loops: 20,
      max_total_tokens: 2_000_000,
      max_wall_time: 600,
      max_total_workers: 10,
      max_tool_calls: 200,
      max_depth: 3,
    },
  },
  {
    name: 'Heavy',
    icon: <Rocket className="h-3 w-3" />,
    values: {
      max_loops: 100,
      max_total_tokens: 10_000_000,
      max_wall_time: 3600,
      max_total_workers: 50,
      max_tool_calls: 1000,
      max_depth: 5,
    },
  },
  {
    name: 'Unlimited',
    icon: <Infinity className="h-3 w-3" />,
    values: {
      max_loops: 999,
      max_total_tokens: 100_000_000,
      max_wall_time: 86400,
      max_total_workers: 999,
      max_tool_calls: 99999,
      max_depth: 10,
    },
  },
];

// ---------------------------------------------------------------------------
// Tools checklist
// ---------------------------------------------------------------------------

const BUILTIN_TOOLS = [
  'code.execute',
  'file.read',
  'file.write',
  'file.list',
  'web.search',
  'web.fetch',
  'web.scrape',
  'data.query',
  'math.eval',
];

function ToolsChecklist({
  selected,
  onChange,
}: {
  selected: string[];
  onChange: (tools: string[]) => void;
}) {
  const toggle = (tool: string) => {
    if (selected.includes(tool)) {
      onChange(selected.filter((t) => t !== tool));
    } else {
      onChange([...selected, tool]);
    }
  };

  return (
    <div className="space-y-1">
      {BUILTIN_TOOLS.map((tool) => (
        <label
          key={tool}
          className="flex items-center gap-2 rounded-md px-2 py-1 text-xs hover:bg-awp-bg/50 cursor-pointer transition-colors"
        >
          <input
            type="checkbox"
            checked={selected.includes(tool)}
            onChange={() => toggle(tool)}
            className="rounded border-awp-border bg-awp-bg text-awp-blue focus:ring-awp-blue/30 h-3.5 w-3.5 accent-awp-blue"
          />
          <span className="font-mono text-awp-text">{tool}</span>
        </label>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

export function SettingsPanel() {
  const { config, updateConfig } = useWorkflowStore();

  const applyPreset = useCallback(
    (preset: Preset) => {
      updateConfig(preset.values as Record<string, unknown>);
    },
    [updateConfig],
  );

  const formatTokens = (v: number) => {
    if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
    if (v >= 1_000) return `${(v / 1_000).toFixed(0)}K`;
    return String(v);
  };

  const formatTime = (v: number) => {
    if (v >= 3600) return `${(v / 3600).toFixed(1)}h`;
    if (v >= 60) return `${(v / 60).toFixed(0)}m`;
    return `${v}s`;
  };

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto p-4">
      {/* Presets */}
      <div className="space-y-2">
        <label className="text-xs font-medium text-awp-muted uppercase tracking-wide">
          Presets
        </label>
        <div className="grid grid-cols-4 gap-1.5">
          {PRESETS.map((preset) => (
            <button
              key={preset.name}
              onClick={() => applyPreset(preset)}
              className="flex flex-col items-center gap-1 rounded-lg border border-awp-border bg-awp-bg px-2 py-2 text-xs text-awp-muted hover:border-awp-blue/50 hover:text-awp-blue hover:bg-awp-blue/5 transition-colors"
            >
              {preset.icon}
              <span className="text-[10px] font-medium">{preset.name}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Budget */}
      <Panel
        title="Budget"
        icon={<Gauge className="h-3.5 w-3.5 text-awp-blue" />}
        defaultOpen
      >
        <div className="space-y-4">
          <SliderInput
            label="Max Loops"
            description="Maximum delegation loop iterations"
            value={config.max_loops}
            min={1}
            max={200}
            step={1}
            onChange={(v) => updateConfig({ max_loops: v })}
          />
          <SliderInput
            label="Max Tokens"
            description="Total token budget across all workers"
            value={config.max_total_tokens}
            min={10_000}
            max={50_000_000}
            step={10_000}
            onChange={(v) => updateConfig({ max_total_tokens: v })}
            format={formatTokens}
          />
          <SliderInput
            label="Max Wall Time"
            description="Maximum execution time"
            value={config.max_wall_time}
            min={10}
            max={86400}
            step={10}
            onChange={(v) => updateConfig({ max_wall_time: v })}
            format={formatTime}
          />
          <SliderInput
            label="Max Workers"
            description="Maximum number of concurrent workers"
            value={config.max_total_workers}
            min={1}
            max={100}
            step={1}
            onChange={(v) => updateConfig({ max_total_workers: v })}
          />
          <SliderInput
            label="Max Tool Calls"
            description="Total tool call budget"
            value={config.max_tool_calls}
            min={1}
            max={10000}
            step={1}
            onChange={(v) => updateConfig({ max_tool_calls: v })}
          />
          <SliderInput
            label="Max Depth"
            description="Maximum delegation depth"
            value={config.max_depth}
            min={1}
            max={10}
            step={1}
            onChange={(v) => updateConfig({ max_depth: v })}
          />
        </div>
      </Panel>

      {/* Sandbox */}
      <Panel
        title="Sandbox"
        icon={<Shield className="h-3.5 w-3.5 text-awp-green" />}
        defaultOpen={false}
      >
        <div className="space-y-4">
          <RadioGroup
            label="Execution Environment"
            description="How agent code is sandboxed"
            options={[
              { value: 'subprocess', label: 'Subprocess' },
              { value: 'docker', label: 'Docker' },
              { value: 'venv', label: 'Venv' },
              { value: 'none', label: 'None' },
            ]}
            value={config.sandbox}
            onChange={(v) =>
              updateConfig({ sandbox: v as 'subprocess' | 'docker' | 'venv' | 'none' })
            }
          />
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-awp-text">
              Packages
            </label>
            <p className="text-[11px] text-awp-muted">
              Python packages to install (one per line)
            </p>
            <textarea
              value={config.packages.join('\n')}
              onChange={(e) =>
                updateConfig({
                  packages: e.target.value
                    .split('\n')
                    .map((s) => s.trim())
                    .filter(Boolean),
                })
              }
              placeholder="numpy&#10;pandas&#10;matplotlib"
              rows={3}
              className="w-full resize-none rounded-lg border border-awp-border bg-awp-bg px-3 py-2 text-xs text-awp-text font-mono placeholder:text-awp-muted/50 focus:border-awp-blue/60 focus:outline-none focus:ring-1 focus:ring-awp-blue/30 transition-colors"
            />
          </div>
        </div>
      </Panel>

      {/* Code Execution */}
      <Panel
        title="Code Execution"
        icon={<Code2 className="h-3.5 w-3.5 text-awp-cyan" />}
        defaultOpen={false}
      >
        <div className="space-y-4">
          <ToggleSwitch
            label="Code Mode"
            description="Enable code execution by agents"
            checked={config.code_mode}
            onChange={(v) => updateConfig({ code_mode: v })}
          />
          <ToggleSwitch
            label="Tool Creation"
            description="Allow agents to create new tools at runtime"
            checked={config.tool_creation}
            onChange={(v) => updateConfig({ tool_creation: v })}
          />
        </div>
      </Panel>

      {/* Tools */}
      <Panel
        title="Tools"
        icon={<Wrench className="h-3.5 w-3.5 text-awp-yellow" />}
        defaultOpen={false}
      >
        <div className="space-y-4">
          <div className="space-y-2">
            <label className="text-xs font-medium text-awp-text">
              Allowed Tools
            </label>
            <ToolsChecklist
              selected={config.tools}
              onChange={(tools) => updateConfig({ tools })}
            />
          </div>
          <TextInput
            label="Forbidden Tools"
            description="Comma-separated list of tools to forbid"
            value={config.forbidden_tools.join(', ')}
            onChange={(v) =>
              updateConfig({
                forbidden_tools: v
                  .split(',')
                  .map((s) => s.trim())
                  .filter(Boolean),
              })
            }
            placeholder="shell.execute, file.delete"
          />
        </div>
      </Panel>

      {/* Advanced */}
      <Panel
        title="Advanced"
        icon={<Settings2 className="h-3.5 w-3.5 text-awp-purple" />}
        defaultOpen={false}
      >
        <div className="space-y-4">
          <ToggleSwitch
            label="Verbose Logging"
            description="Show detailed execution logs"
            checked={config.verbose}
            onChange={(v) => updateConfig({ verbose: v })}
          />
        </div>
      </Panel>
    </div>
  );
}
