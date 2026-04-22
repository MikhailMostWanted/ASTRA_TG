export type ScreenId =
  | "dashboard"
  | "chats"
  | "sources"
  | "fullaccess"
  | "memory"
  | "digest"
  | "reminders"
  | "logs";

export type StatusTone =
  | "online"
  | "offline"
  | "warning"
  | "muted"
  | "success"
  | "danger";

export interface HealthPayload {
  ok: boolean;
  name: string;
  version: string;
}

export interface ProcessState {
  component: string;
  status: StatusTone;
  running: boolean;
  managed: boolean;
  stalePidFile: boolean;
  pid: number | null;
  command: string | null;
  detail: string;
  pidPath: string;
  logPath: string;
}

export interface StatusCardItem {
  key: string;
  label: string;
  status: StatusTone;
  value: string;
  detail: string;
}

export interface DashboardPayload {
  repositoryRoot: string;
  database: {
    available: boolean;
    detail: string;
    databaseUrl: string | null;
    sqlitePath: string | null;
  };
  providerApi: {
    enabled: boolean;
    configured: boolean;
    available: boolean;
    providerName: string | null;
    reason: string | null;
  };
  summary: {
    readyChecks: number;
    totalChecks: number;
    nextSteps: string[];
    warnings: string[];
  };
  statusCards: StatusCardItem[];
  attention: Array<{ tone: StatusTone; text: string }>;
  activity: Array<{ timestamp: string | null; title: string; detail: string | null }>;
  errors: Array<{ tone: StatusTone; title: string; text: string }>;
  astraNow: string[];
  quickActions: Array<{ id: string; label: string; kind: string; enabled: boolean }>;
  processes: ProcessState[];
}

export interface ChatMemorySummary {
  summaryShort: string | null;
  currentState: string | null;
  updatedAt: string | null;
  pendingCount: number;
  topics: Array<string | Record<string, unknown>>;
}

export interface ChatItem {
  id: number;
  telegramChatId: number;
  reference: string;
  title: string;
  handle: string | null;
  type: string;
  enabled: boolean;
  category: string | null;
  summarySchedule: string | null;
  replyAssistEnabled: boolean;
  autoReplyMode: string | null;
  excludeFromMemory: boolean;
  excludeFromDigest: boolean;
  isDigestTarget: boolean;
  messageCount: number;
  lastMessageAt: string | null;
  lastMessageId: number | null;
  lastTelegramMessageId: number | null;
  lastMessagePreview: string;
  lastDirection: string | null;
  lastSourceAdapter: string | null;
  lastSenderName: string | null;
  avatarUrl: string | null;
  syncStatus: "fullaccess" | "local" | "empty";
  memory: ChatMemorySummary | null;
  favorite: boolean;
}

export interface ChatsPayload {
  items: ChatItem[];
  count: number;
  refreshedAt: string | null;
  filters: {
    active: string;
    sort: string;
    search: string;
  };
}

export interface MessageItem {
  id: number;
  telegramMessageId: number | null;
  chatId: number;
  direction: "inbound" | "outbound" | string;
  sourceAdapter: string | null;
  sourceType: string | null;
  senderId: number | null;
  senderName: string | null;
  sentAt: string | null;
  text: string | null;
  normalizedText: string | null;
  replyToMessageId: number | null;
  hasMedia: boolean;
  mediaType: string | null;
  mediaPreviewUrl: string | null;
  forwardInfo: Record<string, unknown> | null;
  entities: unknown[] | null;
  preview: string;
}

export interface ChatMessagesPayload {
  chat: ChatItem;
  messages: MessageItem[];
  refreshedAt: string | null;
}

export interface ChatFreshnessPayload {
  mode: "local" | "fresh" | "aging" | "stale" | "missing" | "attention" | string;
  label: string;
  detail: string;
  isStale: boolean;
  fullaccessReady: boolean;
  canManualSync: boolean;
  lastSyncAt: string | null;
  reference: string | null;
  createdCount: number;
  updatedCount: number;
  skippedCount: number;
}

