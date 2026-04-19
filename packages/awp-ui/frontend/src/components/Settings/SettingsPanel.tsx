import React, { useCallback, useEffect, useState } from 'react';
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
  Key,
  Trash2,
  Plus,
  Cpu,
  BookOpen,
  FolderOpen,
  FileText,
  Archive,
  Folder,
  Loader2,
  AlertCircle,
  Check,
  Brain,
  Sparkles,
  Dna,
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
      max_total_workers: 5,
      max_tool_calls: 20,
      max_depth: 2,
    },
  },
  {
    name: 'Standard',
    icon: <Zap className="h-3 w-3" />,
    values: {
      max_loops: 30,
      max_total_tokens: 2_000_000,
      max_wall_time: 600,
      max_total_workers: 50,
      max_tool_calls: 200,
      max_depth: 10,
    },
  },
  {
    name: 'Heavy',
    icon: <Rocket className="h-3 w-3" />,
    values: {
      max_loops: 100,
      max_total_tokens: 10_000_000,
      max_wall_time: 7200,
      max_total_workers: 1000,
      max_tool_calls: 1000,
      max_depth: 100,
    },
  },
  {
    name: 'Unlimited',
    icon: <Infinity className="h-3 w-3" />,
    values: {
      max_loops: 1000,
      max_total_tokens: 100_000_000,
      max_wall_time: 86400,
      max_total_workers: 10000,
      max_tool_calls: 99999,
      max_depth: 100,
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

// ---------------------------------------------------------------------------
// API Keys section
// ---------------------------------------------------------------------------

/** Expected key prefix per provider — used for format validation hints. */
const KEY_FORMAT_HINTS: Record<string, { prefix: string; placeholder: string; hint: string }> = {
  OPENROUTER_API_KEY: {
    prefix: 'sk-or-',
    placeholder: 'sk-or-v1-abc123...',
    hint: 'Starts with sk-or-. Get yours at openrouter.ai/keys',
  },
  OPENAI_API_KEY: {
    prefix: 'sk-',
    placeholder: 'sk-proj-abc123...',
    hint: 'Starts with sk-. Get yours at platform.openai.com/api-keys',
  },
  ANTHROPIC_API_KEY: {
    prefix: 'sk-ant-',
    placeholder: 'sk-ant-api03-abc123...',
    hint: 'Starts with sk-ant-. Get yours at console.anthropic.com',
  },
  LLM_API_KEY: {
    prefix: '',
    placeholder: 'your-api-key...',
    hint: 'Universal fallback key. Format depends on your provider.',
  },
};

function ApiKeysSection() {
  const { secrets, loadSecrets, addSecret, removeSecret } = useWorkflowStore();
  const [newKey, setNewKey] = useState('OPENROUTER_API_KEY');
  const [newValue, setNewValue] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [keyError, setKeyError] = useState('');

  useEffect(() => {
    loadSecrets();
  }, [loadSecrets]);

  const validateKeyFormat = (provider: string, value: string): string => {
    const fmt = KEY_FORMAT_HINTS[provider];
    if (!fmt || !fmt.prefix || !value.trim()) return '';
    if (!value.startsWith(fmt.prefix)) {
      return `This doesn't look like a valid ${provider.replace('_API_KEY', '').replace('_', ' ')} key. Expected prefix: ${fmt.prefix}`;
    }
    if (value.trim().length < 20) {
      return 'Key seems too short. Please paste the full key.';
    }
    return '';
  };

  const handleAdd = async () => {
    if (!newKey.trim() || !newValue.trim()) return;
    const error = validateKeyFormat(newKey, newValue);
    if (error) {
      setKeyError(error);
      return;
    }
    await addSecret(newKey.trim(), newValue.trim());
    setNewValue('');
    setKeyError('');
    setShowForm(false);
  };

  const handleValueChange = (v: string) => {
    setNewValue(v);
    if (keyError) setKeyError(validateKeyFormat(newKey, v));
  };

  const handleKeyChange = (k: string) => {
    setNewKey(k);
    setKeyError('');
    setNewValue('');
  };

  const hasOpenRouterKey = secrets.some((s) => s.key === 'OPENROUTER_API_KEY');
  const currentHint = KEY_FORMAT_HINTS[newKey] ?? KEY_FORMAT_HINTS.LLM_API_KEY;

  return (
    <Panel
      title="API Keys"
      icon={<Key className="h-3.5 w-3.5 text-awp-yellow" />}
      defaultOpen
    >
      <div className="space-y-3">
        {!hasOpenRouterKey && secrets.length === 0 && (
          <div className="rounded-lg border border-awp-yellow/30 bg-awp-yellow/5 px-3 py-2">
            <p className="text-[11px] text-awp-yellow font-medium">
              No API key configured.
            </p>
            <p className="text-[10px] text-awp-yellow/80 mt-1">
              AWP uses <span className="font-semibold">OpenRouter</span> to access all models.
              Get a free key at{' '}
              <span className="font-mono underline">openrouter.ai/keys</span> and add it as{' '}
              <span className="font-mono">OPENROUTER_API_KEY</span>.
            </p>
          </div>
        )}

        {secrets.length > 0 && (
          <div className="space-y-1.5">
            {secrets.map((sec) => (
              <div
                key={sec.key}
                className="flex items-center justify-between rounded-md border border-awp-border bg-awp-bg px-3 py-1.5"
              >
                <div className="flex items-center gap-2">
                  <Key className="h-3 w-3 text-awp-green" />
                  <span className="text-xs font-mono text-awp-text">{sec.key}</span>
                </div>
                <button
                  onClick={() => removeSecret(sec.key)}
                  className="p-1 rounded text-awp-muted hover:text-awp-red transition-colors"
                  title="Remove"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            ))}
          </div>
        )}

        {showForm ? (
          <div className="space-y-2 rounded-lg border border-awp-border bg-awp-bg p-3">
            <select
              value={newKey}
              onChange={(e) => handleKeyChange(e.target.value)}
              className="w-full rounded-md border border-awp-border bg-awp-panel px-2.5 py-1.5 text-xs text-awp-text focus:border-awp-blue/60 focus:outline-none"
            >
              <option value="OPENROUTER_API_KEY">OPENROUTER_API_KEY (recommended)</option>
              <option value="OPENAI_API_KEY">OPENAI_API_KEY</option>
              <option value="ANTHROPIC_API_KEY">ANTHROPIC_API_KEY</option>
              <option value="LLM_API_KEY">LLM_API_KEY (universal fallback)</option>
            </select>

            <p className="text-[10px] text-awp-muted">
              {currentHint.hint}
            </p>

            <input
              type="password"
              value={newValue}
              onChange={(e) => handleValueChange(e.target.value)}
              placeholder={currentHint.placeholder}
              className={clsx(
                'w-full rounded-md border bg-awp-panel px-2.5 py-1.5 text-xs font-mono text-awp-text placeholder:text-awp-muted/50 focus:outline-none transition-colors',
                keyError
                  ? 'border-awp-red/60 focus:border-awp-red/80 focus:ring-1 focus:ring-awp-red/30'
                  : 'border-awp-border focus:border-awp-blue/60 focus:ring-1 focus:ring-awp-blue/30',
              )}
              onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
            />

            {keyError && (
              <p className="text-[10px] text-awp-red">
                {keyError}
              </p>
            )}

            <div className="flex gap-2">
              <button
                onClick={handleAdd}
                disabled={!newValue.trim()}
                className="flex-1 rounded-md bg-awp-blue px-3 py-1.5 text-xs font-medium text-white hover:bg-awp-blue/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Save
              </button>
              <button
                onClick={() => { setShowForm(false); setNewValue(''); setKeyError(''); }}
                className="rounded-md border border-awp-border px-3 py-1.5 text-xs text-awp-muted hover:text-awp-text transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <button
            onClick={() => setShowForm(true)}
            className="flex items-center gap-1.5 rounded-md border border-dashed border-awp-border px-3 py-1.5 text-xs text-awp-muted hover:border-awp-blue/50 hover:text-awp-blue transition-colors w-full justify-center"
          >
            <Plus className="h-3 w-3" />
            Add API Key
          </button>
        )}
      </div>
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// Model routing – detect provider from model string
// ---------------------------------------------------------------------------

type ProviderRoute = {
  provider: string;
  apiBase: string;
  requiredKey: string;
  color: string;
  hint: string;
};

/** Detect provider and required API key from a model string. */
function detectProvider(model: string): ProviderRoute {
  const m = model.toLowerCase().trim();

  // Direct OpenAI models (gpt-*, o1-*, o3-*, dall-e-*, etc.)
  if (/^(gpt-|o[0-9]|dall-e|text-|tts-|whisper)/.test(m)) {
    return {
      provider: 'OpenAI (direct)',
      apiBase: 'https://api.openai.com/v1',
      requiredKey: 'OPENAI_API_KEY',
      color: 'text-awp-green',
      hint: 'Direct OpenAI API. Requires OPENAI_API_KEY (sk-...).',
    };
  }

  // Direct Anthropic models (claude-*)
  if (/^claude-/.test(m)) {
    return {
      provider: 'Anthropic (direct)',
      apiBase: 'https://api.anthropic.com/v1',
      requiredKey: 'ANTHROPIC_API_KEY',
      color: 'text-awp-purple',
      hint: 'Direct Anthropic API. Requires ANTHROPIC_API_KEY (sk-ant-...).',
    };
  }

  // Ollama – localhost models or explicit ollama/ prefix
  if (m.startsWith('ollama/') || m.startsWith('localhost') || m.startsWith('http://localhost')) {
    return {
      provider: 'Ollama (local)',
      apiBase: 'http://localhost:11434/v1',
      requiredKey: '',
      color: 'text-awp-yellow',
      hint: 'Local Ollama instance. No API key needed – make sure Ollama is running.',
    };
  }

  // Everything else → OpenRouter (provider/model format)
  return {
    provider: 'OpenRouter',
    apiBase: 'https://openrouter.ai/api/v1',
    requiredKey: 'OPENROUTER_API_KEY',
    color: 'text-awp-blue',
    hint: 'Routed via OpenRouter. Requires OPENROUTER_API_KEY (sk-or-...).',
  };
}

/** Example model strings shown as quick-paste helpers. */
const MODEL_EXAMPLES = [
  { id: 'nvidia/nemotron-3-super-120b-a12b',      label: 'Nemotron 3 Super 120B',   provider: 'OpenRouter' },
  { id: 'deepseek/deepseek-chat-v3-0324:free',    label: 'DeepSeek V3 (free)',      provider: 'OpenRouter' },
  { id: 'google/gemini-2.5-pro-exp-03-25:free',   label: 'Gemini 2.5 Pro (free)',   provider: 'OpenRouter' },
  { id: 'meta-llama/llama-4-maverick:free',        label: 'Llama 4 Maverick (free)', provider: 'OpenRouter' },
  { id: 'qwen/qwen3-235b-a22b:free',              label: 'Qwen3 235B (free)',       provider: 'OpenRouter' },
  { id: 'anthropic/claude-sonnet-4',              label: 'Claude Sonnet 4',         provider: 'OpenRouter' },
  { id: 'anthropic/claude-opus-4',                label: 'Claude Opus 4',           provider: 'OpenRouter' },
  { id: 'openai/gpt-4.1',                         label: 'GPT-4.1',                 provider: 'OpenRouter' },
  { id: 'openai/o3',                               label: 'OpenAI o3',               provider: 'OpenRouter' },
  { id: 'deepseek/deepseek-r1',                   label: 'DeepSeek R1',             provider: 'OpenRouter' },
  { id: 'claude-sonnet-4-20250514',               label: 'Claude Sonnet 4',         provider: 'Anthropic' },
  { id: 'gpt-4.1',                                 label: 'GPT-4.1',                 provider: 'OpenAI' },
  { id: 'ollama/llama3',                           label: 'Llama 3 (local)',         provider: 'Ollama' },
] as const;

function ModelSection() {
  const { config, updateConfig, secrets } = useWorkflowStore();

  const route = detectProvider(config.model);
  const hasRequiredKey = !route.requiredKey || secrets.some((s) => s.key === route.requiredKey);

  return (
    <Panel
      title="Model"
      icon={<Cpu className="h-3.5 w-3.5 text-awp-blue" />}
      defaultOpen
    >
      <div className="space-y-3">
        {/* Manager model input */}
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-awp-text">Manager Model</label>
          <input
            type="text"
            value={config.model}
            onChange={(e) => updateConfig({ model: e.target.value })}
            placeholder="openai/gpt-5-mini"
            className="w-full rounded-lg border border-awp-border bg-awp-bg px-3 py-1.5 text-xs font-mono text-awp-text placeholder:text-awp-muted/50 focus:border-awp-blue/60 focus:outline-none focus:ring-1 focus:ring-awp-blue/30 transition-colors"
          />
        </div>

        {/* Auto-detected routing */}
        <div className={clsx(
          'rounded-lg border px-3 py-2 space-y-1',
          hasRequiredKey ? 'border-awp-border bg-awp-bg' : 'border-awp-yellow/30 bg-awp-yellow/5',
        )}>
          <div className="flex items-center gap-2">
            <span className={clsx('text-[10px] font-semibold uppercase tracking-wide', route.color)}>
              {route.provider}
            </span>
            {hasRequiredKey ? (
              <span className="text-[10px] text-awp-green font-medium">Ready</span>
            ) : (
              <span className="text-[10px] text-awp-yellow font-medium">Key missing</span>
            )}
          </div>
          <p className="text-[10px] text-awp-muted">{route.hint}</p>
          {!hasRequiredKey && route.requiredKey && (
            <p className="text-[10px] text-awp-yellow/90 mt-1">
              Add <span className="font-mono font-semibold">{route.requiredKey}</span> in the API Keys section above.
            </p>
          )}
        </div>

        {/* Quick-paste examples */}
        <div className="space-y-1.5">
          <label className="text-[10px] font-medium text-awp-muted uppercase tracking-wide">
            Quick select
          </label>
          <div className="flex flex-wrap gap-1">
            {MODEL_EXAMPLES.map((ex) => {
              const isActive = config.model === ex.id;
              return (
                <button
                  key={ex.id}
                  onClick={() => updateConfig({ model: ex.id })}
                  title={`${ex.id} (${ex.provider})`}
                  className={clsx(
                    'rounded-md border px-2 py-0.5 text-[10px] font-medium transition-colors',
                    isActive
                      ? 'border-awp-blue bg-awp-blue/15 text-awp-blue'
                      : 'border-awp-border text-awp-muted hover:border-awp-muted hover:text-awp-text',
                  )}
                >
                  {ex.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Worker model input */}
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-awp-text">Worker Model</label>
          <p className="text-[11px] text-awp-muted">
            Optional. Leave empty to use the manager model for workers too.
          </p>
          <input
            type="text"
            value={config.worker_model ?? ''}
            onChange={(e) => updateConfig({ worker_model: e.target.value || undefined })}
            placeholder="deepseek/deepseek-chat-v3.1"
            className="w-full rounded-lg border border-awp-border bg-awp-bg px-3 py-1.5 text-xs font-mono text-awp-text placeholder:text-awp-muted/50 focus:border-awp-blue/60 focus:outline-none focus:ring-1 focus:ring-awp-blue/30 transition-colors"
          />
        </div>

        {/* Routing rules info */}
        <div className="rounded-lg border border-awp-border/50 bg-awp-bg/50 px-3 py-2 space-y-1">
          <p className="text-[10px] font-semibold text-awp-text">Auto-routing rules</p>
          <div className="text-[10px] text-awp-muted leading-relaxed space-y-0.5">
            <p><span className="font-mono text-awp-blue">provider/model</span> → OpenRouter (OPENROUTER_API_KEY)</p>
            <p><span className="font-mono text-awp-green">gpt-*</span>, <span className="font-mono text-awp-green">o3</span> → OpenAI direct (OPENAI_API_KEY)</p>
            <p><span className="font-mono text-awp-purple">claude-*</span> → Anthropic direct (ANTHROPIC_API_KEY)</p>
            <p><span className="font-mono text-awp-yellow">ollama/*</span> → Local Ollama (no key)</p>
          </div>
        </div>
      </div>
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// Skills section
// ---------------------------------------------------------------------------

interface ScannedSkill {
  name: string;
  path: string;
  type: 'file' | 'directory' | 'archive';
  size?: number;
}

function SkillsSection() {
  const { config, updateConfig } = useWorkflowStore();
  const [scannedSkills, setScannedSkills] = useState<ScannedSkill[]>([]);
  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState('');
  const [lastScannedDir, setLastScannedDir] = useState('');

  // Scan directory when skills_dir changes (debounced)
  useEffect(() => {
    const dir = config.skills_dir?.trim();
    if (!dir || dir === lastScannedDir) return;

    const timeout = setTimeout(async () => {
      setScanning(true);
      setScanError('');
      try {
        const { scanSkillsDirectory } = await import('@/api/client');
        const result = await scanSkillsDirectory(dir);
        setScannedSkills(result.skills);
        setLastScannedDir(dir);
        setScanError('');
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        // Only show error if it's not a "directory not found" on partial typing
        if (dir.length > 2) {
          setScanError(msg.replace(/^API \d+: /, ''));
        }
        setScannedSkills([]);
      } finally {
        setScanning(false);
      }
    }, 500);

    return () => clearTimeout(timeout);
  }, [config.skills_dir, lastScannedDir]);

  // Clear scanned skills when directory is emptied
  useEffect(() => {
    if (!config.skills_dir?.trim()) {
      setScannedSkills([]);
      setLastScannedDir('');
      setScanError('');
    }
  }, [config.skills_dir]);

  const skillIcon = (type: string) => {
    switch (type) {
      case 'directory': return <Folder className="h-3 w-3 text-awp-blue" />;
      case 'archive': return <Archive className="h-3 w-3 text-awp-yellow" />;
      default: return <FileText className="h-3 w-3 text-awp-cyan" />;
    }
  };

  const formatSize = (bytes?: number) => {
    if (!bytes) return '';
    if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${bytes} B`;
  };

  return (
    <Panel
      title="Skills"
      icon={<BookOpen className="h-3.5 w-3.5 text-awp-purple" />}
      defaultOpen={false}
    >
      <div className="space-y-3">
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-awp-text">Skills Directory</label>
          <p className="text-[11px] text-awp-muted">
            Path to a folder containing skills (.md files, SKILL.md directories, or .zip archives).
            All skills will be available to the manager agent.
          </p>
          <div className="flex gap-1.5">
            <div className="relative flex-1">
              <FolderOpen className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3 w-3 text-awp-muted" />
              <input
                type="text"
                value={config.skills_dir || ''}
                onChange={(e) => updateConfig({ skills_dir: e.target.value })}
                placeholder="/path/to/skills"
                className="w-full rounded-lg border border-awp-border bg-awp-bg pl-7 pr-3 py-1.5 text-xs text-awp-text font-mono placeholder:text-awp-muted/50 focus:border-awp-blue/60 focus:outline-none focus:ring-1 focus:ring-awp-blue/30 transition-colors"
              />
            </div>
          </div>
        </div>

        {/* Scanning indicator */}
        {scanning && (
          <div className="flex items-center gap-2 px-2 py-1.5">
            <Loader2 className="h-3 w-3 text-awp-blue animate-spin" />
            <span className="text-[11px] text-awp-muted">Scanning directory...</span>
          </div>
        )}

        {/* Error message */}
        {scanError && !scanning && (
          <div className="flex items-start gap-2 rounded-lg border border-awp-red/30 bg-awp-red/5 px-3 py-2">
            <AlertCircle className="h-3 w-3 text-awp-red mt-0.5 shrink-0" />
            <p className="text-[11px] text-awp-red">{scanError}</p>
          </div>
        )}

        {/* Scanned skills list */}
        {scannedSkills.length > 0 && !scanning && (
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <label className="text-[10px] font-medium text-awp-muted uppercase tracking-wide">
                Found Skills
              </label>
              <div className="flex items-center gap-1">
                <Check className="h-3 w-3 text-awp-green" />
                <span className="text-[10px] text-awp-green font-medium">
                  {scannedSkills.length} skill{scannedSkills.length !== 1 ? 's' : ''}
                </span>
              </div>
            </div>
            <div className="rounded-lg border border-awp-border bg-awp-bg divide-y divide-awp-border/50 max-h-40 overflow-y-auto">
              {scannedSkills.map((skill) => (
                <div
                  key={skill.path}
                  className="flex items-center gap-2 px-2.5 py-1.5"
                  title={skill.path}
                >
                  {skillIcon(skill.type)}
                  <span className="text-xs text-awp-text flex-1 truncate">
                    {skill.name}
                  </span>
                  <span className="text-[10px] text-awp-muted shrink-0">
                    {skill.type === 'directory' ? 'dir' : formatSize(skill.size)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Empty state */}
        {config.skills_dir?.trim() && !scanning && !scanError && scannedSkills.length === 0 && lastScannedDir && (
          <div className="rounded-lg border border-awp-border/50 bg-awp-bg/50 px-3 py-2">
            <p className="text-[11px] text-awp-muted">
              No skills found in this directory. Skills can be:
            </p>
            <ul className="text-[10px] text-awp-muted mt-1 space-y-0.5 list-disc list-inside">
              <li><span className="font-mono">.md</span> files (single-file skills)</li>
              <li>Subdirectories with a <span className="font-mono">SKILL.md</span> file</li>
              <li><span className="font-mono">.zip</span> or <span className="font-mono">.skill</span> archives</li>
            </ul>
          </div>
        )}
      </div>
    </Panel>
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

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto p-4">
      {/* API Keys */}
      <ApiKeysSection />

      {/* Model */}
      <ModelSection />

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

      {/* Budget Limits */}
      <Panel
        title="Budget Limits"
        icon={<Gauge className="h-3.5 w-3.5 text-awp-blue" />}
        defaultOpen
      >
        <div className="space-y-4">
          <SliderInput
            label="Max Loops"
            description="Manager delegation loop iterations (think → delegate → evaluate = 1 loop)"
            value={config.max_loops}
            min={1}
            max={1000}
            step={1}
            onChange={(v) => updateConfig({ max_loops: v })}
          />
          <SliderInput
            label="Max Tokens"
            description="Total LLM tokens in millions (e.g. 1.2 = 1,200,000)"
            value={config.max_total_tokens / 1_000_000}
            min={0.1}
            max={100}
            step={0.1}
            onChange={(v) =>
              updateConfig({ max_total_tokens: Math.round(v * 1_000_000) })
            }
            format={(v) => `${v.toFixed(1)}M`}
          />
          <SliderInput
            label="Max Wall Time"
            description="Maximum real-world execution time in minutes"
            value={Math.round(config.max_wall_time / 60)}
            min={1}
            max={1440}
            step={1}
            onChange={(v) => updateConfig({ max_wall_time: v * 60 })}
            format={(v) => `${v} min`}
          />
          <SliderInput
            label="Max Workers"
            description="Maximum total worker agents spawned across all iterations"
            value={config.max_total_workers}
            min={1}
            max={10000}
            step={1}
            onChange={(v) => updateConfig({ max_total_workers: v })}
          />
          <SliderInput
            label="Max Tool Calls"
            description="Maximum total tool invocations (code.execute, file.write, etc.) per worker"
            value={config.max_tool_calls}
            min={1}
            max={10000}
            step={1}
            onChange={(v) => updateConfig({ max_tool_calls: v })}
          />
          <SliderInput
            label="Max Depth"
            description="Maximum recursive delegation depth (worker → sub-worker → sub-sub-worker...)"
            value={config.max_depth}
            min={1}
            max={100}
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

      {/* Manager Intelligence */}
      <Panel
        title="Manager Intelligence"
        icon={<Brain className="h-3.5 w-3.5 text-awp-purple" />}
        defaultOpen
      >
        <div className="space-y-4">
          <p className="text-[11px] text-awp-muted leading-relaxed">
            Enhanced problem-solving capabilities for the delegation loop manager.
            These features improve planning, debugging, adaptation, and self-reflection.
          </p>
          <ToggleSwitch
            label="Task Decomposition"
            description="Manager creates an explicit task plan before delegating work"
            checked={config.planning_enabled}
            onChange={(v) => updateConfig({ planning_enabled: v })}
          />
          {config.planning_enabled && (
            <SliderInput
              label="Max Subtasks"
              description="Maximum subtasks in a plan"
              value={config.planning_max_subtasks}
              min={2}
              max={20}
              step={1}
              onChange={(v) => updateConfig({ planning_max_subtasks: v })}
            />
          )}
          <ToggleSwitch
            label="Hypothesis Debugging"
            description="On worker failure, generate causal hypotheses before retrying"
            checked={config.diagnosis_enabled}
            onChange={(v) => updateConfig({ diagnosis_enabled: v })}
          />
          {config.diagnosis_enabled && (
            <SliderInput
              label="Confidence Threshold"
              description="Trigger diagnosis when worker confidence drops below this"
              value={config.diagnosis_confidence_threshold * 100}
              min={5}
              max={80}
              step={5}
              onChange={(v) => updateConfig({ diagnosis_confidence_threshold: v / 100 })}
              format={(v) => `${v}%`}
            />
          )}
          <ToggleSwitch
            label="Strategy Switching"
            description="Rotate through meta-strategies on stall instead of stopping"
            checked={config.strategy_switching_enabled}
            onChange={(v) => updateConfig({ strategy_switching_enabled: v })}
          />
          <ToggleSwitch
            label="Budget Reservation"
            description="Pre-allocate budget to phases (60% work, 20% validation, 15% synthesis, 5% reserve)"
            checked={config.budget_reservation_enabled}
            onChange={(v) => updateConfig({ budget_reservation_enabled: v })}
          />
          <ToggleSwitch
            label="Decision Journal"
            description="Manager tracks its decisions and outcomes for self-correction"
            checked={config.decision_journal_enabled}
            onChange={(v) => updateConfig({ decision_journal_enabled: v })}
          />
          {config.decision_journal_enabled && (
            <SliderInput
              label="Max Journal Entries"
              description="Oldest entries evicted when exceeded"
              value={config.decision_journal_max_entries}
              min={5}
              max={50}
              step={5}
              onChange={(v) => updateConfig({ decision_journal_max_entries: v })}
            />
          )}
        </div>
      </Panel>

      {/* Optimizers — two SGD modes exposed by awp: θ-axis (outer loop)
          and y-axis (refinement). Not invoked inline by a single run;
          these are defaults for the separate awp optimize / awp refine
          workflows. */}
      <Panel
        title="Optimizers"
        icon={<Dna className="h-3.5 w-3.5 text-awp-blue" />}
        defaultOpen={false}
      >
        <div className="space-y-5">
          <p className="text-[11px] text-awp-muted leading-relaxed">
            Two SGD modes run outside a normal{' '}
            <code className="rounded bg-awp-border/40 px-1 font-mono text-[10px]">
              awp run
            </code>
            . Both reduce the same scalar loss but move different
            parameters: the outer loop trains the policy (θ — prompt
            artifacts); refinement polishes a single run's deliverable
            (y). Disjoint state · compose cleanly.
          </p>

          {/* Outer Loop — θ-axis */}
          <div className="rounded-lg border border-awp-border/60 bg-awp-bg/40 p-3 space-y-3">
            <div className="flex items-center gap-2">
              <Dna className="h-3.5 w-3.5 text-awp-blue" />
              <h4 className="text-xs font-semibold text-awp-text">
                Outer Loop — θ-axis SGD{' '}
                <span className="text-[10px] font-normal text-awp-muted">
                  (A5, experimental)
                </span>
              </h4>
            </div>
            <p className="text-[10px] text-awp-muted leading-relaxed">
              LLM-as-optimizer (TextGrad) updates six versioned prompt
              artifacts across a task suite; rollback halves the
              learning rate on mean-loss regression. Launch via{' '}
              <code className="rounded bg-awp-border/40 px-1 font-mono">
                awp optimize
              </code>{' '}
              or the Optimizer tab.{' '}
              <a
                href="https://github.com/veegee82/agent-workflow-protocol/blob/main/docs/outer-loop.md"
                target="_blank"
                rel="noreferrer"
                className="text-awp-blue hover:underline"
              >
                Learn more →
              </a>
            </p>
            <ToggleSwitch
              label="Surface in UI"
              description="Show the Optimizer tab and expose the suite/epoch charts"
              checked={config.outer_loop_enabled}
              onChange={(v) => updateConfig({ outer_loop_enabled: v })}
            />
            {config.outer_loop_enabled && (
              <>
                <SliderInput
                  label="Default Epochs"
                  description="Suite runs per optimize invocation"
                  value={config.outer_loop_default_epochs}
                  min={1}
                  max={20}
                  step={1}
                  onChange={(v) =>
                    updateConfig({ outer_loop_default_epochs: v })
                  }
                />
                <SliderInput
                  label="Default Learning Rate"
                  description="Halved on each mean-loss regression"
                  value={config.outer_loop_default_learning_rate * 100}
                  min={5}
                  max={100}
                  step={5}
                  onChange={(v) =>
                    updateConfig({
                      outer_loop_default_learning_rate: v / 100,
                    })
                  }
                  format={(v) => `${(v / 100).toFixed(2)}`}
                />
                <ToggleSwitch
                  label="Use TextGrad (LLM-as-optimizer)"
                  description="Without this, epochs still run but no artifact is touched"
                  checked={config.outer_loop_with_textgrad}
                  onChange={(v) =>
                    updateConfig({ outer_loop_with_textgrad: v })
                  }
                />
              </>
            )}
          </div>

          {/* Refinement — y-axis */}
          <div className="rounded-lg border border-awp-border/60 bg-awp-bg/40 p-3 space-y-3">
            <div className="flex items-center gap-2">
              <Sparkles className="h-3.5 w-3.5 text-awp-blue" />
              <h4 className="text-xs font-semibold text-awp-text">
                Refinement — y-axis SGD
              </h4>
            </div>
            <p className="text-[10px] text-awp-muted leading-relaxed">
              Task-local inference-compute scaling: iteratively refines
              a completed run's deliverable using critique + gate +
              eval signals as a deterministic gradient (R36 aborts on
              empty). Triggered from any complete/partial run's{' '}
              <strong>Refine</strong> button in the Run History.{' '}
              <a
                href="https://github.com/veegee82/agent-workflow-protocol/blob/main/docs/refinement.md"
                target="_blank"
                rel="noreferrer"
                className="text-awp-blue hover:underline"
              >
                Learn more →
              </a>
            </p>
            <ToggleSwitch
              label="Enable Refine button"
              description="Show 'Refine' + 'Refinements' controls on run-history entries"
              checked={config.refinement_enabled}
              onChange={(v) => updateConfig({ refinement_enabled: v })}
            />
            {config.refinement_enabled && (
              <SliderInput
                label="Default Iterations"
                description="Pre-filled in the Refine modal (1–10; budget halves per iter)"
                value={config.refinement_default_iterations}
                min={1}
                max={10}
                step={1}
                onChange={(v) =>
                  updateConfig({ refinement_default_iterations: v })
                }
              />
            )}
          </div>
        </div>
      </Panel>

      {/* Skills */}
      <SkillsSection />

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
          <ToggleSwitch
            label="LLM Trace"
            description="Save full LLM call traces (prompts, responses, tokens)"
            checked={config.trace_enabled}
            onChange={(v) => updateConfig({ trace_enabled: v })}
          />
        </div>
      </Panel>
    </div>
  );
}
