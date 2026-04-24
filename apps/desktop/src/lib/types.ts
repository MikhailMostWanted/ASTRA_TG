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
  status?: "available" | "unavailable" | string;
  reason: string | null;
  reasonCode?: string | null;
  actionHint?: string | null;
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
  chatRoster?: ChatRosterStatePayload | null;
  messageWorkspace?: WorkspaceStatusPayload | null;
  manualSend?: ManualSendJournalPayload | null;
  live?: LiveStatusPayload | null;
  managedProcess?: ProcessState;
}

export interface LiveStatusPayload {
  scope: "active_chat" | "roster" | "all" | string;
  source?: string | null;
  status: "live" | "paused" | "cached" | "refreshed" | "degraded" | "cleared" | string;
  active?: boolean;
  paused?: boolean;
  reason?: string | null;
  reasonCode?: string | null;
  chatId?: number | null;
  newMessageCount?: number;
  meaningfulMessageCount?: number;
  totalNewMessageCount?: number;
  totalMeaningfulMessageCount?: number;
  changedItemCount?: number;
  replyAction?: string | null;
  replySkippedReason?: string | null;
  refreshSource?: string | null;
  syncing?: boolean;
  lastUpdatedAt?: string | null;
  lastSuccessAt?: string | null;
  lastError?: string | null;
  lastErrorAt?: string | null;
  degraded?: boolean;
  degradedUntil?: string | null;
  nextRefreshAfter?: string | null;
  intervalSeconds?: number;
  latencyMs?: number;
  decisionStatus?: string | null;
  decisionReasonCode?: string | null;
  decisionAction?: string | null;
  pendingConfirmation?: boolean;
  lastAction?: string | null;
  timestamp?: string | null;
  record?: boolean;
  activity?: LiveStatusPayload[];
}

export interface ChatMemorySummary {
  summaryShort: string | null;
  currentState: string | null;
  updatedAt: string | null;
  pendingCount: number;
  topics: Array<string | Record<string, unknown>>;
}

export interface ChatIdentityPayload {
  id: number;
  localChatId: number | null;
  runtimeChatId: number;
  chatKey: string;
  workspaceAvailable: boolean;
}

export interface ChatRosterFreshnessPayload {
  mode: string;
  label: string;
  lastActivityAt: string | null;
}

export interface ChatAssetHintsPayload {
  avatarCached: boolean;
  avatarSource: string | null;
}

export interface ChatItem {
  id: number;
  localChatId: number | null;
  runtimeChatId: number;
  chatKey: string;
  workspaceAvailable: boolean;
  identity: ChatIdentityPayload;
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
  lastMessageKey: string | null;
  lastTelegramMessageId: number | null;
  lastMessagePreview: string;
  lastDirection: string | null;
  lastSourceAdapter: string | null;
  lastSenderName: string | null;
  avatarUrl: string | null;
  syncStatus: "fullaccess" | "local" | "runtime" | "empty" | string;
  memory: ChatMemorySummary | null;
  favorite: boolean;
  rosterSource: "legacy" | "new" | string;
  rosterLastActivityAt: string | null;
  rosterLastMessageKey: string | null;
  rosterLastMessagePreview: string;
  rosterLastDirection: string | null;
  rosterLastSenderName: string | null;
  rosterFreshness: ChatRosterFreshnessPayload;
  unreadCount: number;
  unreadMentionCount: number;
  pinned: boolean;
  muted: boolean;
  archived: boolean;
  assetHints: ChatAssetHintsPayload;
}

export interface ChatRosterStatePayload {
  source: "legacy" | "new" | string;
  requestedBackend: "legacy" | "new" | string | null;
  effectiveBackend: "legacy" | "new" | string | null;
  degraded: boolean;
  degradedReason: string | null;
  lastUpdatedAt: string | null;
  lastSuccessAt: string | null;
  lastError: string | null;
  lastErrorAt: string | null;
  route: RuntimeRoutePayload | Record<string, unknown>;
  live?: LiveStatusPayload | null;
}

export interface ChatsPayload {
  items: ChatItem[];
  count: number;
  source: "legacy" | "new" | string;
  roster: ChatRosterStatePayload;
  live?: LiveStatusPayload | null;
  refreshedAt: string | null;
  filters: {
    active: string;
    sort: string;
    search: string;
  };
}

