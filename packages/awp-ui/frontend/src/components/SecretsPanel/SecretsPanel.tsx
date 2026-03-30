import React, { useState, useCallback } from 'react';
import { clsx } from 'clsx';
import {
  Key,
  Plus,
  Trash2,
  Shield,
  AlertTriangle,
  Clock,
} from 'lucide-react';
import type { SecretEntry } from '@/types';
import { Modal } from '@/components/Layout';

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface SecretsPanelProps {
  secrets: SecretEntry[];
  onAdd: (key: string, value: string) => void;
  onDelete: (key: string) => void;
}

// ---------------------------------------------------------------------------
// Preset buttons
// ---------------------------------------------------------------------------

const COMMON_PRESETS = [
  'OPENROUTER_API_KEY',
  'OPENAI_API_KEY',
  'ANTHROPIC_API_KEY',
];

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export function SecretsPanel({ secrets, onAdd, onDelete }: SecretsPanelProps) {
  const [newKey, setNewKey] = useState('');
  const [newValue, setNewValue] = useState('');
  const [deleteConfirmKey, setDeleteConfirmKey] = useState<string | null>(null);

  const handleAdd = useCallback(() => {
    const trimmedKey = newKey.trim();
    const trimmedValue = newValue.trim();
    if (!trimmedKey || !trimmedValue) return;
    onAdd(trimmedKey, trimmedValue);
    setNewKey('');
    setNewValue('');
  }, [newKey, newValue, onAdd]);

  const handlePresetClick = useCallback(
    (presetKey: string) => {
      setNewKey(presetKey);
    },
    [],
  );

  const handleConfirmDelete = useCallback(() => {
    if (deleteConfirmKey) {
      onDelete(deleteConfirmKey);
      setDeleteConfirmKey(null);
    }
  }, [deleteConfirmKey, onDelete]);

  const existingKeys = new Set(secrets.map((s) => s.key));

  return (
    <div className="space-y-4">
      {/* Info */}
      <div className="flex items-start gap-2 rounded-lg border border-awp-blue/20 bg-awp-blue/5 p-3">
        <Shield className="h-4 w-4 text-awp-blue shrink-0 mt-0.5" />
        <p className="text-[11px] text-awp-muted leading-relaxed">
          Secrets are stored locally and injected into workflow agents. Values
          are never displayed after saving.
        </p>
      </div>

      {/* Add form */}
      <div className="space-y-2">
        <label className="text-xs font-medium text-awp-text">
          Add Secret
        </label>

        {/* Presets */}
        <div className="flex flex-wrap gap-1.5">
          {COMMON_PRESETS.filter((p) => !existingKeys.has(p)).map(
            (preset) => (
              <button
                key={preset}
                type="button"
                onClick={() => handlePresetClick(preset)}
                className={clsx(
                  'rounded-md border px-2 py-1 text-[10px] font-mono transition-colors',
                  newKey === preset
                    ? 'border-awp-blue bg-awp-blue/15 text-awp-blue'
                    : 'border-awp-border text-awp-muted hover:border-awp-muted hover:text-awp-text',
                )}
              >
                {preset}
              </button>
            ),
          )}
        </div>

        {/* Key input */}
        <input
          type="text"
          value={newKey}
          onChange={(e) => setNewKey(e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, ''))}
          placeholder="SECRET_KEY_NAME"
          className="w-full rounded-md border border-awp-border bg-awp-bg px-3 py-1.5 text-xs text-awp-text font-mono placeholder:text-awp-muted/50 focus:outline-none focus:ring-1 focus:ring-awp-blue focus:border-awp-blue transition-colors"
        />

        {/* Value input */}
        <input
          type="password"
          value={newValue}
          onChange={(e) => setNewValue(e.target.value)}
          placeholder="Secret value..."
          className="w-full rounded-md border border-awp-border bg-awp-bg px-3 py-1.5 text-xs text-awp-text placeholder:text-awp-muted/50 focus:outline-none focus:ring-1 focus:ring-awp-blue focus:border-awp-blue transition-colors"
        />

        {/* Add button */}
        <button
          type="button"
          onClick={handleAdd}
          disabled={!newKey.trim() || !newValue.trim()}
          className={clsx(
            'flex w-full items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
            newKey.trim() && newValue.trim()
              ? 'bg-awp-blue/15 text-awp-blue hover:bg-awp-blue/25'
              : 'bg-awp-border/30 text-awp-muted cursor-not-allowed',
          )}
        >
          <Plus className="h-3 w-3" />
          Add Secret
        </button>
      </div>

      {/* Stored secrets list */}
      <div className="space-y-1.5">
        <label className="text-xs font-medium text-awp-muted uppercase tracking-wide">
          Stored Secrets ({secrets.length})
        </label>
        {secrets.length === 0 ? (
          <div className="rounded-lg border border-dashed border-awp-border py-4 text-center">
            <Key className="h-6 w-6 text-awp-border mx-auto mb-1" />
            <p className="text-[11px] text-awp-muted">No secrets stored</p>
          </div>
        ) : (
          <div className="space-y-1">
            {secrets.map((secret) => (
              <div
                key={secret.key}
                className="flex items-center justify-between rounded-lg border border-awp-border bg-awp-bg px-3 py-2 group"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <Key className="h-3 w-3 text-awp-yellow shrink-0" />
                  <span className="text-xs font-mono text-awp-text truncate">
                    {secret.key}
                  </span>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <span className="text-[10px] text-awp-muted flex items-center gap-1">
                    <Clock className="h-2.5 w-2.5" />
                    {new Date(secret.created_at).toLocaleDateString()}
                  </span>
                  <button
                    type="button"
                    onClick={() => setDeleteConfirmKey(secret.key)}
                    className="opacity-0 group-hover:opacity-100 text-awp-muted hover:text-awp-red transition-all"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Delete confirmation modal */}
      <Modal
        open={deleteConfirmKey !== null}
        onClose={() => setDeleteConfirmKey(null)}
        title="Delete Secret"
      >
        <div className="space-y-4">
          <div className="flex items-start gap-3">
            <div className="rounded-full bg-awp-red/10 p-2">
              <AlertTriangle className="h-5 w-5 text-awp-red" />
            </div>
            <div>
              <p className="text-sm text-awp-text">
                Are you sure you want to delete the secret{' '}
                <code className="rounded bg-awp-bg px-1.5 py-0.5 text-xs font-mono text-awp-yellow">
                  {deleteConfirmKey}
                </code>
                ?
              </p>
              <p className="text-xs text-awp-muted mt-1">
                This action cannot be undone. Workflows using this secret will
                fail until a new value is provided.
              </p>
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setDeleteConfirmKey(null)}
              className="rounded-md border border-awp-border px-3 py-1.5 text-xs font-medium text-awp-text hover:bg-awp-bg transition-colors"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleConfirmDelete}
              className="rounded-md bg-awp-red/15 px-3 py-1.5 text-xs font-medium text-awp-red hover:bg-awp-red/25 transition-colors"
            >
              Delete
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
