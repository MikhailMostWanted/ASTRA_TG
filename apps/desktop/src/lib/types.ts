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
  runtime?: RuntimeStatusPayload;
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
  runtime?: RuntimeStatusPayload;
}

export interface RuntimeAuthPayload {
  state: string;
  authState: string;
  sessionState: string;
  authorized: boolean;
  awaitingCode: boolean;
  awaitingPassword: boolean;
  canRequestCode: boolean;
  canSubmitCode: boolean;
  canSubmitPassword: boolean;
  canLogout: boolean;
  canReset: boolean;
  user: {
    id: number | null;
    username: string | null;
    phoneHint: string | null;
  };
  device: {
    id: string | null;
    name: string | null;
  };
  session: {
    path: string | null;
    stored: boolean;
  };
  updatedAt: string | null;
  stateChangedAt: string | null;
  codeRequestedAt: string | null;
  authorizedAt: string | null;
  logoutStartedAt: string | null;
  lastCheckedAt: string | null;
  timestamps: {
    updatedAt: string | null;
    stateChangedAt: string | null;
    codeRequestedAt: string | null;
    authorizedAt: string | null;
    logoutStartedAt: string | null;
    lastCheckedAt: string | null;
    errorAt: string | null;
  };
  reasonCode: string | null;
  reason: string | null;
  error: {
    code: string | null;
    message: string | null;
    at: string | null;
  } | null;
}

export interface RuntimeAuthStatusPayload {
  status: RuntimeAuthPayload;
}

export interface RuntimeAuthActionPayload {
  kind: string;
  message: string;
  status: RuntimeAuthPayload;
}

export interface RuntimeBackendPayload {
  backend: "legacy" | "new" | string;
  name: string;
  registered: boolean;
  lifecycle: string;
  active: boolean;
  healthy: boolean;
  ready: boolean;
  routeAvailable: boolean;
  startedAt: string | null;
  stoppedAt: string | null;
  uptimeSeconds: number | null;
  lastError: string | null;
  degradedReason: string | null;
  unavailableReason: string | null;
  auth: RuntimeAuthPayload | null;
  capabilities: string[];
}

export interface RuntimeRoutePayload {
  surface: string;
  requested: "legacy" | "new" | string;
  effective: "legacy" | "new" | string;
  targetAvailable: boolean;
  targetReady: boolean;
  reason: string | null;
}

export interface RuntimeStatusPayload {
  generatedAt: string;
  defaultBackend: string;
  registeredBackends: string[];
  routes: {
    targetRegistered: boolean;
    routes: Record<string, RuntimeRoutePayload>;
  };
  backends: Record<string, RuntimeBackendPayload>;
  legacy: RuntimeBackendPayload | null;
  newRuntime: RuntimeBackendPayload | null;
  managedProcess?: ProcessState;
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
  syncTrigger: string | null;
  updatedNow: boolean;
  syncError: string | null;
}

export interface LLMDecisionReasonPayload {
  source: string;
  code: string;
  summary: string;
  detail: string;
  flags: string[];
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
  replyOpportunityMode: string | null;
  replyOpportunityReason: string | null;
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
    mode: "deterministic" | "llm_refine" | "fallback" | "rejected_by_guardrails" | string;
    label: string;
    provider: string | null;
    detail: string | null;
  } | null;
  llmDebug: {
    mode: string;
    baselineMessages: string[];
    baselineText: string | null;
    rawCandidate: string | null;
    decisionReason: LLMDecisionReasonPayload | null;
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
    send: boolean;
    markSent: boolean;
    variants: Record<string, boolean>;
    disabledReason: string | null;
  };
}

export interface AutopilotPayload {
  masterEnabled: boolean;
  allowChannels: boolean;
  mode: "off" | "draft" | "confirm" | "autopilot" | string;
  trusted: boolean;
  writeReady: boolean;
  decision: {
    mode: string;
    action: string;
    allowed: boolean;
    reason: string;
    confidence: number | null;
    trigger: string | null;
    sourceMessageId: number | null;
    replyText: string | null;
    pendingDraftStatus: string | null;
  };
  pendingDraft: {
    text?: string;
    mode?: string;
    status?: string;
    created_at?: string;
    source_message_id?: number;
    confidence?: number;
    trigger?: string;
    focus_label?: string;
    source_message_preview?: string;
    reply_opportunity_reason?: string;
  } | null;
  lastSentAt: string | null;
  lastSentSourceMessageId: number | null;
  cooldown: {
    active: boolean;
    remainingSeconds: number;
    until: string | null;
  };
  journal: Array<{
    timestamp?: string;
    action?: string;
    mode?: string;
    status?: string;
    actor?: string;
    automatic?: boolean;
    message?: string;
    reason?: string | null;
    confidence?: number | null;
    trigger?: string | null;
    chat_id?: number | null;
    source_message_id?: number | null;
    sent_message_id?: number | null;
    text_preview?: string | null;
  }>;
}

export interface ChatWorkspacePayload {
  chat: ChatItem;
  messages: MessageItem[];
  reply: ReplyPreviewPayload;
  autopilot: AutopilotPayload | null;
  freshness: ChatFreshnessPayload;
  refreshedAt: string | null;
}

export interface ChatSendPayload {
  ok: boolean;
  sentMessage: MessageItem | null;
  workspace: ChatWorkspacePayload;
}

export interface AutopilotGlobalPayload {
  settings: {
    master_enabled: boolean;
    allow_channels: boolean;
    cooldown_seconds?: number;
    min_prepare_confidence?: number;
    min_send_confidence?: number;
  };
}

export interface ChatAutopilotPayload {
  chat: ChatItem;
  autopilot: AutopilotPayload;
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
  readyForManualSend: boolean;
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
    mode: "deterministic" | "llm_refine" | "fallback" | "rejected_by_guardrails" | string;
    label: string;
    llm_requested: boolean;
    llm_applied: boolean;
    provider: string | null;
    notes: string[];
    flags: string[];
    summary_short: string | null;
    debug: {
      mode: string;
      baseline: {
        summary_short: string | null;
        overview_lines: string[];
        key_source_lines: string[];
      };
      raw_candidate: string | null;
      decision_reason: LLMDecisionReasonPayload | null;
    } | null;
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
  llmDebug: {
    mode: string;
    baseline: {
      summaryShort: string | null;
      overviewLines: string[];
      keySourceLines: string[];
    };
    rawCandidate: string | null;
    decisionReason: LLMDecisionReasonPayload | null;
  } | null;
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
