export interface Experiment {
  id: string;
  name: string;
  goal: string;
  base_dir: string;
  created_at: number;
  archived_at: number | null;
}

export interface Task {
  id: string;                    // "<exp_id>:<task_id>"
  experiment_id: string;
  task_number: number;
  slug: string;
  mode: "seed" | "continuation";
  user_prompt: string | null;
  user_feedback: string | null;
  inputs_json: string;
  best_run_id: string | null;
  best_reason: "auto_loss" | "user_override" | null;
  created_at: number;
}

export interface ExperimentDetail extends Experiment {
  tasks: Task[];
}

export interface TaskRun {
  id: string;
  run_role: "seed" | "refine_iter" | "optimize_epoch_run";
  loss: number | null;
  status: string;
  created_at: string;
  completed_at: string | null;
}

export interface TaskDetail extends Task {
  runs: TaskRun[];
}

export interface LossPoint {
  task_number?: number;
  task_id?: string;
  best_loss?: number;
  run_id?: string;
  run_role?: string;
  loss?: number;
  status?: string;
  created_at?: string;
}

async function apiGet<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`GET ${path} → ${r.status}`);
  return r.json() as Promise<T>;
}

async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`POST ${path} → ${r.status}`);
  return r.json() as Promise<T>;
}

export const experimentApi = {
  list: () => apiGet<Experiment[]>("/api/experiments"),
  create: (name: string, goal: string) =>
    apiPost<Experiment>("/api/experiments", { name, goal }),
  detail: (experimentId: string) =>
    apiGet<ExperimentDetail>(`/api/experiments/${experimentId}`),
  lossCurve: (experimentId: string) =>
    apiGet<LossPoint[]>(`/api/experiments/${experimentId}/loss-curve`),
  createTask: (experimentId: string, userPrompt: string) =>
    apiPost<Task>(`/api/experiments/${experimentId}/tasks`, {
      user_prompt: userPrompt,
    }),
};

export const taskApi = {
  detail: (taskIdKey: string) => apiGet<TaskDetail>(`/api/tasks/${taskIdKey}`),
  lossSeries: (taskIdKey: string) =>
    apiGet<LossPoint[]>(`/api/tasks/${taskIdKey}/loss-series`),
  setBest: (taskIdKey: string, runId: string) =>
    apiPost<{ best_run_id: string; reason: string }>(
      `/api/tasks/${taskIdKey}/best`,
      { run_id: runId }
    ),
};
