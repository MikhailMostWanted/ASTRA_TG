import type {
  ChatMessagesPayload,
  ChatsPayload,
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
  chatMessages: (chatId: number, limit = 80) =>
    request<ChatMessagesPayload>(withQuery(`/api/chats/${chatId}/messages`, { limit })),
  replyPreview: (chatId: number, useProviderRefinement = false) =>
    request<ReplyPreviewPayload>(
      withQuery(`/api/chats/${chatId}/reply-preview`, {
        use_provider_refinement: useProviderRefinement ? "true" : undefined,
      }),
      { method: "POST" },
    ),
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