export interface MessageItem {
  id: number;
  chatKey: string;
  messageKey: string;
  runtimeMessageId: number;
  localMessageId: number | null;
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
  replyToLocalMessageId: number | null;
  replyToRuntimeMessageId: number | null;
  replyToMessageKey: string | null;
  hasMedia: boolean;
  mediaType: string | null;
  mediaPreviewUrl: string | null;
  forwardInfo: Record<string, unknown> | unknown[] | null;
  entities: Record<string, unknown> | unknown[] | null;
  preview: string;
}

export interface MessageHistoryPayload {
  limit: number;
  returnedCount: number;
  hasMoreBefore: boolean;
  beforeRuntimeMessageId: number | null;
  oldestMessageKey: string | null;
  newestMessageKey: string | null;
  oldestRuntimeMessageId: number | null;
  newestRuntimeMessageId: number | null;
}

export interface WorkspaceAvailabilityPayload {
  workspaceAvailable: boolean;
  historyReadable: boolean;
  runtimeReadable: boolean;
  legacyWorkspaceAvailable: boolean;
  replyContextAvailable: boolean;
  sendAvailable: boolean;
  autopilotAvailable: boolean;
  canLoadOlder: boolean;
}

export interface MessageSourceIdentityPayload {
  backend: string;
  chatKey: string | null;
  runtimeChatId: number | null;
  localChatId: number | null;
  oldestMessageKey: string | null;
  newestMessageKey: string | null;
  oldestRuntimeMessageId: number | null;
  newestRuntimeMessageId: number | null;
}

export interface WorkspaceStatusPayload {
  source: "legacy" | "new" | string;
  requestedBackend: "legacy" | "new" | string | null;
  effectiveBackend: "legacy" | "new" | string | null;
  degraded: boolean;
  degradedReason: string | null;
  syncTrigger: string | null;
  updatedNow: boolean;
  syncError: string | null;
  lastUpdatedAt: string | null;
  lastSuccessAt: string | null;
  lastError: string | null;
  lastErrorAt: string | null;
  availability: WorkspaceAvailabilityPayload;
  messageSource: MessageSourceIdentityPayload;
  route?: RuntimeRoutePayload | Record<string, unknown>;
  sendPath?: RuntimeRoutePayload | Record<string, unknown>;
  sendDisabledReason?: string | null;
  live?: LiveStatusPayload | null;
}

