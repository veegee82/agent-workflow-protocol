import React, { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import {
  Copy,
  Check,
  AlertTriangle,
  ChevronRight,
  ChevronDown,
  FileDown,
  Maximize2,
  X,
  Inbox,
  Bot,
  Zap,
  Cpu,
  Users,
  Clock,
  Wrench,
  Target,
} from 'lucide-react';
import { Virtuoso, type VirtuosoHandle } from 'react-virtuoso';
import { useWorkflowStore } from '@/stores/workflowStore';
import type { OutputBlock } from '@/types';
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
// Image modal
// ---------------------------------------------------------------------------

function ImageModal({
  src,
  alt,
  onClose,
}: {
  src: string;
  alt: string;
  onClose: () => void;
}) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm animate-fade-in"
      onClick={onClose}
    >
      <button
        onClick={onClose}
        className="absolute right-4 top-4 rounded-lg bg-awp-panel/80 p-2 text-awp-muted hover:text-awp-text transition-colors"
      >
        <X className="h-5 w-5" />
      </button>
      <img
        src={src}
        alt={alt}
        className="max-h-[90vh] max-w-[90vw] rounded-xl shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Markdown renderer (hoisted for use in JsonNode)
// ---------------------------------------------------------------------------

const MarkdownBlock = memo(function MarkdownBlock({ content }: { content: string }) {
  return (
    <div className="prose prose-invert prose-sm max-w-none prose-headings:text-awp-text prose-p:text-awp-text prose-a:text-awp-blue prose-strong:text-awp-text prose-code:text-awp-cyan prose-code:bg-awp-bg prose-code:rounded prose-code:px-1 prose-code:py-0.5 prose-code:before:content-none prose-code:after:content-none prose-pre:bg-transparent prose-pre:p-0">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw]}
        components={{
          code({ className, children, ...props }) {
            const match = /language-(\w+)/.exec(className || '');
            const codeStr = String(children).replace(/\n$/, '');
            if (match) {
              return (
                <div className="relative group">
                  <div className="absolute right-2 top-2 flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <span className="text-[10px] uppercase tracking-wider text-awp-muted">
                      {match[1]}
                    </span>
                    <CopyButton text={codeStr} />
                  </div>
                  <SyntaxHighlighter
                    style={oneDark}
                    language={match[1]}
                    PreTag="div"
                    customStyle={{
                      background: '#0d1117',
                      borderRadius: '0.5rem',
                      fontSize: '0.8rem',
                      border: '1px solid #30363d',
                    }}
                  >
                    {codeStr}
                  </SyntaxHighlighter>
                </div>
              );
            }
            return (
              <code className={className} {...props}>
                {children}
              </code>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
});

// ---------------------------------------------------------------------------
// Collapsible JSON tree (paginated for large arrays/objects)
// ---------------------------------------------------------------------------

const JSON_PAGE_SIZE = 50;

/** Paginated collapsible container for JSON arrays and objects. */
function JsonCollapsibleNode<T>({
  name,
  label,
  depth,
  open,
  onToggle,
  items,
  renderItem,
}: {
  name?: string;
  label: string;
  depth: number;
  open: boolean;
  onToggle: () => void;
  items: T[];
  renderItem: (item: T, index: number) => React.ReactNode;
}) {
  const [visibleCount, setVisibleCount] = useState(JSON_PAGE_SIZE);
  const visible = items.slice(0, visibleCount);
  const remaining = items.length - visibleCount;

  return (
    <div style={{ paddingLeft: depth * 16 }}>
      <button
        onClick={onToggle}
        className="flex items-center gap-1 text-awp-text hover:text-awp-blue transition-colors"
      >
        {open ? (
          <ChevronDown className="h-3 w-3 shrink-0" />
        ) : (
          <ChevronRight className="h-3 w-3 shrink-0" />
        )}
        {name && <span className="text-awp-purple">{name}:</span>}
        <span className="text-awp-muted">{label}</span>
      </button>
      {open && (
        <div className="mt-0.5">
          {visible.map((item, i) => renderItem(item, i))}
          {remaining > 0 && (
            <button
              onClick={() => setVisibleCount((v) => v + JSON_PAGE_SIZE)}
              className="ml-4 mt-1 text-[11px] text-awp-blue hover:underline"
              style={{ paddingLeft: (depth + 1) * 16 }}
            >
              Show {Math.min(remaining, JSON_PAGE_SIZE)} more ({remaining} remaining)
            </button>
          )}
        </div>
      )}
    </div>
  );
}

const MAX_JSON_DEPTH = 20;

function JsonNode({
  name,
  value,
  depth = 0,
}: {
  name?: string;
  value: unknown;
  depth?: number;
}) {
  const [open, setOpen] = useState(depth < 2);

  // Prevent infinite recursion on deeply nested data
  if (depth > MAX_JSON_DEPTH) {
    return (
      <div className="flex items-center gap-1 text-awp-muted italic" style={{ paddingLeft: depth * 16 }}>
        {name && <span className="text-awp-purple">{name}:</span>}
        <span>... (max depth)</span>
      </div>
    );
  }

  if (value === null || value === undefined) {
    return (
      <div className="flex items-center gap-1" style={{ paddingLeft: depth * 16 }}>
        {name && <span className="text-awp-purple">{name}:</span>}
        <span className="text-awp-muted italic">null</span>
      </div>
    );
  }

  if (typeof value === 'boolean') {
    return (
      <div className="flex items-center gap-1" style={{ paddingLeft: depth * 16 }}>
        {name && <span className="text-awp-purple">{name}:</span>}
        <span className="text-awp-orange">{String(value)}</span>
      </div>
    );
  }

  if (typeof value === 'number') {
    return (
      <div className="flex items-center gap-1" style={{ paddingLeft: depth * 16 }}>
        {name && <span className="text-awp-purple">{name}:</span>}
        <span className="text-awp-cyan">{value}</span>
      </div>
    );
  }

  if (typeof value === 'string') {
    // Detect code-like strings: key is "code" or "source" with newlines
    const isCode =
      (name === 'code' || name === 'source') && value.includes('\n');
    if (isCode) {
      return (
        <div style={{ paddingLeft: depth * 16 }}>
          {name && <span className="text-awp-purple">{name}:</span>}
          <div className="mt-1 relative group">
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
                fontSize: '0.8rem',
                border: '1px solid #30363d',
              }}
            >
              {value}
            </SyntaxHighlighter>
          </div>
        </div>
      );
    }

    // Detect markdown-rich strings (headings, lists, bold, links, etc.)
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
        <div style={{ paddingLeft: depth * 16 }}>
          {name && <span className="text-awp-purple mb-1 block">{name}:</span>}
          <div className="ml-2 mt-1 rounded-lg border border-awp-border/40 bg-awp-bg/50 p-3">
            <MarkdownBlock content={value} />
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
        return (
          <div style={{ paddingLeft: depth * 16 }}>
            {name && <span className="text-awp-purple">{name}:</span>}
            <JsonNode value={inner} depth={depth + 1} />
          </div>
        );
      } catch {
        // not valid JSON, fall through
      }
    }

    // Short strings: inline display
    if (value.length <= 200 && !value.includes('\n')) {
      return (
        <div className="flex items-start gap-1" style={{ paddingLeft: depth * 16 }}>
          {name && <span className="text-awp-purple shrink-0">{name}:</span>}
          <span className="text-awp-green break-all">&quot;{value}&quot;</span>
        </div>
      );
    }

    // Long multi-line plain strings: show in a scrollable block
    return (
      <div style={{ paddingLeft: depth * 16 }}>
        {name && <span className="text-awp-purple block mb-1">{name}:</span>}
        <div className="ml-2 rounded-lg border border-awp-border/40 bg-awp-bg/50 p-3 text-awp-green text-xs max-h-64 overflow-y-auto whitespace-pre-wrap break-words">
          {value}
        </div>
      </div>
    );
  }

  if (Array.isArray(value)) {
    return (
      <JsonCollapsibleNode
        name={name}
        label={`[${value.length} item${value.length !== 1 ? 's' : ''}]`}
        depth={depth}
        open={open}
        onToggle={() => setOpen((v) => !v)}
        items={value}
        renderItem={(item, i) => (
          <JsonNode key={i} name={String(i)} value={item} depth={depth + 1} />
        )}
      />
    );
  }

  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>);
    return (
      <JsonCollapsibleNode
        name={name}
        label={`{${entries.length} key${entries.length !== 1 ? 's' : ''}}`}
        depth={depth}
        open={open}
        onToggle={() => setOpen((v) => !v)}
        items={entries}
        renderItem={([k, v]) => (
          <JsonNode key={k} name={k} value={v} depth={depth + 1} />
        )}
      />
    );
  }

  return (
    <div style={{ paddingLeft: depth * 16 }}>
      {name && <span className="text-awp-purple">{name}: </span>}
      <span className="text-awp-text">{String(value)}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Individual block renderers
// ---------------------------------------------------------------------------

const CodeBlock = memo(function CodeBlock({ content, language }: { content: string; language?: string }) {
  return (
    <div className="relative group">
      <div className="absolute right-2 top-2 flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity z-10">
        {language && (
          <span className="text-[10px] uppercase tracking-wider text-awp-muted">
            {language}
          </span>
        )}
        <CopyButton text={content} />
      </div>
      <SyntaxHighlighter
        style={oneDark}
        language={language ?? 'text'}
        PreTag="div"
        customStyle={{
          background: '#0d1117',
          borderRadius: '0.5rem',
          fontSize: '0.8rem',
          border: '1px solid #30363d',
        }}
      >
        {content}
      </SyntaxHighlighter>
    </div>
  );
});

const ImageBlock = memo(function ImageBlock({ content, title }: { content: string; title?: string }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <>
      <div className="relative group inline-block">
        <img
          src={content}
          alt={title ?? 'Output image'}
          className="max-w-full rounded-lg border border-awp-border cursor-pointer hover:border-awp-blue/50 transition-colors"
          onClick={() => setExpanded(true)}
        />
        <button
          onClick={() => setExpanded(true)}
          className="absolute right-2 top-2 rounded-md bg-awp-panel/80 p-1.5 text-awp-muted opacity-0 group-hover:opacity-100 hover:text-awp-text transition-all"
        >
          <Maximize2 className="h-3.5 w-3.5" />
        </button>
      </div>
      {expanded && (
        <ImageModal
          src={content}
          alt={title ?? 'Output image'}
          onClose={() => setExpanded(false)}
        />
      )}
    </>
  );
});

