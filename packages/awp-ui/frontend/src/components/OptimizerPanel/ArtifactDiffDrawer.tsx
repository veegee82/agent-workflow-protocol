import { useEffect, useMemo } from 'react';
import { X, Loader2, AlertCircle } from 'lucide-react';
import { useWorkflowStore } from '@/stores/workflowStore';
import { COLORS } from '@/components/MetricsPanel/charts/_shared';

/**
 * Side drawer that shows the unified diff between two versions of an
 * artifact.
 *
 * The diff is computed in-browser with a small LCS-based line-diff
 * helper so we don't pull in a dependency. For the short strings the
 * optimizer produces (≤ 20 000 chars), an O(n*m) LCS is fine.
 */
interface Props {
  artifact: string;
  fromVersion: number;
  toVersion: number;
  eventType: 'update' | 'rollback';
  onClose: () => void;
}

export function ArtifactDiffDrawer({
  artifact,
  fromVersion,
  toVersion,
  eventType,
  onClose,
}: Props) {
  const versionsByName = useWorkflowStore(
    (s) => s.optimizerState.artifactVersions,
  );
  const loadArtifactVersions = useWorkflowStore((s) => s.loadArtifactVersions);
  const error = useWorkflowStore((s) => s.optimizerState.error);

  const versions = versionsByName?.[artifact];
  useEffect(() => {
    if (!versions) {
      loadArtifactVersions(artifact).catch(() => {});
    }
  }, [artifact, versions, loadArtifactVersions]);

  // Escape-to-close
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const { from, to, diffLines } = useMemo(() => {
    if (!versions) return { from: null, to: null, diffLines: [] };
    const fromV = versions.find((v) => v.version === fromVersion) ?? null;
    const toV = versions.find((v) => v.version === toVersion) ?? null;
    const lines = diffLinesLcs(fromV?.content ?? '', toV?.content ?? '');
    return { from: fromV, to: toV, diffLines: lines };
  }, [versions, fromVersion, toVersion]);

  return (
    <div className="fixed inset-0 z-50 flex">
      {/* backdrop */}
      <button
        type="button"
        aria-label="Close diff"
        onClick={onClose}
        className="flex-1 bg-black/50"
      />
      {/* drawer */}
      <div className="flex h-full w-[640px] max-w-[90vw] flex-col border-l border-awp-border bg-awp-bg shadow-xl">
        <div className="flex items-center justify-between border-b border-awp-border bg-awp-panel px-4 py-3">
          <div>
            <div className="text-sm font-semibold text-awp-text">
              {artifact}
            </div>
            <div className="text-[11px] text-awp-muted">
              {eventType === 'rollback' ? (
                <span className="text-awp-red">rollback</span>
              ) : (
                <span className="text-awp-green">update</span>
              )}{' '}
              <span className="font-mono">
                v{fromVersion} → v{toVersion}
              </span>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-awp-muted hover:bg-awp-border/40 hover:text-awp-text"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 overflow-auto">
          {!versions && (
            <div className="flex h-full w-full items-center justify-center text-sm text-awp-muted">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Loading versions...
            </div>
          )}
          {error && (
            <div className="m-4 flex items-start gap-2 rounded-md border border-awp-red/40 bg-awp-red/10 p-3 text-xs text-awp-red">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <div>{error}</div>
            </div>
          )}
          {versions && (!from || !to) && (
            <div className="p-4 text-xs text-awp-muted">
              One of the versions (v{fromVersion} or v{toVersion}) could not
              be found in the artifact registry. The diff may reference a
              version that was manually rolled back.
            </div>
          )}
          {versions && from && to && (
            <DiffView diffLines={diffLines} />
          )}
        </div>
      </div>
    </div>
  );
}

function DiffView({ diffLines }: { diffLines: DiffLine[] }) {
  return (
    <pre
      className="m-0 overflow-x-auto p-3 text-[11px] leading-[1.5]"
      style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' }}
    >
      {diffLines.map((ln, i) => (
        <div
          key={i}
          style={{
            backgroundColor:
              ln.kind === 'add'
                ? 'rgba(0, 230, 118, 0.08)'
                : ln.kind === 'del'
                  ? 'rgba(255, 23, 68, 0.08)'
                  : 'transparent',
            color:
              ln.kind === 'add'
                ? COLORS.green
                : ln.kind === 'del'
                  ? COLORS.red
                  : COLORS.text,
            paddingLeft: 6,
            paddingRight: 6,
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}
        >
          <span
            style={{ color: COLORS.muted, marginRight: 6, userSelect: 'none' }}
          >
            {ln.kind === 'add' ? '+' : ln.kind === 'del' ? '-' : ' '}
          </span>
          {ln.text || '\u00A0'}
        </div>
      ))}
      {diffLines.length === 0 && (
        <div style={{ color: COLORS.muted, fontStyle: 'italic' }}>
          (identical)
        </div>
      )}
    </pre>
  );
}

// ---------------------------------------------------------------------------
// Minimal line-based LCS diff
// ---------------------------------------------------------------------------
//
// We intentionally do NOT pull in a diff library. The artifacts produced by
// the outer loop are short (≤ 20 000 chars / few hundred lines), so a
// classic O(n*m) LCS is fast enough and the whole helper is < 50 LOC.

interface DiffLine {
  kind: 'add' | 'del' | 'ctx';
  text: string;
}

function diffLinesLcs(a: string, b: string): DiffLine[] {
  if (a === b) return [];
  const aLines = a.split('\n');
  const bLines = b.split('\n');
  const n = aLines.length;
  const m = bLines.length;

  // Build LCS table. We store only lengths; the path is reconstructed in
  // a second pass. Flat array indexing is marginally faster than 2D.
  const dp = new Uint32Array((n + 1) * (m + 1));
  const idx = (i: number, j: number): number => i * (m + 1) + j;
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      if (aLines[i] === bLines[j]) {
        dp[idx(i, j)] = dp[idx(i + 1, j + 1)] + 1;
      } else {
        dp[idx(i, j)] =
          dp[idx(i + 1, j)] >= dp[idx(i, j + 1)]
            ? dp[idx(i + 1, j)]
            : dp[idx(i, j + 1)];
      }
    }
  }

  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (aLines[i] === bLines[j]) {
      out.push({ kind: 'ctx', text: aLines[i] });
      i++;
      j++;
    } else if (dp[idx(i + 1, j)] >= dp[idx(i, j + 1)]) {
      out.push({ kind: 'del', text: aLines[i] });
      i++;
    } else {
      out.push({ kind: 'add', text: bLines[j] });
      j++;
    }
  }
  while (i < n) {
    out.push({ kind: 'del', text: aLines[i] });
    i++;
  }
  while (j < m) {
    out.push({ kind: 'add', text: bLines[j] });
    j++;
  }
  return out;
}

export default ArtifactDiffDrawer;