export interface ChatMessagesPayload {
  chat: ChatItem;
  messages: MessageItem[];
  history: MessageHistoryPayload;
  status: WorkspaceStatusPayload;
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

export interface ReplyTriggerPayload {
  messageKey: string | null;
  localMessageId: number | null;
  runtimeMessageId: number | null;
  senderName: string | null;
  preview: string | null;
  sentAt: string | null;
  backend: string | null;
}

export interface ReplyFocusPayload {
  label: string | null;
  reason: string | null;
  score: number | null;
  selectionMessageCount: number;
}

export interface ReplyOpportunityPayload {
  mode: string | null;
  reason: string | null;
  replyRecommended: boolean;
}

export interface ReplyRetrievalHitPayload {
  id: number;
  chatId: number;
  chatTitle: string;
  inboundText: string;
  outboundText: string;
  exampleType: string;
  sourcePersonKey: string | null;
  qualityScore: number | null;
  score: number | null;
  createdAt: string | null;
  reasons: string[];
}

export interface ReplyRetrievalPayload {
  used: boolean;
  matchCount: number;
  strategyBias: string | null;
  lengthHint: string | null;
  rhythmHint: string | null;
  dominantTopicHint: string | null;
  messageCountHint?: number | null;
  styleMarkers?: string[];
  notes: string[];
  hits: ReplyRetrievalHitPayload[];
}

export interface ReplyStylePayload {
  profileKey: string | null;
  source: string | null;
  sourceReason: string | null;
  notes: string[];
  personaApplied: boolean;
  personaNotes: string[];
}

export interface ReplyFallbackPayload {
  code: string | null;
  reason: string | null;
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
  focusScore?: number | null;
  selectionMessageCount?: number;
  sourceMessageKey?: string | null;
  sourceLocalMessageId?: number | null;
  sourceRuntimeMessageId?: number | null;
  sourceBackend?: string | null;
  replyOpportunityMode: string | null;
  replyOpportunityReason: string | null;
  replyRecommended?: boolean;
  fewShotFound: boolean;
  fewShotMatchCount: number;
  fewShotNotes: string[];
  fewShotStrategyBias?: string | null;
  fewShotLengthHint?: string | null;
  fewShotRhythmHint?: string | null;
  fewShotDominantTopicHint?: string | null;
  fewShotMessageCountHint?: number | null;
  fewShotStyleMarkers?: string[];
  styleSourceReason?: string | null;
  alternativeAction: string | null;
  trigger?: ReplyTriggerPayload | null;
  focus?: ReplyFocusPayload | null;
  opportunity?: ReplyOpportunityPayload | null;
  retrieval?: ReplyRetrievalPayload | null;
  style?: ReplyStylePayload | null;
  fallback?: ReplyFallbackPayload | null;
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

export interface ReplyContextPayload {
  available: boolean;
  sourceBackend: string;
  focusLabel: string | null;
  focusReason: string | null;
  replyOpportunityMode: string | null;
  replyOpportunityReason: string | null;
  sourceMessageKey: string | null;
  sourceRuntimeMessageId: number | null;
  sourceLocalMessageId: number | null;
  sourceSenderName: string | null;
  sourceMessagePreview: string | null;
  sourceSentAt: string | null;
  draftScopeBasis: {
    sourceMessageKey: string | null;
    sourceMessageId: number | null;
    runtimeMessageId: number | null;
    focusLabel: string | null;
    sourceMessagePreview: string | null;
    replyOpportunityMode: string | null;
  } | null;
  draftScopeKey: string | null;
}

export interface AutopilotPayload {
  masterEnabled: boolean;
  allowChannels: boolean;
  globalMode?: "off" | "draft" | "semi_auto" | "autopilot" | string;
  emergencyStop?: boolean;
  autopilotPaused?: boolean;
  mode: "off" | "draft" | "semi_auto" | "confirm" | "autopilot" | string;
  effectiveMode?: "off" | "draft" | "semi_auto" | "autopilot" | string;
  trusted: boolean;
  allowed?: boolean;
  autopilotAllowed?: boolean;
  writeReady: boolean;
  policy?: Record<string, unknown>;
  state?: {
    status?: string;
    reasonCode?: string | null;
    reason?: string | null;
    updatedAt?: string | null;
    lastDecisionAt?: string | null;
  };
  decision: {
    mode: string;
    effectiveMode?: string;
    status?: string;
    action: string;
    allowed: boolean;
    reason: string;
    reasonCode?: string | null;
    confidence: number | null;
    trigger: string | null;
    focus?: string | null;
    opportunity?: string | null;
    sourceMessageId: number | null;
    sourceMessageKey?: string | null;
    sourceRuntimeMessageId?: number | null;
    replyText: string | null;
    draftScopeKey?: string | null;
    pendingDraftStatus: string | null;
    executionId?: string | null;
    sourceBackend?: string | null;
    workspaceSource?: string | null;
    freshnessMode?: string | null;
    freshnessSyncTrigger?: string | null;
    liveSource?: string | null;
    liveNewMessageCount?: number;
  };
  pendingDraft: {
    id?: string;
    executionId?: string;
    text?: string;
    mode?: string;
    status?: string;
    created_at?: string;
    createdAt?: string;
    source_message_id?: number;
    sourceMessageId?: number;
    source_message_key?: string;
    sourceMessageKey?: string;
    confidence?: number;
    trigger?: string;
    focus_label?: string;
    focus?: string;
    opportunity?: string;
    draft_scope_key?: string;
    draftScopeKey?: string;
    source_message_preview?: string;
    reply_opportunity_reason?: string;
  } | null;
  lastSentAt: string | null;
  lastSentSourceMessageId: number | null;
  lastSentSourceMessageKey?: string | null;
  lastSentMessageKey?: string | null;
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
    reasonCode?: string | null;
    reason_code?: string | null;
    confidence?: number | null;
    trigger?: string | null;
    focus?: string | null;
    opportunity?: string | null;
    chat_id?: number | null;
    source_message_id?: number | null;
    sent_message_id?: number | null;
    text_preview?: string | null;
    chat_key?: string | null;
    runtime_chat_id?: number | null;
    backend?: string | null;
    draft_scope_key?: string | null;
    sent_message_key?: string | null;
    error_code?: string | null;
    executionId?: string | null;
    execution_id?: string | null;
    allowed?: boolean | null;
  }>;
}

export interface ChatWorkspacePayload {
  chat: ChatItem;
  messages: MessageItem[];
  history: MessageHistoryPayload;
  replyContext: ReplyContextPayload | null;
  reply: ReplyPreviewPayload;
  autopilot: AutopilotPayload | null;
  freshness: ChatFreshnessPayload;
  status: WorkspaceStatusPayload;
  live?: LiveStatusPayload | null;
  refreshedAt: string | null;
}

export interface ChatSendPayload {
  ok: boolean;
  status: "success" | "failed" | "unavailable" | "degraded" | "fallback" | string;
  reason: string | null;
  error: { code: string; message: string | null } | null;
  source: "legacy" | "new" | string;
  requestedBackend: "legacy" | "new" | string | null;
  effectiveBackend: "legacy" | "new" | string | null;
  backend: "legacy" | "new" | string | null;
  route: RuntimeRoutePayload | Record<string, unknown>;
  fallback: {
    used: boolean;
    reason: string | null;
  };
  target: {
    requestedChatId: number;
    localChatId: number | null;
    runtimeChatId: number | null;
    chatKey: string | null;
  };
  sentMessage: MessageItem | null;
  sentMessageIdentity: Record<string, unknown> | null;
  workspace: ChatWorkspacePayload | null;
  debug: {
    journal: ManualSendJournalPayload;
    trace: Record<string, unknown> | null;
  };
}

export interface ChatSendPreparePayload {
  ok: boolean;
  status: string;
  ready: boolean;
  reason: string | null;
  error: { code: string; message: string | null } | null;
  source: string;
  requestedBackend: string | null;
  effectiveBackend: string | null;
  backend: string | null;
  route: RuntimeRoutePayload | Record<string, unknown>;
  target: {
    requestedChatId: number;
    localChatId: number | null;
    runtimeChatId: number | null;
    chatKey: string | null;
  };
  fallback: {
    used: boolean;
    reason: string | null;
  };
  draft: {
    scopeKey: string | null;
    sourceMessageId: number | null;
    sourceMessageKey: string | null;
    textLength: number;
  };
  debug: Record<string, unknown>;
}

export interface ManualSendJournalPayload {
  timestamp: string | null;
  chatKey: string | null;
  runtimeChatId: number | null;
  localChatId: number | null;
  requestedChatId?: number | null;
  backend: string | null;
  requestedBackend: string | null;
  effectiveBackend: string | null;
  draftScopeKey: string | null;
  clientSendId?: string | null;
  success: boolean;
  status: string;
  reason: string | null;
  errorReason: string | null;
  errorCode: string | null;
  sentMessageIdentity: Record<string, unknown> | null;
  route: RuntimeRoutePayload | Record<string, unknown>;
  fallback: {
    used: boolean;
    reason: string | null;
  };
}

export interface AutopilotGlobalPayload {
  policy?: Record<string, unknown>;
  globalPolicy?: Record<string, unknown>;
  settings: {
    master_enabled: boolean;
    allow_channels: boolean;
    cooldown_seconds?: number;
    min_prepare_confidence?: number;
    min_send_confidence?: number;
  };
  activity?: AutopilotPayload["journal"];
}

export interface ChatAutopilotPayload {
  chat: ChatItem;
  policy?: Record<string, unknown>;
  autopilot: AutopilotPayload;
  workspace?: ChatWorkspacePayload | null;
}

export interface AutopilotConfirmPayload {
  ok: boolean;
  status: string;
  reason: string | null;
  error: { code: string; message: string | null } | null;
  autopilot: AutopilotPayload | null;
  sentMessage?: MessageItem | null;
  sentMessageIdentity?: Record<string, unknown> | null;
  workspace: ChatWorkspacePayload | null;
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