const TableBlock = memo(function TableBlock({ content }: { content: string }) {
  let rows: string[][] = [];
  try {
    const parsed = JSON.parse(content);
    if (Array.isArray(parsed) && parsed.length > 0) {
      if (Array.isArray(parsed[0])) {
        rows = parsed;
      } else if (typeof parsed[0] === 'object') {
        const headers = Object.keys(parsed[0]);
        rows = [headers, ...parsed.map((r: Record<string, unknown>) => headers.map((h) => String(r[h] ?? '')))];
      }
    }
  } catch {
    // Treat as TSV/CSV fallback
    rows = content.split('\n').filter(Boolean).map((line) => line.split('\t'));
  }

  if (rows.length === 0) return <pre className="text-xs text-awp-muted">{content}</pre>;

  const [header, ...body] = rows;

  return (
    <div className="overflow-x-auto rounded-lg border border-awp-border">
      <table className="text-xs text-awp-text" style={{ minWidth: 'max-content' }}>
        <thead className="sticky top-0 bg-awp-panel">
          <tr>
            {header.map((cell, i) => (
              <th
                key={i}
                className="border-b border-awp-border px-3 py-2 text-left font-semibold text-awp-muted uppercase tracking-wide"
              >
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((row, ri) => (
            <tr
              key={ri}
              className={clsx(
                ri % 2 === 0 ? 'bg-awp-bg/30' : 'bg-awp-panel/30',
                'hover:bg-awp-blue/5 transition-colors',
              )}
            >
              {row.map((cell, ci) => (
                <td key={ci} className="border-b border-awp-border/50 px-3 py-1.5">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
});

const JsonBlock = memo(function JsonBlock({ content }: { content: string }) {
  const parsed = useMemo(() => {
    try { return JSON.parse(content); } catch { return null; }
  }, [content]);

  if (parsed === null) return <CodeBlock content={content} language="json" />;

  return (
    <div className="rounded-lg border border-awp-border bg-awp-bg p-3 font-mono text-xs leading-relaxed overflow-x-auto">
      <JsonNode value={parsed} />
    </div>
  );
});

const ErrorBlock = memo(function ErrorBlock({ content, title }: { content: string; title?: string }) {
  return (
    <div className="rounded-lg border border-awp-red/40 bg-awp-red/5 px-4 py-3">
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-awp-red" />
        <div className="flex-1 min-w-0">
          {title && (
            <div className="mb-1 text-xs font-semibold text-awp-red">{title}</div>
          )}
          <div className="rounded overflow-hidden">
            <SyntaxHighlighter
              language="text"
              style={oneDark}
              customStyle={{ margin: 0, padding: '0.5rem', background: 'transparent', fontSize: '0.8125rem', lineHeight: '1.5', color: 'rgba(248,81,73,0.9)' }}
              wrapLines
              wrapLongLines
            >
              {content}
            </SyntaxHighlighter>
          </div>
        </div>
      </div>
    </div>
  );
});

const FileBlock = memo(function FileBlock({ content, title }: { content: string; title?: string }) {
  return (
    <a
      href={content}
      download={title ?? true}
      className="flex items-center gap-2 rounded-lg border border-awp-border bg-awp-bg px-4 py-3 text-sm text-awp-blue hover:border-awp-blue/50 hover:bg-awp-blue/5 transition-colors"
    >
      <FileDown className="h-4 w-4 shrink-0" />
      <span className="truncate">{title ?? content}</span>
    </a>
  );
});

// ---------------------------------------------------------------------------
// Single output block card
// ---------------------------------------------------------------------------

const OutputBlockCard = memo(function OutputBlockCard({ block, index }: { block: OutputBlock; index: number }) {
  const agentName = block.metadata?.agent as string | undefined;

  return (
    <div
      className="animate-fade-in"
      style={{ animationDelay: `${Math.min(index * 30, 300)}ms` }}
    >
      {agentName && (
        <div className="mb-1.5 flex items-center gap-1.5">
          <Bot className="h-3 w-3 text-awp-purple" />
          <span className="text-[11px] font-medium text-awp-purple">{agentName}</span>
        </div>
      )}
      {block.title && block.type !== 'error' && (
        <div className="mb-1.5 text-xs font-semibold text-awp-muted">{block.title}</div>
      )}
      <div className="rounded-xl border border-awp-border/60 bg-awp-panel/40 p-4">
        {block.type === 'markdown' && <MarkdownBlock content={block.content} />}
        {block.type === 'code' && (
          <CodeBlock content={block.content} language={block.language} />
        )}
        {block.type === 'image' && (
          <ImageBlock content={block.content} title={block.title} />
        )}
        {block.type === 'chart' && (
          block.content.trim().startsWith('<svg') ? (
            <div
              className="overflow-x-auto [&>svg]:max-w-full"
              dangerouslySetInnerHTML={{ __html: block.content }}
            />
          ) : (
            <ImageBlock content={block.content} title={block.title} />
          )
        )}
        {block.type === 'table' && <TableBlock content={block.content} />}
        {block.type === 'json' && <JsonBlock content={block.content} />}
        {block.type === 'evaluation' && <EvalBlock content={block.content} />}
        {block.type === 'error' && (
          <ErrorBlock content={block.content} title={block.title} />
        )}
        {block.type === 'file' && (
          <FileBlock content={block.content} title={block.title} />
        )}
      </div>
    </div>
  );
});

// ---------------------------------------------------------------------------
// Evaluation Score Block
// ---------------------------------------------------------------------------

interface EvalMetric {
  name: string;
  kind: string;
  score: number;
  weight: number;
}

interface EvalData {
  final_score: number;
  action: string;
  metrics: EvalMetric[];
  retries_used?: number;
}

const EvalBlock = memo(function EvalBlock({ content }: { content: string }) {
  const data: EvalData | null = useMemo(() => {
    try { return JSON.parse(content); } catch { return null; }
  }, [content]);

  if (!data || typeof data.final_score !== 'number') {
    return <JsonBlock content={content} />;
  }

  const score = data.final_score;
  const pct = Math.round(score * 100);
  const actionLabel = data.action?.replace(/_/g, ' ') ?? '';
  const isAccept = data.action === 'accept' || data.action === 'accept_with_warning';
  const isFail = data.action === 'fail_workflow';

  const scoreColor = score >= 0.75
    ? 'text-emerald-400'
    : score >= 0.5
      ? 'text-yellow-400'
      : 'text-red-400';

  const barColor = score >= 0.75
    ? 'bg-emerald-500'
    : score >= 0.5
      ? 'bg-yellow-500'
      : 'bg-red-500';

  const actionBadge = isAccept
    ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
    : isFail
      ? 'bg-red-500/15 text-red-400 border-red-500/30'
      : 'bg-yellow-500/15 text-yellow-400 border-yellow-500/30';

  return (
    <div className="space-y-3">
      {/* Header: Score + Action */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Target className={clsx('h-5 w-5', scoreColor)} />
          <span className={clsx('text-2xl font-bold font-mono tabular-nums', scoreColor)}>
            {pct}%
          </span>
          <div className="h-2 w-32 rounded-full bg-awp-border overflow-hidden">
            <div
              className={clsx('h-full rounded-full transition-all duration-700', barColor)}
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
        <span className={clsx('text-[11px] font-medium px-2 py-0.5 rounded border', actionBadge)}>
          {actionLabel}
        </span>
      </div>

      {/* Metric breakdown */}
      {data.metrics && data.metrics.length > 0 && (
        <div className="space-y-1.5">
          {data.metrics.map((m) => {
            const mPct = Math.round(m.score * 100);
            const mColor = m.score >= 0.65
              ? 'text-emerald-400'
              : m.score >= 0.4
                ? 'text-yellow-400'
                : 'text-red-400';
            const mBar = m.score >= 0.65
              ? 'bg-emerald-500'
              : m.score >= 0.4
                ? 'bg-yellow-500'
                : 'bg-red-500';

            return (
              <div key={m.name} className="flex items-center gap-2 text-xs">
                <span className="w-36 truncate text-awp-muted" title={m.name}>
                  {m.name}
                </span>
                <div className="flex-1 h-1.5 rounded-full bg-awp-border overflow-hidden">
                  <div
                    className={clsx('h-full rounded-full transition-all duration-500', mBar)}
                    style={{ width: `${mPct}%` }}
                  />
                </div>
                <span className={clsx('w-10 text-right font-mono tabular-nums', mColor)}>
                  {mPct}%
                </span>
                <span className="w-14 text-right text-awp-muted font-mono">
                  w={m.weight}
                </span>
              </div>
            );
          })}
        </div>
      )}

      {/* Retries */}
      {(data.retries_used ?? 0) > 0 && (
        <div className="text-[11px] text-awp-muted">
          Retries used: {data.retries_used}
        </div>
      )}
    </div>
  );
});

// ---------------------------------------------------------------------------
// Budget State Bar — live auto-updating budget display
// ---------------------------------------------------------------------------

function BudgetStateBar() {
  const budget = useWorkflowStore((s) => s.budget);
  const runStatus = useWorkflowStore((s) => s.runStatus);
  const isActive = runStatus === 'running' || budget.tokens_used > 0 || budget.loops_used > 0;

  if (!isActive) return null;

  const pct = (used: number, max: number) => max > 0 ? Math.min(100, (used / max) * 100) : 0;
  const fmtTokens = (n: number) => n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : n >= 1000 ? `${(n / 1000).toFixed(0)}k` : String(n);
  const fmtTime = (ms: number) => {
    const s = Math.floor(ms / 1000);
    return s >= 3600 ? `${Math.floor(s / 3600)}h${Math.floor((s % 3600) / 60)}m` : s >= 60 ? `${Math.floor(s / 60)}m${s % 60}s` : `${s}s`;
  };

  const items = [
    { icon: Zap, label: 'Tokens', used: fmtTokens(budget.tokens_used), max: fmtTokens(budget.tokens_max), pct: pct(budget.tokens_used, budget.tokens_max), color: 'text-yellow-400' },
    { icon: Cpu, label: 'Loops', used: String(budget.loops_used), max: String(budget.loops_max), pct: pct(budget.loops_used, budget.loops_max), color: 'text-blue-400' },
    { icon: Users, label: 'Workers', used: String(budget.workers_used), max: String(budget.workers_max), pct: pct(budget.workers_used, budget.workers_max), color: 'text-purple-400' },
    { icon: Clock, label: 'Time', used: fmtTime(budget.wall_time_ms), max: fmtTime(budget.wall_time_max_ms), pct: pct(budget.wall_time_ms, budget.wall_time_max_ms), color: 'text-green-400' },
    { icon: Wrench, label: 'Tools', used: String(budget.tool_calls_used), max: String(budget.tool_calls_max), pct: pct(budget.tool_calls_used, budget.tool_calls_max), color: 'text-orange-400' },
  ];

  return (
    <div className="sticky top-0 z-10 flex items-center gap-3 border-b border-awp-border bg-awp-panel/95 backdrop-blur px-4 py-2 text-[11px]">
      <span className="text-awp-muted font-medium uppercase tracking-wider mr-1">State</span>
      {items.map((item) => (
        <div key={item.label} className="flex items-center gap-1.5">
          <item.icon className={clsx('h-3 w-3', item.color)} />
          <span className="text-awp-muted">{item.label}</span>
          <span className="text-awp-text font-mono">{item.used}</span>
          <span className="text-awp-muted">/</span>
          <span className="text-awp-muted font-mono">{item.max}</span>
          <div className="w-10 h-1 rounded-full bg-awp-border overflow-hidden">
            <div
              className={clsx('h-full rounded-full transition-all duration-500', item.pct > 90 ? 'bg-red-500' : item.pct > 70 ? 'bg-yellow-500' : 'bg-awp-blue')}
              style={{ width: `${item.pct}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

// Main OutputPanel
// ---------------------------------------------------------------------------

export function OutputPanel() {
  const outputBlocks = useWorkflowStore((s) => s.outputBlocks);
  const virtuosoRef = useRef<VirtuosoHandle>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const blockCount = outputBlocks.length;

  // Follow output: scroll to bottom when new blocks arrive
  useEffect(() => {
    if (autoScroll && blockCount > 0) {
      virtuosoRef.current?.scrollToIndex({ index: blockCount - 1, align: 'end', behavior: 'smooth' });
    }
  }, [blockCount, autoScroll]);

  const handleAtBottomChange = useCallback((atBottom: boolean) => {
    setAutoScroll(atBottom);
  }, []);

  const renderItem = useCallback(
    (index: number) => <OutputBlockCard block={outputBlocks[index]} index={index} />,
    [outputBlocks],
  );

  if (blockCount === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-awp-muted">
        <Inbox className="h-12 w-12 opacity-40" />
        <p className="text-sm">Start a workflow to see results</p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <BudgetStateBar />
      <div className="flex-1 relative">
        <Virtuoso
          ref={virtuosoRef}
          totalCount={blockCount}
          itemContent={renderItem}
          atBottomStateChange={handleAtBottomChange}
          atBottomThreshold={80}
          overscan={400}
          className="px-6 py-4"
          itemSize={(el) => el.getBoundingClientRect().height + 16}
          defaultItemHeight={120}
        />
        {/* Scroll-to-bottom pill */}
        {!autoScroll && (
          <button
            onClick={() => {
              virtuosoRef.current?.scrollToIndex({ index: blockCount - 1, align: 'end', behavior: 'smooth' });
              setAutoScroll(true);
            }}
            className="absolute bottom-4 left-1/2 -translate-x-1/2 z-10 rounded-full border border-awp-border bg-awp-panel px-3 py-1.5 text-xs text-awp-muted shadow-lg hover:text-awp-text transition-colors"
          >
            Scroll to bottom
          </button>
        )}
      </div>
    </div>
  );
}
