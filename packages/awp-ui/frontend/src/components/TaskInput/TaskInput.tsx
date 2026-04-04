import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Play,
  Square,
  Upload,
  X,
  FileText,
  FileImage,
  FileCode,
  File as FileIcon,
  Eye,
  EyeOff,
  Loader2,
  CheckCircle2,
  AlertCircle,
  Circle,
  Sparkles,
} from 'lucide-react';
import { useWorkflowStore } from '@/stores/workflowStore';
import clsx from 'clsx';


function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function fileTypeIcon(name: string) {
  const ext = name.split('.').pop()?.toLowerCase() ?? '';
  if (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'].includes(ext))
    return <FileImage className="h-4 w-4 text-awp-purple" />;
  if (['py', 'ts', 'js', 'tsx', 'jsx', 'rs', 'go', 'java'].includes(ext))
    return <FileCode className="h-4 w-4 text-awp-blue" />;
  if (['md', 'txt', 'csv', 'json', 'yaml', 'yml'].includes(ext))
    return <FileText className="h-4 w-4 text-awp-green" />;
  return <FileIcon className="h-4 w-4 text-awp-muted" />;
}

const statusConfig: Record<
  string,
  { color: string; label: string; icon: React.ReactNode }
> = {
  idle: {
    color: 'bg-awp-muted',
    label: 'Idle',
    icon: <Circle className="h-2.5 w-2.5 fill-awp-muted text-awp-muted" />,
  },
  running: {
    color: 'bg-awp-blue',
    label: 'Running',
    icon: <Loader2 className="h-2.5 w-2.5 text-awp-blue animate-spin" />,
  },
  complete: {
    color: 'bg-awp-green',
    label: 'Complete',
    icon: <CheckCircle2 className="h-2.5 w-2.5 text-awp-green" />,
  },
  error: {
    color: 'bg-awp-red',
    label: 'Error',
    icon: <AlertCircle className="h-2.5 w-2.5 text-awp-red" />,
  },
};

export function TaskInput() {
  const config = useWorkflowStore((s) => s.config);
  const updateConfig = useWorkflowStore((s) => s.updateConfig);
  const startRun = useWorkflowStore((s) => s.startRun);
  const stopRun = useWorkflowStore((s) => s.stopRun);
  const runStatus = useWorkflowStore((s) => s.runStatus);
  const attachedFiles = useWorkflowStore((s) => s.attachedFiles);
  const addFiles = useWorkflowStore((s) => s.addFiles);
  const removeFile = useWorkflowStore((s) => s.removeFile);
  const isRefactoring = useWorkflowStore((s) => s.isRefactoring);
  const refactorTask = useWorkflowStore((s) => s.refactorTask);

  const [showApiKey, setShowApiKey] = useState(false);
  const [isDragOver, setIsDragOver] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Local state for lag-free typing; debounce store updates
  const [localTask, setLocalTask] = useState(config.task);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => { setLocalTask(config.task); }, [config.task]);
  useEffect(() => () => clearTimeout(debounceRef.current), []);

  const isRunning = runStatus === 'running';
  const status = statusConfig[runStatus] ?? statusConfig.idle;

  const handleTextChange = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      const val = e.target.value;
      setLocalTask(val);
      const el = e.target;
      el.style.height = 'auto';
      el.style.height = `${Math.min(el.scrollHeight, 300)}px`;
      clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => updateConfig({ task: val }), 300);
    },
    [updateConfig],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragOver(false);
      const files = Array.from(e.dataTransfer.files);
      if (files.length > 0) addFiles(files);
    },
    [addFiles],
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setIsDragOver(false);
  }, []);

  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files ?? []);
      if (files.length > 0) addFiles(files);
      e.target.value = '';
    },
    [addFiles],
  );


  return (
    <div className="flex h-full flex-col gap-4 p-4 overflow-y-auto">
      {/* Status indicator */}
      <div className="flex items-center gap-2 text-xs text-awp-muted">
        {status.icon}
        <span>{status.label}</span>
      </div>

      {/* Task description */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <label className="text-xs font-medium text-awp-muted uppercase tracking-wide">
            Task
          </label>
          <button
            onClick={refactorTask}
            disabled={!localTask.trim() || isRefactoring || isRunning}
            title="Refactor task into structured prompt"
            className={clsx(
              'flex items-center gap-1 rounded-md px-2 py-1 text-xs transition-all',
              localTask.trim() && !isRefactoring && !isRunning
                ? 'text-awp-purple hover:bg-awp-purple/10 hover:text-awp-purple'
                : 'cursor-not-allowed text-awp-muted/40',
            )}
          >
            {isRefactoring ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Sparkles className="h-3.5 w-3.5" />
            )}
            Refactor
          </button>
        </div>
        <textarea
          ref={textareaRef}
          value={localTask}
          onChange={handleTextChange}
          placeholder="Describe the task for your agent workflow..."
          rows={4}
          className="w-full resize-none rounded-lg border border-awp-border bg-awp-bg px-3 py-2.5 text-sm text-awp-text placeholder:text-awp-muted/60 focus:border-awp-blue/60 focus:outline-none focus:ring-1 focus:ring-awp-blue/30 transition-colors"
        />
      </div>

      {/* File drop zone */}
      <div
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onClick={() => fileInputRef.current?.click()}
        className={clsx(
          'flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-4 py-5 transition-all',
          isDragOver
            ? 'border-awp-blue bg-awp-blue/10 scale-[1.01]'
            : 'border-awp-border hover:border-awp-muted hover:bg-awp-bg/50',
        )}
      >
        <Upload
          className={clsx(
            'h-5 w-5 transition-colors',
            isDragOver ? 'text-awp-blue' : 'text-awp-muted',
          )}
        />
        <span className="text-xs text-awp-muted">
          Drop files here or click to browse
        </span>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          onChange={handleFileSelect}
          className="hidden"
        />
      </div>

      {/* Attached files */}
      {attachedFiles.length > 0 && (
        <div className="space-y-1">
          {attachedFiles.map((file, idx) => (
            <div
              key={`${file.name}-${idx}`}
              className="flex items-center gap-2 rounded-md border border-awp-border bg-awp-bg px-2.5 py-1.5 text-xs"
            >
              {fileTypeIcon(file.name)}
              <span className="flex-1 truncate text-awp-text">
                {file.name}
              </span>
              <span className="text-awp-muted">
                {formatFileSize(file.size)}
              </span>
              <button
                onClick={() => removeFile(idx)}
                className="rounded p-0.5 text-awp-muted hover:bg-awp-border hover:text-awp-red transition-colors"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Model */}
      <div className="space-y-1.5">
        <label className="text-xs font-medium text-awp-muted uppercase tracking-wide">
          Model
        </label>
        <input
          type="text"
          value={config.model}
          onChange={(e) => updateConfig({ model: e.target.value })}
          placeholder="openai/gpt-5-nano"
          className="w-full rounded-lg border border-awp-border bg-awp-bg px-3 py-2 text-sm font-mono text-awp-text placeholder:text-awp-muted/60 focus:border-awp-blue/60 focus:outline-none focus:ring-1 focus:ring-awp-blue/30 transition-colors"
        />
      </div>

      {/* Worker model */}
      <div className="space-y-1.5">
        <label className="text-xs font-medium text-awp-muted uppercase tracking-wide">
          Worker Model{' '}
          <span className="text-awp-muted/60 normal-case">(optional)</span>
        </label>
        <input
          type="text"
          value={config.worker_model ?? ''}
          onChange={(e) =>
            updateConfig({ worker_model: e.target.value || undefined })
          }
          placeholder="Same as main model"
          className="w-full rounded-lg border border-awp-border bg-awp-bg px-3 py-2 text-sm font-mono text-awp-text placeholder:text-awp-muted/60 focus:border-awp-blue/60 focus:outline-none focus:ring-1 focus:ring-awp-blue/30 transition-colors"
        />
      </div>

      {/* API key */}
      <div className="space-y-1.5">
        <label className="text-xs font-medium text-awp-muted uppercase tracking-wide">
          API Key
        </label>
        <div className="relative">
          <input
            type={showApiKey ? 'text' : 'password'}
            value={config.api_key ?? ''}
            onChange={(e) =>
              updateConfig({ api_key: e.target.value || undefined })
            }
            placeholder="sk-or-..."
            className="w-full rounded-lg border border-awp-border bg-awp-bg px-3 py-2 pr-10 text-sm text-awp-text placeholder:text-awp-muted/60 focus:border-awp-blue/60 focus:outline-none focus:ring-1 focus:ring-awp-blue/30 transition-colors font-mono"
          />
          <button
            type="button"
            onClick={() => setShowApiKey((v) => !v)}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-awp-muted hover:text-awp-text transition-colors"
          >
            {showApiKey ? (
              <EyeOff className="h-4 w-4" />
            ) : (
              <Eye className="h-4 w-4" />
            )}
          </button>
        </div>
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Action buttons */}
      <div className="space-y-2">
        {isRunning ? (
          <button
            onClick={stopRun}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-awp-red/90 px-4 py-2.5 text-sm font-semibold text-white shadow-lg hover:bg-awp-red transition-colors"
          >
            <Square className="h-4 w-4" />
            Stop Workflow
          </button>
        ) : (
          <button
            onClick={startRun}
            disabled={!localTask.trim()}
            className={clsx(
              'flex w-full items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold text-white shadow-lg transition-all',
              localTask.trim()
                ? 'bg-gradient-to-r from-awp-blue to-awp-purple hover:shadow-awp-blue/25 hover:shadow-xl active:scale-[0.98]'
                : 'cursor-not-allowed bg-awp-border text-awp-muted',
              isRunning && 'animate-pulse-slow',
            )}
          >
            <Play className="h-4 w-4" />
            Run Workflow
          </button>
        )}
      </div>

    </div>
  );
}