export interface ReplySuggestion {
  baseReplyText: string | null;
  replyMessages: string[];
  finalReplyMessages: string[];
  replyText: string | null;
  styleProfileKey: string | null;
  styleSource: string | null;
  styleNotes: string[];
  personaApplied: boolean;
  personaNotes: string[];
  guardrailFlags: string[];
  reasonShort: string | null;
  riskLabel: string | null;
  confidence: number | null;
  strategy: string | null;
  sourceMessageId: number | null;
  chatId: number | null;
  situation: string | null;
  sourceMessagePreview: string | null;
  focusLabel: string | null;
  focusReason: string | null;
  fewShotFound: boolean;
  fewShotMatchCount: number;
  fewShotNotes: string[];
  alternativeAction: string | null;
  llmRefineRequested: boolean;
  llmRefineApplied: boolean;
  llmRefineProvider: string | null;
  llmRefineNotes: string[];
  llmRefineGuardrailFlags: string[];
  llmStatus: {
    mode: "deterministic" | "llm_refine" | "fallback" | string;
    label: string;
    provider: string | null;
    detail: string | null;
  } | null;
  variants: Array<{
    id: string;
    label: string;
    description: string;
    text: string;
  }>;
}

export interface ReplyPreviewPayload {
  kind: string;
  chatId: number | null;
  chatTitle: string | null;
  chatReference: string | null;
  errorMessage: string | null;
  sourceSenderName: string | null;
  sourceMessagePreview: string | null;
  suggestion: ReplySuggestion | null;
  actions: {
    copy: boolean;
    refresh: boolean;
    pasteToTelegram: boolean;
    markSent: boolean;
    variants: Record<string, boolean>;
    disabledReason: string | null;
  };
}

export interface ChatWorkspacePayload {
  chat: ChatItem;
  messages: MessageItem[];
  reply: ReplyPreviewPayload;
  freshness: ChatFreshnessPayload;
  refreshedAt: string | null;
}

export interface SourcesPayload {
  items: ChatItem[];
  count: number;
  onboarding: string;
}

export interface SourceMutationPayload {
  message: string;
  source: ChatItem;
}

export interface FullAccessStatus {
  enabled: boolean;
  apiCredentialsConfigured: boolean;
  phoneConfigured: boolean;
  sessionPath: string;
  sessionExists: boolean;
  authorized: boolean;
  telethonAvailable: boolean;
  requestedReadonly: boolean;
  effectiveReadonly: boolean;
  syncLimit: number;
  pendingLogin: boolean;
  syncedChatCount: number;
  syncedMessageCount: number;
  readyForManualSync: boolean;
  reason: string | null;
}

export interface FullAccessOverviewPayload {
  status: FullAccessStatus;
  instructions: string[];
  localLoginCommand: string;
  onboarding: string;
}

export interface FullAccessChat {
  telegramChatId: number;
  title: string;
  chatType: string;
  username: string | null;
  reference: string;
  avatarUrl: string | null;
}

export interface FullAccessChatsPayload {
  items: FullAccessChat[];
  truncated: boolean;
  returnedCount: number;
}

export interface FullAccessCodePayload {
  kind: string;
  phone: string | null;
  instructions: string[];
}

export interface FullAccessLoginPayload extends FullAccessCodePayload {}

export interface FullAccessLogoutPayload {
  sessionRemoved: boolean;
  pendingAuthCleared: boolean;
}

export interface FullAccessSyncPayload {
  chat: FullAccessChat;
  localChatId: number;
  chatCreated: boolean;
  scannedCount: number;
  createdCount: number;
  updatedCount: number;
  skippedCount: number;
}

export interface MemoryItem {
  id: number;
  chatId: number;
  chatTitle: string | null;
  summaryShort: string | null;
  summaryLong: string | null;
  currentState: string | null;
  topics: Array<string | Record<string, unknown>>;
  recentConflicts: Array<string | Record<string, unknown>>;
  pendingTasks: Array<string | Record<string, unknown>>;
  linkedPeople: Array<string | Record<string, unknown>>;
  lastDigestAt: string | null;
  updatedAt: string | null;
}

