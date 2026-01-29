// API client for AI Art Generator backend

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function fetchJson<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  return response.json();
}

// Health & Info
export const getHealth = () => fetchJson<{ status: string }>("/health");

export const getProviders = () =>
  fetchJson<{ image: string[]; text: string[]; research: string[] }>("/providers");

// Project (single project in cwd)
export const getProject = () =>
  fetchJson<{ name: string; path: string; config: Record<string, unknown>; asset_count: number }>(
    "/project"
  );

export const updateProjectConfig = (config: Record<string, unknown>) =>
  fetchJson<{ config: Record<string, unknown> }>("/project/config", {
    method: "PATCH",
    body: JSON.stringify(config),
  });

// Assets
export const listAssets = (status?: string) => {
  const params = status ? `?status=${status}` : "";
  return fetchJson<{ assets: Record<string, unknown>[] }>(`/assets${params}`);
};

export const addAssets = (
  items: { description: string; name?: string; metadata?: Record<string, unknown> }[],
  autoStart = false
) =>
  fetchJson<{ assets: Record<string, unknown>[] }>(
    `/assets?auto_start=${autoStart}`,
    {
      method: "POST",
      body: JSON.stringify(items),
    }
  );

export const uploadInput = (
  content: string,
  format: string = "text",
  autoStart = false
) =>
  fetchJson<{ assets: Record<string, unknown>[] }>(
    `/assets/upload?auto_start=${autoStart}`,
    {
      method: "POST",
      body: JSON.stringify({ content, format }),
    }
  );

export const getAsset = (assetId: string) =>
  fetchJson<Record<string, unknown>>(`/assets/${encodeURIComponent(assetId)}`);

// Processing
export const processAll = (autoApprove = false) =>
  fetchJson<{ message: string; asset_ids?: string[] }>(
    `/process?auto_approve=${autoApprove}`,
    { method: "POST" }
  );

export const processAsset = (assetId: string, autoApprove = false) =>
  fetchJson<{ message: string }>(
    `/assets/${encodeURIComponent(assetId)}/process?auto_approve=${autoApprove}`,
    { method: "POST" }
  );

// Approval Queue
export const getApprovalQueue = () =>
  fetchJson<{ queue: Record<string, unknown>[] }>("/queue");

export const submitApproval = (data: {
  asset_id: string;
  step_id: string;
  approved: boolean;
  selected_index?: number;
  regenerate?: boolean;
  modified_prompt?: string;
}) =>
  fetchJson<{ message: string; asset_id: string }>("/approve", {
    method: "POST",
    body: JSON.stringify(data),
  });

// Quick Generate
export const quickGenerate = (data: {
  prompt: string;
  provider?: string;
  variations?: number;
  style?: Record<string, unknown>;
}) =>
  fetchJson<{
    images: { index: number; width: number; height: number; data: string }[];
  }>("/generate", {
    method: "POST",
    body: JSON.stringify(data),
  });

// File URLs
export const getFileUrl = (filePath: string) =>
  `${API_BASE}/files/${filePath}`;

// Interactive Mode

export const getInteractiveStatus = () =>
  fetchJson<{
    total_assets: number;
    completed_assets: number;
    failed_assets: number;
    awaiting_approval: number;
    currently_generating: number;
    pending: number;
    is_running: boolean;
    is_paused: boolean;
  }>("/interactive/status");

export const getNextApproval = () =>
  fetchJson<{ item: Record<string, unknown> | null; message?: string }>(
    "/interactive/next"
  );

export const getAllApprovals = () =>
  fetchJson<{ items: Record<string, unknown>[] }>("/interactive/approvals");

export const getGeneratingItems = () =>
  fetchJson<{ items: Record<string, unknown>[] }>("/interactive/generating");

export const submitInteractiveApproval = (decision: {
  item_id: string;
  approved: boolean;
  selected_option_id?: string;
  regenerate?: boolean;
}) =>
  fetchJson<{ status: string; selected?: Record<string, unknown> }>(
    "/interactive/approve",
    {
      method: "POST",
      body: JSON.stringify(decision),
    }
  );

export const skipApproval = (itemId: string) =>
  fetchJson<{ status: string }>(`/interactive/skip/${encodeURIComponent(itemId)}`, {
    method: "POST",
  });

export const regenerateItem = (itemId: string) =>
  fetchJson<{ status: string }>(`/interactive/regenerate/${encodeURIComponent(itemId)}`, {
    method: "POST",
  });

export const startInteractive = () =>
  fetchJson<{ status: string; assets_queued: number }>("/interactive/start", {
    method: "POST",
  });

export const pauseInteractive = () =>
  fetchJson<{ status: string }>("/interactive/pause", {
    method: "POST",
  });

export const resumeInteractive = () =>
  fetchJson<{ status: string }>("/interactive/resume", {
    method: "POST",
  });

export const stopInteractive = () =>
  fetchJson<{ status: string }>("/interactive/stop", {
    method: "POST",
  });

// WebSocket URL
export const getWebSocketUrl = () => {
  const wsBase = API_BASE.replace(/^http/, "ws");
  return `${wsBase}/ws`;
};
