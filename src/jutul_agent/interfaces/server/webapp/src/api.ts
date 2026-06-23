// The REST surface of the server (everything except the per-turn WebSocket),
// typed. Mirrors the FastAPI routes in interfaces/server/app.py.

import type { ReplayMessage } from "./protocol";

export interface ModelInfo {
  id: string;
  label: string;
  provider: string;
  note?: string | null;
}

export interface SimDetails {
  display_name?: string;
  examples?: string[];
}

export interface HistoryEntry {
  id: string;
  title: string;
  started: string;
  last_active: string;
  sim: string;
}

export interface SimulatorsResponse {
  simulators: string[];
  default: string | null;
  details: Record<string, SimDetails>;
}

export interface ModelsResponse {
  default: string | null;
  providers: string[];
  models: ModelInfo[];
}

async function getJSON<T>(url: string, fallback: T): Promise<T> {
  try {
    const resp = await fetch(url);
    if (!resp.ok) return fallback;
    return (await resp.json()) as T;
  } catch {
    return fallback;
  }
}

async function postJSON<T>(url: string, body: unknown): Promise<T> {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(await resp.text().catch(() => resp.statusText));
  return (await resp.json()) as T;
}

export const api = {
  simulators: () =>
    getJSON<SimulatorsResponse>("/simulators", { simulators: [], default: null, details: {} }),

  models: () =>
    getJSON<ModelsResponse>("/models", { default: null, providers: [], models: [] }),

  modelWindow: (model: string) =>
    getJSON<{ model: string; window: number | null }>(
      `/models/window?model=${encodeURIComponent(model)}`,
      { model, window: null },
    ),

  history: async (limit = 40): Promise<HistoryEntry[]> => {
    const data = await getJSON<{ sessions: HistoryEntry[] }>(
      `/sessions/history?limit=${limit}`,
      { sessions: [] },
    );
    return data.sessions;
  },

  messages: async (id: string): Promise<ReplayMessage[]> => {
    const data = await getJSON<{ messages: ReplayMessage[] }>(
      `/sessions/${id}/messages`,
      { messages: [] },
    );
    return data.messages;
  },

  createSession: (body: { sim?: string; model?: string }) =>
    postJSON<{ session_id: string }>("/sessions", body),

  resumeSession: (id: string, body: { sim?: string; model?: string }) =>
    postJSON<{ session_id: string; kernel_restarted: boolean }>(`/sessions/${id}/resume`, body),

  deleteSession: (id: string) =>
    fetch(`/sessions/${id}`, { method: "DELETE" }).catch(() => undefined),

  context: (id: string) =>
    getJSON<{ markdown: string }>(`/sessions/${id}/context`, { markdown: "" }),

  uploadFile: async (id: string, file: File): Promise<{ path: string }> => {
    const fd = new FormData();
    fd.append("file", file);
    const resp = await fetch(`/sessions/${id}/upload`, { method: "POST", body: fd });
    if (!resp.ok) throw new Error(await resp.text().catch(() => resp.statusText));
    return (await resp.json()) as { path: string };
  },

  transcriptUrl: (id: string, fmt: "html" | "md") =>
    `/sessions/${id}/transcript?format=${fmt}`,

  memoryUrl: (id: string) => `/sessions/${id}/memory`,
};
