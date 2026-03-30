import { useCallback, useEffect, useRef, useState } from 'react';
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
} from 'lucide-react';
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
// Collapsible JSON tree
// ---------------------------------------------------------------------------

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
    return (
      <div className="flex items-start gap-1" style={{ paddingLeft: depth * 16 }}>
        {name && <span className="text-awp-purple shrink-0">{name}:</span>}
        <span className="text-awp-green break-all">&quot;{value}&quot;</span>
      </div>
    );
  }

  if (Array.isArray(value)) {
    return (
      <div style={{ paddingLeft: depth * 16 }}>
        <button
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-1 text-awp-text hover:text-awp-blue transition-colors"
        >
          {open ? (
            <ChevronDown className="h-3 w-3 shrink-0" />
          ) : (
            <ChevronRight className="h-3 w-3 shrink-0" />
          )}
          {name && <span className="text-awp-purple">{name}:</span>}
          <span className="text-awp-muted">
            [{value.length} item{value.length !== 1 ? 's' : ''}]
          </span>
        </button>
        {open && (
          <div className="mt-0.5">
            {value.map((item, i) => (
              <JsonNode key={i} name={String(i)} value={item} depth={depth + 1} />
            ))}
          </div>
        )}
      </div>
    );
  }

  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>);
    return (
      <div style={{ paddingLeft: depth * 16 }}>
        <button
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-1 text-awp-text hover:text-awp-blue transition-colors"
        >
          {open ? (
            <ChevronDown className="h-3 w-3 shrink-0" />
          ) : (
            <ChevronRight className="h-3 w-3 shrink-0" />
          )}
          {name && <span className="text-awp-purple">{name}:</span>}
          <span className="text-awp-muted">
            {'{'}
            {entries.length} key{entries.length !== 1 ? 's' : ''}
            {'}'}
          </span>
        </button>
        {open && (
          <div className="mt-0.5">
            {entries.map(([k, v]) => (
              <JsonNode key={k} name={k} value={v} depth={depth + 1} />
            ))}
          </div>
        )}
      </div>
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

function MarkdownBlock({ content }: { content: string }) {
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
}

function CodeBlock({ content, language }: { content: string; language?: string }) {
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
}

function ImageBlock({ content, title }: { content: string; title?: string }) {
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
}

function TableBlock({ content }: { content: string }) {
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
      <table className="w-full text-xs text-awp-text">
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
}

function JsonBlock({ content }: { content: string }) {
  let parsed: unknown;
  try {
    parsed = JSON.parse(content);
  } catch {
    return <CodeBlock content={content} language="json" />;
  }

  return (
    <div className="rounded-lg border border-awp-border bg-awp-bg p-3 font-mono text-xs leading-relaxed overflow-x-auto">
      <JsonNode value={parsed} />
    </div>
  );
}

function ErrorBlock({ content, title }: { content: string; title?: string }) {
  return (
    <div className="rounded-lg border border-awp-red/40 bg-awp-red/5 px-4 py-3">
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-awp-red" />
        <div className="flex-1 min-w-0">
          {title && (
            <div className="mb-1 text-xs font-semibold text-awp-red">{title}</div>
          )}
          <pre className="whitespace-pre-wrap break-words text-sm text-awp-red/90 font-mono">
            {content}
          </pre>
        </div>
      </div>
    </div>
  );
}

function FileBlock({ content, title }: { content: string; title?: string }) {
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
}

// ---------------------------------------------------------------------------
// Single output block card
// ---------------------------------------------------------------------------

function OutputBlockCard({ block, index }: { block: OutputBlock; index: number }) {
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
        {block.type === 'error' && (
          <ErrorBlock content={block.content} title={block.title} />
        )}
        {block.type === 'file' && (
          <FileBlock content={block.content} title={block.title} />
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main OutputPanel
// ---------------------------------------------------------------------------

export function OutputPanel() {
  const { outputBlocks } = useWorkflowStore();
  const scrollRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  // Auto-scroll to bottom when new blocks arrive
  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [outputBlocks.length, autoScroll]);

  // Detect if user scrolled up
  const handleScroll = useCallback(() => {
    if (!scrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 80;
    setAutoScroll(isAtBottom);
  }, []);

  if (outputBlocks.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-awp-muted">
        <Inbox className="h-12 w-12 opacity-40" />
        <p className="text-sm">Start a workflow to see results</p>
      </div>
    );
  }

  return (
    <div
      ref={scrollRef}
      onScroll={handleScroll}
      className="flex h-full flex-col gap-4 overflow-y-auto px-6 py-4 scroll-smooth"
    >
      {outputBlocks.map((block, i) => (
        <OutputBlockCard key={i} block={block} index={i} />
      ))}

      {/* Scroll-to-bottom pill */}
      {!autoScroll && (
        <button
          onClick={() => {
            if (scrollRef.current) {
              scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
              setAutoScroll(true);
            }
          }}
          className="sticky bottom-4 mx-auto rounded-full border border-awp-border bg-awp-panel px-3 py-1.5 text-xs text-awp-muted shadow-lg hover:text-awp-text transition-colors"
        >
          Scroll to bottom
        </button>
      )}
    </div>
  );
}