export interface MemoryOverviewPayload {
  summary: {
    chatCards: number;
    peopleCards: number;
    lastRebuildAt: string | null;
    lastRebuildStats: Record<string, unknown> | null;
  };
  items: MemoryItem[];
}

export interface MemoryRebuildPayload {
  updatedChatCount: number;
  updatedPeopleCount: number;
  analyzedMessageCount: number;
  message: string;
}

export interface DigestRecordItem {
  id: number;
  sourceChatId: number | null;
  sourceChatTitle: string | null;
  sourceMessageId: number | null;
  title: string | null;
  summary: string | null;
  link: string | null;
  sortOrder: number;
}

export interface DigestRecord {
  id: number;
  chatId: number | null;
  windowStart: string | null;
  windowEnd: string | null;
  summaryShort: string | null;
  summaryLong: string | null;
  deliveredToChatId: number | null;
  deliveredMessageId: number | null;
  createdAt: string | null;
  items: DigestRecordItem[];
}

export interface DigestOverviewPayload {
  target: {
    chatId: string | null;
    label: string | null;
    chatType: string | null;
  };
  latest: DigestRecord | null;
  recentRuns: DigestRecord[];
  generation: {
    digest_id: number | null;
    window: string;
    mode: "deterministic" | "llm_refine" | "fallback" | string;
    label: string;
    llm_requested: boolean;
    llm_applied: boolean;
    provider: string | null;
    notes: string[];
    flags: string[];
    summary_short: string | null;
  } | null;
}

export interface DigestRunPayload {
  window: string;
  hasDigest: boolean;
  messageCount: number;
  sourceCount: number;
  summaryShort: string | null;
  previewChunks: string[];
  targetConfigured: boolean;
  target: {
    chatId: string | null;
    label: string | null;
    chatType: string | null;
  };
  llmRefineRequested: boolean;
  llmRefineApplied: boolean;
  llmRefineProvider: string | null;
  llmRefineNotes: string[];
  llmRefineGuardrailFlags: string[];
  digest: DigestRecord | null;
}

export interface DigestTargetPayload {
  chatId: string | null;
  label: string | null;
  chatType: string | null;
  note: string | null;
  message: string;
}

export interface TaskItem {
  id: number;
  status: string;
  title: string;
  summary: string | null;
  dueAt: string | null;
  suggestedRemindAt: string | null;
  confidence: number | null;
  needsUserConfirmation: boolean;
  sourceChatId: number | null;
  sourceChatTitle: string | null;
  sourceMessageId: number | null;
  sourceMessagePreview: string | null;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface ReminderItem {
  id: number;
  taskId: number;
  status: string;
  remindAt: string | null;
  lastNotificationAt: string | null;
  payload: Record<string, unknown> | null;
  task: TaskItem | null;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface RemindersOverviewPayload {
  summary: {
    candidateCount: number;
    confirmedTaskCount: number;
    activeReminderCount: number;
    lastNotificationAt: string | null;
  };
  candidates: TaskItem[];
  tasks: TaskItem[];
  reminders: ReminderItem[];
}

export interface ReminderScanPayload {
  summaryText: string;
  cards: string[];
  createdCount: number;
  skippedExistingCount: number;
  overview: RemindersOverviewPayload;
}

export interface OpsOverviewPayload {
  doctor: {
    okItems: string[];
    warnings: string[];
    nextSteps: string[];
  };
  processes: Array<ProcessState & { lines: string[] }>;
  actions: Array<{ id: string; label: string; enabled: boolean }>;
}

export interface LogsPayload {
  items: Array<ProcessState & { lines: string[] }>;
}

export interface OperationSummaryItem {
  component: string;
  ok: boolean;
  started?: boolean;
  stopped?: boolean;
  pid?: number | null;
  detail: string;
}

export interface OperationPayload {
  action: string;
  results?: OperationSummaryItem[];
  stopResults?: OperationSummaryItem[];
  startResults?: OperationSummaryItem[];
  created?: boolean;
  path?: string;
  sourcePath?: string;
  payload?: Record<string, unknown>;
  okItems?: string[];
  warnings?: string[];
  nextSteps?: string[];
}
