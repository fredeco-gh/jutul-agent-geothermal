// The wire protocol, typed. This is the TypeScript mirror of the server's
// `interfaces/server/protocol.py` (+ the side-channel events app.py emits). Both
// ends now code against one explicit contract, so a renamed or reshaped field is
// a compile error here instead of a silent runtime bug.

/** A pending approval's individual action (one tool call awaiting a decision). */
export interface InterruptAction {
  name: string;
  label?: string;
  args?: Record<string, unknown>;
  description?: string | null;
}

/** Messages the server streams to the client over the WebSocket. */
export type ServerMessage =
  | { type: "text"; text: string }
  | { type: "reasoning"; text: string }
  | {
      type: "tool";
      event: "requested" | "delta" | "finished" | "error";
      name: string | null;
      label?: string;
      tool_call_id: string | null;
      args?: Record<string, unknown> | null;
      content?: string | null;
      /** A delta carries the full terminal-rendered output so far: replace, not append. */
      replace?: boolean;
    }
  | {
      type: "interrupt";
      interrupt_id: string;
      actions: InterruptAction[];
      allowed_decisions: string[];
      allowlist: string[];
    }
  | {
      type: "usage";
      input_tokens: number;
      output_tokens: number;
      total_tokens: number;
      model_calls: number;
    }
  | { type: "turn_end"; text: string; cancelled?: boolean }
  | {
      type: "artifact";
      url: string;
      mime?: string | null;
      caption?: string | null;
      slot?: string | null;
      format?: string | null;
    }
  | {
      type: "viz";
      url: string;
      title?: string | null;
      kind: string;
      poster?: string | null;
      slot?: string | null;
      /** A host app pinning its own always-open view (e.g. a map), outside any
       *  actual turn, isn't a conversation event worth a chat reference. */
      silent?: boolean;
    }
  | { type: "notice"; text: string }
  | {
      type: "ui";
      action: string;
      payload: Record<string, unknown>;
      /** A view id: routes this action to that view's panel (e.g. the map)
       *  instead of appending a chat thread note. Omitted means global. */
      target?: string;
    }
  | { type: "credential_required"; provider: string; label: string; env_var: string }
  | { type: "error"; message: string };

export type ServerMessageType = ServerMessage["type"];

/** Messages the client sends to the server. */
export type ClientMessage =
  | { type: "prompt"; text: string }
  | { type: "decision"; decision: string; message?: string }
  | { type: "cancel" }
  | { type: "command"; command: "set_model" | "set_approval" | "add_dir" | "compact"; arg: string }
  | { type: "ui_event"; payload: unknown }
  // A host-app-defined operation a front end triggers directly, bypassing the
  // model entirely (see jutul_agent.interfaces.server.app.ActionHandler) — for
  // when the front end already has exact, structured inputs and there is
  // nothing for the model to decide, unlike a normal tool call.
  | { type: "action"; name: string; args?: Record<string, unknown> };

/**
 * One recorded item from `GET /sessions/{id}/messages`, replayed to reconstruct a
 * resumed conversation. A superset of the live stream: it also carries the `user`
 * and `assistant` text the live path delivers as bubbles and `text` deltas.
 */
export type ReplayMessage =
  | { type: "user"; text: string }
  | { type: "assistant"; text: string }
  | { type: "reasoning"; text: string }
  | Extract<ServerMessage, { type: "tool" | "viz" | "artifact" }>;

/** Parse a raw WebSocket text frame, or return null if it is not a typed message. */
export function parseServerMessage(data: string): ServerMessage | null {
  try {
    const msg = JSON.parse(data);
    return msg && typeof msg.type === "string" ? (msg as ServerMessage) : null;
  } catch {
    return null;
  }
}

/** Side outputs (a plot/report, a usage tick, a host-app ui action) can arrive
 *  mid-turn while the agent keeps working, so they must NOT clear the "thinking"
 *  indicator — only the agent's own content (or the turn ending) does. A `notice`
 *  is deliberately excluded: it signals a command finished (e.g. /compact), so its
 *  handler legitimately ends the working/busy state rather than passing through. */
export const SIDE_OUTPUT_TYPES: ReadonlySet<ServerMessageType> = new Set([
  "usage",
  "viz",
  "artifact",
  "ui",
]);

/** A `ui` action the client consumes internally (a history-refresh signal) instead
 *  of rendering it as a note in the thread. Named once here so the store (which
 *  suppresses the thread item) and the controller (which runs the refresh) reference
 *  the same action and can't drift apart on a rename. */
export const HISTORY_CHANGED = "history_changed";
