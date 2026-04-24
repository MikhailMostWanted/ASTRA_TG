import type {
  ChatMessagesPayload,
  ChatAutopilotPayload,
  AutopilotConfirmPayload,
  ChatSendPayload,
  ChatSendPreparePayload,
  ChatWorkspacePayload,
  ChatsPayload,
  AutopilotGlobalPayload,
  DashboardPayload,
  DigestOverviewPayload,
  DigestRunPayload,
  DigestTargetPayload,
  FullAccessChatsPayload,
  FullAccessCodePayload,
  FullAccessLoginPayload,
  FullAccessLogoutPayload,
  FullAccessOverviewPayload,
  FullAccessSyncPayload,
  HealthPayload,
  LogsPayload,
  MemoryOverviewPayload,
  MemoryRebuildPayload,
  OperationPayload,
  OpsOverviewPayload,
  RemindersOverviewPayload,
  ReminderScanPayload,
  ReplyPreviewPayload,
  RuntimeAuthActionPayload,
  RuntimeAuthStatusPayload,
  RuntimeStatusPayload,
  SourceMutationPayload,
  SourcesPayload,
} from "@/lib/types";

const DEFAULT_API_URL = (
  import.meta.env.VITE_ASTRA_DESKTOP_API_URL || "http://127.0.0.1:8765"
).replace(/\/$/, "");

let apiUrl = DEFAULT_API_URL;

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

type RequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
};

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, headers, ...init } = options;
  const response = await fetch(`${apiUrl}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...headers,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (!response.ok) {
    const errorBody = (await response.json().catch(() => null)) as
      | { detail?: string }
      | null;
    throw new ApiError(errorBody?.detail || "Не удалось выполнить запрос.", response.status);
  }

  return (await response.json()) as T;
}

export function setApiUrl(nextApiUrl: string) {
  apiUrl = nextApiUrl.replace(/\/$/, "");
}

export function getApiUrl() {
  return apiUrl;
}

function withQuery(path: string, params: Record<string, string | number | undefined>) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") {
      search.set(key, String(value));
    }
  }
  const query = search.toString();
  return query ? `${path}?${query}` : path;
}

export const api = {
  get apiUrl() {
    return apiUrl;
  },
  health: () => request<HealthPayload>("/health"),
  runtime: () => request<RuntimeStatusPayload>("/api/runtime"),
  newRuntimeHealth: () => request<RuntimeStatusPayload["newRuntime"]>("/api/runtime/new/health"),
  newRuntimeAuthStatus: () =>
    request<RuntimeAuthStatusPayload>("/api/runtime/new/auth"),
  requestNewRuntimeCode: () =>
    request<RuntimeAuthActionPayload>("/api/runtime/new/auth/request-code", { method: "POST" }),
  submitNewRuntimeCode: (payload: { code: string }) =>
    request<RuntimeAuthActionPayload>("/api/runtime/new/auth/submit-code", {
      method: "POST",
      body: payload,
    }),
  submitNewRuntimePassword: (payload: { password: string }) =>
    request<RuntimeAuthActionPayload>("/api/runtime/new/auth/submit-password", {
      method: "POST",
      body: payload,
    }),
  logoutNewRuntime: () =>
    request<RuntimeAuthActionPayload>("/api/runtime/new/auth/logout", { method: "POST" }),
  resetNewRuntime: () =>
    request<RuntimeAuthActionPayload>("/api/runtime/new/auth/reset", { method: "POST" }),
  dashboard: () => request<DashboardPayload>("/api/dashboard"),
  ops: (tail = 80) => request<OpsOverviewPayload>(withQuery("/api/ops", { tail })),
  logs: (component?: string, tail = 80) =>
    request<LogsPayload>(withQuery("/api/logs", { component, tail })),
  chats: (params: { search?: string; filter?: string; sort?: string }) =>
    request<ChatsPayload>(
      withQuery("/api/chats", {
        search: params.search,
        filter: params.filter,
        sort: params.sort,
      }),
    ),
  chatMessages: (chatId: number, limit = 80, beforeRuntimeMessageId?: number | null) =>
    request<ChatMessagesPayload>(
      withQuery(`/api/chats/${chatId}/messages`, {
        limit,
        before_runtime_message_id: beforeRuntimeMessageId ?? undefined,
      }),
    ),
  chatWorkspace: (chatId: number, limit = 80) =>
    request<ChatWorkspacePayload>(withQuery(`/api/chats/${chatId}/workspace`, { limit })),
  replyPreview: (chatId: number, useProviderRefinement?: boolean) =>
    request<ReplyPreviewPayload>(
      withQuery(`/api/chats/${chatId}/reply-preview`, {
        use_provider_refinement:
          typeof useProviderRefinement === "boolean"
            ? useProviderRefinement
              ? "true"
              : "false"
            : undefined,
      }),
      { method: "POST" },
    ),
  sendChatMessage: (
    chatId: number,
    payload: {
      text: string;
      source_message_id?: number | null;
      reply_to_source_message_id?: number | null;
      source_message_key?: string | null;
      reply_to_source_message_key?: string | null;
      draft_scope_key?: string | null;
      client_send_id?: string | null;
    },
  ) =>
    request<ChatSendPayload>(`/api/chats/${chatId}/send`, {
      method: "POST",
      body: payload,
    }),
  prepareChatSend: (
    chatId: number,
    payload: {
      text: string;
      source_message_id?: number | null;
      source_message_key?: string | null;
      draft_scope_key?: string | null;
      client_send_id?: string | null;
    },
  ) =>
    request<ChatSendPreparePayload>(`/api/chats/${chatId}/send/prepare`, {
      method: "POST",
      body: payload,
    }),
  autopilotStatus: (chatId?: number) =>
    request<AutopilotGlobalPayload | ChatAutopilotPayload>(
      typeof chatId === "number" ? `/api/chats/${chatId}/autopilot` : "/api/autopilot",
    ),
  updateAutopilotGlobal: (payload: {
    mode?: string;
    master_enabled?: boolean;
    allow_channels?: boolean;
    emergency_stop?: boolean;
    autopilot_paused?: boolean;
  }) =>
    request<AutopilotGlobalPayload>("/api/autopilot", {
      method: "POST",
      body: payload,
    }),
  emergencyStopAutopilot: () =>
    request<AutopilotGlobalPayload>("/api/autopilot/emergency-stop", { method: "POST" }),
  pauseAutopilot: (paused: boolean) =>
    request<AutopilotGlobalPayload>("/api/autopilot/pause", {
      method: "POST",
      body: { paused },
    }),
  autopilotActivity: (limit = 20) =>
    request<{ items: AutopilotGlobalPayload["activity"]; count: number }>(
      withQuery("/api/autopilot/activity", { limit }),
    ),
  updateChatAutopilot: (
    chatId: number,
    payload: { trusted?: boolean; allowed?: boolean; autopilot_allowed?: boolean; mode?: string },
  ) =>
    request<ChatAutopilotPayload>(`/api/chats/${chatId}/autopilot`, {
      method: "POST",
      body: payload,
    }),
  confirmAutopilotPending: (chatId: number, pendingId?: string | null) =>
    request<AutopilotConfirmPayload>(`/api/chats/${chatId}/autopilot/confirm`, {
      method: "POST",
      body: { pending_id: pendingId ?? null },
    }),
  sources: () => request<SourcesPayload>("/api/sources"),
  addSource: (payload: { reference?: string; title?: string; chat_type?: string }) =>
    request<SourceMutationPayload>("/api/sources", {
      method: "POST",
      body: payload,
    }),
  enableSource: (chatId: number) =>
    request<SourceMutationPayload>(`/api/sources/${chatId}/enable`, { method: "POST" }),
  disableSource: (chatId: number) =>
    request<SourceMutationPayload>(`/api/sources/${chatId}/disable`, { method: "POST" }),
  syncSource: (chatId: number) =>
    request<FullAccessSyncPayload>(`/api/sources/${chatId}/sync`, { method: "POST" }),
  fullaccess: () => request<FullAccessOverviewPayload>("/api/fullaccess"),
  fullaccessChats: (limit = 25) =>
    request<FullAccessChatsPayload>(withQuery("/api/fullaccess/chats", { limit })),
  requestFullaccessCode: () =>
    request<FullAccessCodePayload>("/api/fullaccess/request-code", { method: "POST" }),
  loginFullaccess: (payload: { code: string; password?: string }) =>
    request<FullAccessLoginPayload>("/api/fullaccess/login", {
      method: "POST",
      body: payload,
    }),
  logoutFullaccess: () =>
    request<FullAccessLogoutPayload>("/api/fullaccess/logout", { method: "POST" }),
  syncFullaccessChat: (reference: string) =>
    request<FullAccessSyncPayload>("/api/fullaccess/sync", {
      method: "POST",
      body: { reference },
    }),
  memory: (limit = 20) => request<MemoryOverviewPayload>(withQuery("/api/memory", { limit })),
  rebuildMemory: (reference?: string) =>
    request<MemoryRebuildPayload>("/api/memory/rebuild", {
      method: "POST",
      body: { reference },
    }),
  digest: (limit = 6) => request<DigestOverviewPayload>(withQuery("/api/digest", { limit })),
  runDigest: (payload: { window?: string; use_provider_improvement?: boolean }) =>
    request<DigestRunPayload>("/api/digest/run", {
      method: "POST",
      body: payload,
    }),
  setDigestTarget: (payload: { reference?: string; label?: string }) =>
    request<DigestTargetPayload>("/api/digest/target", {
      method: "POST",
      body: payload,
    }),
  reminders: () => request<RemindersOverviewPayload>("/api/reminders"),
  scanReminders: (payload: { window_argument?: string; source_reference?: string }) =>
    request<ReminderScanPayload>("/api/reminders/scan", {
      method: "POST",
      body: payload,
    }),
  runOperation: (action: string, component?: string) =>
    request<OperationPayload>(withQuery(`/api/operations/${action}`, { component }), {
      method: "POST",
    }),
};
