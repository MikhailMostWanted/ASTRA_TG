import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ReplyPanel } from "@/components/system/ReplyPanel";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { ReplyPreviewPayload, WorkspaceStatusPayload } from "@/lib/types";
import { buildReplyDraftScopeKey } from "@/stores/app-store";

describe("ReplyPanel", () => {
  it("does not crash on malformed reply payloads from the bridge", () => {
    render(
      <TooltipProvider>
        <ReplyPanel
          reply={
            {
              kind: "suggestion",
              sourceMessagePreview: "Когда сможешь вернуться с апдейтом?",
              sourceSenderName: "Анна",
              suggestion: {
                confidence: 0.82,
                focusLabel: "вопрос",
                focusReason: "Последний осмысленный входящий trigger.",
                sourceMessageId: 512,
                replyMessages: null,
                finalReplyMessages: undefined,
                styleNotes: null,
                personaNotes: undefined,
                fewShotNotes: "broken",
                guardrailFlags: null,
                llmRefineNotes: undefined,
              },
            } as unknown as ReplyPreviewPayload
          }
          workflowState={null}
          onRefresh={vi.fn()}
          onCopy={vi.fn()}
          onUseDraft={vi.fn()}
          onMarkSent={vi.fn()}
          onClearDraft={vi.fn()}
        />
      </TooltipProvider>,
    );

    expect(screen.getByText("Панель ответа")).toBeInTheDocument();
    expect(screen.getByText("Главный вариант")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Использовать как черновик" })).toBeInTheDocument();
  });

  it("renders a collapsed llm debug block with rejected candidate details", () => {
    render(
      <TooltipProvider>
        <ReplyPanel
          reply={{
            kind: "suggestion",
            chatId: 42,
            chatTitle: "Команда продукта",
            chatReference: "@product_team",
            errorMessage: null,
            sourceSenderName: "Анна",
            sourceMessagePreview: "Когда сможешь скинуть финальный файл?",
            actions: {
              copy: true,
              refresh: true,
              pasteToTelegram: false,
              send: false,
              markSent: false,
              variants: {},
              disabledReason: null,
            },
            suggestion: {
              baseReplyText: "Понял, посмотрю и вернусь.",
              replyMessages: ["Понял, посмотрю и вернусь."],
              finalReplyMessages: ["Понял, посмотрю и вернусь."],
              replyText: "Понял, посмотрю и вернусь.",
              styleProfileKey: "friend_explain",
              styleSource: "auto",
              styleNotes: [],
              personaApplied: true,
              personaNotes: [],
              guardrailFlags: [],
              reasonShort: "Есть открытый вопрос.",
              riskLabel: "низкий",
              confidence: 0.82,
              strategy: "мягко ответить",
              sourceMessageId: 512,
              chatId: 42,
              situation: "question",
              sourceMessagePreview: "Анна: Когда сможешь скинуть финальный файл?",
              focusLabel: "вопрос",
              focusReason: "Выбран последний незакрытый вопрос.",
              replyOpportunityMode: "follow_up_after_self",
              replyOpportunityReason: "Несмотря на последнее исходящее, в теме остался незакрытый хвост.",
              fewShotFound: false,
              fewShotMatchCount: 0,
              fewShotNotes: [],
              alternativeAction: null,
              llmRefineRequested: true,
              llmRefineApplied: false,
              llmRefineProvider: "openai_compatible",
              llmRefineNotes: ["LLM-кандидат отклонён guardrails."],
              llmRefineGuardrailFlags: ["слишком_литературно"],
              llmStatus: {
                mode: "rejected_by_guardrails",
                label: "Отклонён guardrails",
                provider: "openai_compatible",
                detail: "Сработали guardrails: слишком_литературно. Сохранена детерминированная база.",
              },
              llmDebug: {
                mode: "rejected_by_guardrails",
                baselineMessages: ["Понял, посмотрю и вернусь."],
                baselineText: "Понял, посмотрю и вернусь.",
                rawCandidate: "В данном случае благодарю за терпение, завтра утром отправлю файл на 25 страниц!!!",
                decisionReason: {
                  source: "guardrails",
                  code: "guardrails_rejected",
                  summary: "LLM-кандидат для reply отклонён guardrails.",
                  detail: "Сработали guardrails: слишком_литературно. Сохранена детерминированная база.",
                  flags: ["слишком_литературно"],
                },
              },
              variants: [
                {
                  id: "primary",
                  label: "Основной",
                  description: "Рекомендуемый вариант для отправки.",
                  text: "Понял, посмотрю и вернусь.",
                },
              ],
            },
          }}
          live={{
            scope: "active_chat",
            status: "refreshed",
            reasonCode: "meaningful_signal",
            replyAction: "started",
            decisionStatus: "awaiting_confirmation",
            pendingConfirmation: true,
            newMessageCount: 1,
            meaningfulMessageCount: 1,
            lastAction: "Режим semi_auto: подготовлен черновик, требуется один явный confirm.",
          }}
          workflowState={null}
          onRefresh={vi.fn()}
          onCopy={vi.fn()}
          onUseDraft={vi.fn()}
          onMarkSent={vi.fn()}
          onClearDraft={vi.fn()}
        />
      </TooltipProvider>,
    );

    expect(screen.getByText("Отладка / детали")).toBeInTheDocument();
    expect(screen.queryByText("Сырой LLM-кандидат")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Отладка \/ детали/i }));

    expect(screen.getByText("Сырой LLM-кандидат")).toBeInTheDocument();
    expect(screen.getAllByText(/слишком_литературно/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/детерминированная база/i).length).toBeGreaterThan(0);
  });

  it("deduplicates sender prefix in trigger preview", () => {
    render(
      <TooltipProvider>
        <ReplyPanel
          reply={{
            kind: "suggestion",
            chatId: 52,
            chatTitle: "Личный чат",
            chatReference: "@nastya",
            errorMessage: null,
            sourceSenderName: "Настенька💗",
            sourceMessagePreview: "Настенька💗: Настенька💗: Красиво слаженно",
            actions: {
              copy: true,
              refresh: true,
              pasteToTelegram: false,
              send: false,
              markSent: false,
              variants: {},
              disabledReason: null,
            },
            suggestion: {
              baseReplyText: "Понял.",
              replyMessages: ["Понял."],
              finalReplyMessages: ["Понял."],
              replyText: "Понял.",
              styleProfileKey: "friend_explain",
              styleSource: "auto",
              styleNotes: [],
              personaApplied: false,
              personaNotes: [],
              guardrailFlags: [],
              reasonShort: "Есть фокус.",
              riskLabel: "низкий",
              confidence: 0.7,
              strategy: "поддержать",
              sourceMessageId: 901,
              chatId: 52,
              situation: "small_talk",
              sourceMessagePreview: "Настенька💗: Красиво слаженно",
              focusLabel: "продолжение темы",
              focusReason: "Свежий фрагмент ещё держит тему.",
              replyOpportunityMode: "direct_reply",
              replyOpportunityReason: "Последний входящий сигнал остаётся без ответа.",
              fewShotFound: false,
              fewShotMatchCount: 0,
              fewShotNotes: [],
              alternativeAction: null,
              llmRefineRequested: false,
              llmRefineApplied: false,
              llmRefineProvider: null,
              llmRefineNotes: [],
              llmRefineGuardrailFlags: [],
              llmStatus: null,
              llmDebug: null,
              variants: [],
            },
          }}
          workflowState={null}
          onRefresh={vi.fn()}
          onCopy={vi.fn()}
          onUseDraft={vi.fn()}
          onMarkSent={vi.fn()}
          onClearDraft={vi.fn()}
        />
      </TooltipProvider>,
    );

    expect(screen.getByText("Настенька💗: Красиво слаженно")).toBeInTheDocument();
    expect(screen.queryByText("Настенька💗: Настенька💗: Красиво слаженно")).not.toBeInTheDocument();
  });

  it("hides stale draft text when current focus changed", () => {
    render(
      <TooltipProvider>
        <ReplyPanel
          reply={{
            kind: "suggestion",
            chatId: 42,
            chatTitle: "Команда продукта",
            chatReference: "@product_team",
            errorMessage: null,
            sourceSenderName: "Анна",
            sourceMessagePreview: "Когда сможешь скинуть финальный файл?",
            actions: {
              copy: true,
              refresh: true,
              pasteToTelegram: false,
              send: false,
              markSent: false,
              variants: {},
              disabledReason: null,
            },
            suggestion: {
              baseReplyText: "Понял, посмотрю и вернусь.",
              replyMessages: ["Понял, посмотрю и вернусь."],
              finalReplyMessages: ["Понял, посмотрю и вернусь."],
              replyText: "Понял, посмотрю и вернусь.",
              styleProfileKey: "friend_explain",
              styleSource: "auto",
              styleNotes: [],
              personaApplied: true,
              personaNotes: [],
              guardrailFlags: [],
              reasonShort: "Есть открытый вопрос.",
              riskLabel: "низкий",
              confidence: 0.82,
              strategy: "мягко ответить",
              sourceMessageId: 512,
              chatId: 42,
              situation: "question",
              sourceMessagePreview: "Анна: Когда сможешь скинуть финальный файл?",
              focusLabel: "вопрос",
              focusReason: "Выбран последний незакрытый вопрос.",
              replyOpportunityMode: "direct_reply",
              replyOpportunityReason: "Последний осмысленный входящий сигнал остаётся без ответа.",
              fewShotFound: false,
              fewShotMatchCount: 0,
              fewShotNotes: [],
              alternativeAction: null,
              llmRefineRequested: false,
              llmRefineApplied: false,
              llmRefineProvider: null,
              llmRefineNotes: [],
              llmRefineGuardrailFlags: [],
              llmStatus: null,
              llmDebug: null,
              variants: [],
            },
          }}
          workflowState={{
            seenMessageKey: "telegram:-10042:512",
            seenMessageId: 512,
            draftText: "Старый черновик не по теме",
            draftSourceMessageKey: "telegram:-10042:401",
            draftSourceMessageId: 401,
            draftFocusLabel: "просьба",
            draftScopeKey: buildReplyDraftScopeKey({
              sourceMessageId: 401,
              sourceMessageKey: "telegram:-10042:401",
              focusLabel: "просьба",
              sourceMessagePreview: "Скинь, пожалуйста, итоговый файл.",
              replyOpportunityMode: "direct_reply",
            }),
            draftUpdatedAt: "2026-04-22T12:30:00.000Z",
            sentSourceMessageKey: null,
            sentSourceMessageId: null,
            sentAt: null,
          }}
          onRefresh={vi.fn()}
          onCopy={vi.fn()}
          onUseDraft={vi.fn()}
          onMarkSent={vi.fn()}
          onClearDraft={vi.fn()}
        />
      </TooltipProvider>,
    );

    expect(screen.getByText("Черновик устарел для текущего фокуса")).toBeInTheDocument();
    expect(screen.queryByText("Старый черновик не по теме")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Скопировать старый черновик" })).toBeInTheDocument();
  });

  it("shows an explicit no-reply state instead of fake variants", () => {
    render(
      <TooltipProvider>
        <ReplyPanel
          reply={{
            kind: "suggestion",
            chatId: 77,
            chatTitle: "Спокойный чат",
            chatReference: "@quiet_chat",
            errorMessage: null,
            sourceSenderName: "Анна",
            sourceMessagePreview: "ок",
            actions: {
              copy: true,
              refresh: true,
              pasteToTelegram: false,
              send: false,
              markSent: true,
              variants: {},
              disabledReason: "Send-path на этом этапе остаётся выключенным.",
            },
            suggestion: {
              baseReplyText: "Сейчас лучше не писать.",
              replyMessages: [],
              finalReplyMessages: [],
              replyText: "Сейчас лучше не писать.",
              styleProfileKey: "friend_explain",
              styleSource: "auto",
              styleNotes: [],
              personaApplied: false,
              personaNotes: [],
              guardrailFlags: [],
              reasonShort: "Явного повода писать сейчас нет.",
              riskLabel: "лучше не отвечать",
              confidence: 0.83,
              strategy: "не отвечать",
              sourceMessageId: 701,
              chatId: 77,
              situation: "no_reply",
              sourceMessagePreview: "Анна: ок",
              focusLabel: "слабый триггер",
              focusReason: "В окне нет явного вопроса или просьбы.",
              focusScore: 0.22,
              selectionMessageCount: 10,
              sourceMessageKey: "telegram:-10077:701",
              sourceLocalMessageId: 701,
              sourceRuntimeMessageId: 701,
              sourceBackend: "legacy_local_store",
              replyOpportunityMode: "hold",
              replyOpportunityReason: "Явного повода писать сейчас нет.",
              replyRecommended: false,
              fewShotFound: false,
              fewShotMatchCount: 0,
              fewShotNotes: [],
              alternativeAction: "Подожди нового сигнала или вернись позже с фактом.",
              trigger: {
                messageKey: "telegram:-10077:701",
                localMessageId: 701,
                runtimeMessageId: 701,
                senderName: "Анна",
                preview: "ок",
                sentAt: null,
                backend: "legacy_local_store",
              },
              focus: {
                label: "слабый триггер",
                reason: "В окне нет явного вопроса или просьбы.",
                score: 0.22,
                selectionMessageCount: 10,
              },
              opportunity: {
                mode: "hold",
                reason: "Явного повода писать сейчас нет.",
                replyRecommended: false,
              },
              retrieval: {
                used: false,
                matchCount: 0,
                strategyBias: null,
                lengthHint: null,
                rhythmHint: null,
                dominantTopicHint: null,
                notes: [],
                hits: [],
              },
              style: {
                profileKey: "friend_explain",
                source: "auto",
                sourceReason: "Спокойный дефолтный профиль.",
                notes: [],
                personaApplied: false,
                personaNotes: [],
              },
              fallback: {
                code: null,
                reason: null,
              },
              llmRefineRequested: false,
              llmRefineApplied: false,
              llmRefineProvider: null,
              llmRefineNotes: [],
              llmRefineGuardrailFlags: [],
              llmStatus: null,
              llmDebug: null,
              variants: [],
            },
          }}
          workflowState={null}
          onRefresh={vi.fn()}
          onCopy={vi.fn()}
          onUseDraft={vi.fn()}
          onMarkSent={vi.fn()}
          onClearDraft={vi.fn()}
        />
      </TooltipProvider>,
    );

    expect(screen.getByText("Сейчас лучше не отвечать")).toBeInTheDocument();
    expect(screen.getByText("Подожди нового сигнала или вернись позже с фактом.")).toBeInTheDocument();
    expect(screen.queryByText("Варианты ответа")).not.toBeInTheDocument();
    expect(screen.queryByText("Черновик перед отправкой")).not.toBeInTheDocument();
  });

  it("sends only the current editable draft with source key and draft scope", () => {
    const onSend = vi.fn();
    render(
      <TooltipProvider>
        <ReplyPanel
          reply={{
            kind: "suggestion",
            chatId: -200001,
            chatTitle: "Runtime chat",
            chatReference: "@runtime_chat",
            errorMessage: null,
            sourceSenderName: "Анна",
            sourceMessagePreview: "Сможешь посмотреть это сегодня?",
            actions: {
              copy: true,
              refresh: true,
              pasteToTelegram: false,
              send: true,
              markSent: false,
              variants: {},
              disabledReason: null,
            },
            suggestion: {
              baseReplyText: "Да, посмотрю сейчас.",
              replyMessages: ["Да, посмотрю сейчас."],
              finalReplyMessages: ["Да, посмотрю сейчас."],
              replyText: "Да, посмотрю сейчас.",
              styleProfileKey: "friend_explain",
              styleSource: "auto",
              styleNotes: [],
              personaApplied: false,
              personaNotes: [],
              guardrailFlags: [],
              reasonShort: "Есть вопрос.",
              riskLabel: "низкий",
              confidence: 0.8,
              strategy: "ответить коротко",
              sourceMessageId: null,
              chatId: -200001,
              situation: "question",
              sourceMessagePreview: "Сможешь посмотреть это сегодня?",
              focusLabel: "вопрос",
              focusReason: "Последний входящий вопрос.",
              sourceMessageKey: "telegram:-100777:41",
              sourceLocalMessageId: null,
              sourceRuntimeMessageId: 41,
              sourceBackend: "new_runtime",
              replyOpportunityMode: "direct_reply",
              replyOpportunityReason: "Последний входящий сигнал без ответа.",
              replyRecommended: true,
              fewShotFound: false,
              fewShotMatchCount: 0,
              fewShotNotes: [],
              alternativeAction: null,
              llmRefineRequested: false,
              llmRefineApplied: false,
              llmRefineProvider: null,
              llmRefineNotes: [],
              llmRefineGuardrailFlags: [],
              llmStatus: null,
              llmDebug: null,
              variants: [
                {
                  id: "primary",
                  label: "Основной",
                  description: "Короткий ответ.",
                  text: "Да, посмотрю сейчас.",
                },
              ],
            },
          }}
          replyContext={{
            available: true,
            sourceBackend: "new",
            focusLabel: "вопрос",
            focusReason: "Последний входящий вопрос.",
            replyOpportunityMode: "direct_reply",
            replyOpportunityReason: "Последний входящий сигнал без ответа.",
            sourceMessageKey: "telegram:-100777:41",
            sourceRuntimeMessageId: 41,
            sourceLocalMessageId: null,
            sourceSenderName: "Анна",
            sourceMessagePreview: "Сможешь посмотреть это сегодня?",
            sourceSentAt: "2026-04-23T09:04:00+00:00",
            draftScopeBasis: {
              sourceMessageKey: "telegram:-100777:41",
              sourceMessageId: null,
              runtimeMessageId: 41,
              focusLabel: "вопрос",
              sourceMessagePreview: "Сможешь посмотреть это сегодня?",
              replyOpportunityMode: "direct_reply",
            },
            draftScopeKey: "telegram:-100777:41::вопрос::direct_reply::Сможешь посмотреть это сегодня?",
          }}
          workspaceStatus={{
            source: "new",
            requestedBackend: "new",
            effectiveBackend: "new",
            degraded: false,
            degradedReason: null,
            syncTrigger: "runtime_poll",
            updatedNow: true,
            syncError: null,
            lastUpdatedAt: "2026-04-23T09:05:02.000Z",
            lastSuccessAt: "2026-04-23T09:05:02.000Z",
            lastError: null,
            lastErrorAt: null,
            availability: {
              workspaceAvailable: true,
              historyReadable: true,
              runtimeReadable: true,
              legacyWorkspaceAvailable: false,
              replyContextAvailable: true,
              sendAvailable: true,
              autopilotAvailable: false,
              canLoadOlder: true,
            },
            messageSource: {
              backend: "new_runtime",
              chatKey: "telegram:-100777",
              runtimeChatId: -100777,
              localChatId: null,
              oldestMessageKey: "telegram:-100777:40",
              newestMessageKey: "telegram:-100777:41",
              oldestRuntimeMessageId: 40,
              newestRuntimeMessageId: 41,
            },
            route: {},
            sendPath: { effective: "new" },
            sendDisabledReason: null,
          }}
          live={{
            scope: "active_chat",
            status: "refreshed",
            reasonCode: "meaningful_signal",
            replyAction: "started",
            decisionStatus: "awaiting_confirmation",
            pendingConfirmation: true,
            newMessageCount: 1,
            meaningfulMessageCount: 1,
            lastAction: "Режим semi_auto: подготовлен черновик, требуется один явный confirm.",
          }}
          workflowState={null}
          onRefresh={vi.fn()}
          onCopy={vi.fn()}
          onUseDraft={vi.fn()}
          onSend={onSend}
          onMarkSent={vi.fn()}
          onClearDraft={vi.fn()}
        />
      </TooltipProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Использовать как черновик" }));
    fireEvent.change(screen.getByPlaceholderText("Вставь вариант, поправь формулировку и отправь явно."), {
      target: { value: "Да, посмотрю сейчас и отпишусь." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Отправить" }));

    expect(onSend).toHaveBeenCalledWith(
      "Да, посмотрю сейчас и отпишусь.",
      null,
      "telegram:-100777:41",
      "telegram:-100777:41::вопрос::direct_reply::Сможешь посмотреть это сегодня?",
    );
    expect(screen.queryByText("Отправить вариант")).not.toBeInTheDocument();
  });

  it("shows loading and disabled states for rebuild and send feedback", () => {
    render(
      <TooltipProvider>
        <ReplyPanel
          reply={buildAutopilotReply()}
          workspaceStatus={buildWritableWorkspaceStatus()}
          workflowState={null}
          refreshing
          sending
          sendStatus={{
            status: "pending",
            message: "Отправляю сообщение.",
            backend: "new",
            sentMessageKey: null,
            timestamp: "2026-04-24T12:05:00.000Z",
            tone: "pending",
          }}
          onRefresh={vi.fn()}
          onCopy={vi.fn()}
          onUseDraft={vi.fn()}
          onSend={vi.fn()}
          onMarkSent={vi.fn()}
          onClearDraft={vi.fn()}
        />
      </TooltipProvider>,
    );

    expect(screen.getByRole("button", { name: "Пересобираю" })).toBeDisabled();
    const sendButton = screen.getByRole("button", { name: "Отправляю" });
    expect(sendButton).toBeDisabled();
    expect(sendButton).toHaveAttribute("aria-busy", "true");
    expect(screen.getAllByText("Отправляю сообщение.").length).toBeGreaterThan(0);
    expect(screen.getByText(/основной Telegram/)).toBeInTheDocument();
  });

  it("shows owner style variant as a cascade instead of one paragraph", () => {
    const reply = buildAutopilotReply();
    reply.suggestion!.variants = [
      {
        id: "primary",
        label: "Основной",
        description: "Главный вариант.",
        text: "да понял\nщас посмотрю",
      },
      {
        id: "short",
        label: "Короче",
        description: "Коротко.",
        text: "ща гляну",
      },
      {
        id: "soft",
        label: "Мягче",
        description: "Мягче.",
        text: "да я понял тебя\nспокойно посмотрю",
      },
      {
        id: "owner_style",
        label: "В моём стиле",
        description: "Каскад.",
        text: "не не\nя не про это\nщас пытаюсь понять\nчто ты имеешь в виду",
      },
    ];

    render(
      <TooltipProvider>
        <ReplyPanel
          reply={reply}
          workflowState={null}
          onRefresh={vi.fn()}
          onCopy={vi.fn()}
          onUseDraft={vi.fn()}
          onMarkSent={vi.fn()}
          onClearDraft={vi.fn()}
        />
      </TooltipProvider>,
    );

    expect(screen.getAllByText("В моём стиле").length).toBeGreaterThan(0);
    expect(screen.getByText("не не")).toBeInTheDocument();
    expect(screen.getByText("я не про это")).toBeInTheDocument();
    expect(screen.getByText("щас пытаюсь понять")).toBeInTheDocument();
    expect(screen.queryByText("не не\nя не про это\nщас пытаюсь понять\nчто ты имеешь в виду")).not.toBeInTheDocument();
  });

  it("renders workspace context without reply generation when new runtime is read-only", () => {
    render(
      <TooltipProvider>
        <ReplyPanel
          reply={{
            kind: "workspace_context_only",
            chatId: -200001,
            chatTitle: "Runtime chat",
            chatReference: "@runtime_chat",
            errorMessage: null,
            sourceSenderName: "Анна",
            sourceMessagePreview: "Сможешь посмотреть это сегодня?",
            suggestion: null,
            actions: {
              copy: false,
              refresh: true,
              pasteToTelegram: false,
              send: false,
              markSent: false,
              variants: {},
              disabledReason: "Write-path на этом этапе выключен.",
            },
          }}
          replyContext={{
            available: true,
            sourceBackend: "new",
            focusLabel: "вопрос",
            focusReason: "Последний входящий message остаётся без ответа.",
            replyOpportunityMode: "direct_reply",
            replyOpportunityReason: "Есть свежий незакрытый вопрос.",
            sourceMessageKey: "telegram:-100777:51",
            sourceRuntimeMessageId: 51,
            sourceLocalMessageId: null,
            sourceSenderName: "Анна",
            sourceMessagePreview: "Сможешь посмотреть это сегодня?",
            sourceSentAt: "2026-04-23T09:05:00.000Z",
            draftScopeBasis: {
              sourceMessageKey: "telegram:-100777:51",
              sourceMessageId: null,
              runtimeMessageId: 51,
              focusLabel: "вопрос",
              sourceMessagePreview: "Сможешь посмотреть это сегодня?",
              replyOpportunityMode: "direct_reply",
            },
            draftScopeKey: "telegram:-100777:51::вопрос::direct_reply::Сможешь посмотреть это сегодня?",
          }}
          freshness={null}
          workspaceStatus={{
            source: "new",
            requestedBackend: "new",
            effectiveBackend: "new",
            degraded: false,
            degradedReason: null,
            syncTrigger: "runtime_poll",
            updatedNow: true,
            syncError: null,
            lastUpdatedAt: "2026-04-23T09:05:02.000Z",
            lastSuccessAt: "2026-04-23T09:05:02.000Z",
            lastError: null,
            lastErrorAt: null,
            availability: {
              workspaceAvailable: true,
              historyReadable: true,
              runtimeReadable: true,
              legacyWorkspaceAvailable: false,
              replyContextAvailable: true,
              sendAvailable: false,
              autopilotAvailable: false,
              canLoadOlder: true,
            },
            messageSource: {
              backend: "new_runtime",
              chatKey: "telegram:-100777",
              runtimeChatId: -100777,
              localChatId: null,
              oldestMessageKey: "telegram:-100777:40",
              newestMessageKey: "telegram:-100777:51",
              oldestRuntimeMessageId: 40,
              newestRuntimeMessageId: 51,
            },
            route: {},
          }}
          workflowState={null}
          onRefresh={vi.fn()}
          onCopy={vi.fn()}
          onUseDraft={vi.fn()}
          onMarkSent={vi.fn()}
          onClearDraft={vi.fn()}
        />
      </TooltipProvider>,
    );

    expect(screen.getByText("Панель ответа")).toBeInTheDocument();
    expect(screen.getByText("ответ не собран")).toBeInTheDocument();
    expect(screen.getByText("Контекст найден, но готовый текст или отправка сейчас недоступны.")).toBeInTheDocument();
    expect(screen.getByText("Последний входящий message остаётся без ответа.")).toBeInTheDocument();
    expect(screen.getByText("вопрос")).toBeInTheDocument();
    expect(screen.getByText(/можно читать контекст, но отправлять готовый ответ пока нельзя/)).toBeInTheDocument();
  });

  it("renders managed reply execution controls and confirms pending semi-auto send", () => {
    const onUpdateGlobal = vi.fn();
    const onUpdateChat = vi.fn();
    const onConfirm = vi.fn();
    const onEmergencyStop = vi.fn();

    render(
      <TooltipProvider>
        <ReplyPanel
          reply={buildAutopilotReply()}
          autopilot={{
            masterEnabled: true,
            allowChannels: false,
            globalMode: "semi_auto",
            emergencyStop: false,
            autopilotPaused: false,
            mode: "semi_auto",
            effectiveMode: "semi_auto",
            trusted: true,
            allowed: false,
            autopilotAllowed: false,
            writeReady: true,
            decision: {
              mode: "semi_auto",
              effectiveMode: "semi_auto",
              status: "awaiting_confirmation",
              action: "confirm",
              allowed: true,
              reason: "Режим semi_auto: подготовлен черновик, требуется один явный confirm.",
              reasonCode: "confirm_required",
              confidence: 0.91,
              trigger: "вопрос",
              focus: "вопрос",
              opportunity: "direct_reply",
              sourceMessageId: null,
              sourceMessageKey: "telegram:-100777:41",
              sourceRuntimeMessageId: 41,
              replyText: "Да, посмотрю сейчас.",
              draftScopeKey: "telegram:-100777:41::вопрос::direct_reply::Сможешь посмотреть это сегодня?",
              pendingDraftStatus: "awaiting_confirmation",
              executionId: "rex_test_confirm",
            },
            pendingDraft: {
              id: "rex_test_confirm",
              executionId: "rex_test_confirm",
              text: "Да, посмотрю сейчас.",
              mode: "semi_auto",
              status: "awaiting_confirmation",
              sourceMessageKey: "telegram:-100777:41",
              confidence: 0.91,
              trigger: "вопрос",
              draftScopeKey: "telegram:-100777:41::вопрос::direct_reply::Сможешь посмотреть это сегодня?",
            },
            lastSentAt: null,
            lastSentSourceMessageId: null,
            cooldown: {
              active: false,
              remainingSeconds: 0,
              until: null,
            },
            journal: [
              {
                timestamp: "2026-04-24T12:00:00.000Z",
                action: "confirm_awaited",
                status: "awaiting_confirmation",
                message: "Ждёт подтверждения",
                reasonCode: "confirm_required",
              },
            ],
          }}
          workspaceStatus={{
            source: "new",
            requestedBackend: "new",
            effectiveBackend: "new",
            degraded: false,
            degradedReason: null,
            syncTrigger: "runtime_poll",
            updatedNow: true,
            syncError: null,
            lastUpdatedAt: "2026-04-23T09:05:02.000Z",
            lastSuccessAt: "2026-04-23T09:05:02.000Z",
            lastError: null,
            lastErrorAt: null,
            availability: {
              workspaceAvailable: true,
              historyReadable: true,
              runtimeReadable: true,
              legacyWorkspaceAvailable: false,
              replyContextAvailable: true,
              sendAvailable: true,
              autopilotAvailable: true,
              canLoadOlder: true,
            },
            messageSource: {
              backend: "new_runtime",
              chatKey: "telegram:-100777",
              runtimeChatId: -100777,
              localChatId: null,
              oldestMessageKey: "telegram:-100777:41",
              newestMessageKey: "telegram:-100777:41",
              oldestRuntimeMessageId: 41,
              newestRuntimeMessageId: 41,
            },
            route: {},
            sendPath: { effective: "new" },
            sendDisabledReason: null,
          }}
          live={{
            scope: "active_chat",
            status: "refreshed",
            reasonCode: "meaningful_signal",
            replyAction: "started",
            decisionStatus: "awaiting_confirmation",
            pendingConfirmation: true,
            newMessageCount: 1,
            meaningfulMessageCount: 1,
            lastAction: "Режим semi_auto: подготовлен черновик, требуется один явный confirm.",
          }}
          workflowState={null}
          onRefresh={vi.fn()}
          onCopy={vi.fn()}
          onUseDraft={vi.fn()}
          onSend={vi.fn()}
          onMarkSent={vi.fn()}
          onClearDraft={vi.fn()}
          onUpdateAutopilotGlobal={onUpdateGlobal}
          onUpdateChatAutopilot={onUpdateChat}
          onConfirmAutopilot={onConfirm}
          onEmergencyStop={onEmergencyStop}
        />
      </TooltipProvider>,
    );

    expect(screen.getByText("Глобально: Полуавтомат")).toBeInTheDocument();
    expect(screen.getAllByText("ждёт подтверждение").length).toBeGreaterThan(0);
    expect(screen.getByText("Безопасность автопилота")).toBeInTheDocument();
    expect(screen.getAllByText("Ждёт подтверждения").length).toBeGreaterThan(0);
    fireEvent.change(screen.getByLabelText("Глобальный режим"), { target: { value: "autopilot" } });
    expect(onUpdateGlobal).not.toHaveBeenCalledWith({ mode: "autopilot" });
    expect(screen.getByText("Подтверди включение автопилота")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Включить автопилот" }));
    fireEvent.change(screen.getByLabelText("Режим чата"), { target: { value: "draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить отправку" }));
    fireEvent.click(screen.getByRole("button", { name: "Экстренный стоп" }));

    expect(onUpdateGlobal).toHaveBeenCalledWith({ mode: "autopilot" });
    expect(onUpdateChat).toHaveBeenCalledWith({ mode: "draft" });
    expect(onConfirm).toHaveBeenCalledWith("rex_test_confirm");
    expect(onEmergencyStop).toHaveBeenCalled();
  });
});

function buildAutopilotReply(): ReplyPreviewPayload {
  return {
    kind: "suggestion",
    chatId: -200001,
    chatTitle: "Runtime chat",
    chatReference: "@runtime_chat",
    errorMessage: null,
    sourceSenderName: "Анна",
    sourceMessagePreview: "Сможешь посмотреть это сегодня?",
    actions: {
      copy: true,
      refresh: true,
      pasteToTelegram: false,
      send: true,
      markSent: false,
      variants: {},
      disabledReason: null,
    },
    suggestion: {
      baseReplyText: "Да, посмотрю сейчас.",
      replyMessages: ["Да, посмотрю сейчас."],
      finalReplyMessages: ["Да, посмотрю сейчас."],
      replyText: "Да, посмотрю сейчас.",
      styleProfileKey: "friend_explain",
      styleSource: "auto",
      styleNotes: [],
      personaApplied: false,
      personaNotes: [],
      guardrailFlags: [],
      reasonShort: "Есть вопрос.",
      riskLabel: "низкий",
      confidence: 0.91,
      strategy: "ответить коротко",
      sourceMessageId: null,
      chatId: -200001,
      situation: "question",
      sourceMessagePreview: "Сможешь посмотреть это сегодня?",
      focusLabel: "вопрос",
      focusReason: "Последний входящий вопрос.",
      sourceMessageKey: "telegram:-100777:41",
      sourceLocalMessageId: null,
      sourceRuntimeMessageId: 41,
      sourceBackend: "new_runtime",
      replyOpportunityMode: "direct_reply",
      replyOpportunityReason: "Последний входящий вопрос без ответа.",
      replyRecommended: true,
      fewShotFound: false,
      fewShotMatchCount: 0,
      fewShotNotes: [],
      alternativeAction: null,
      llmRefineRequested: false,
      llmRefineApplied: false,
      llmRefineProvider: null,
      llmRefineNotes: [],
      llmRefineGuardrailFlags: [],
      llmStatus: null,
      llmDebug: null,
      variants: [
        {
          id: "primary",
          label: "Основной",
          description: "Короткий ответ.",
          text: "Да, посмотрю сейчас.",
        },
      ],
    },
  };
}

function buildWritableWorkspaceStatus(): WorkspaceStatusPayload {
  return {
    source: "new",
    requestedBackend: "new",
    effectiveBackend: "new",
    degraded: false,
    degradedReason: null,
    syncTrigger: "runtime_poll",
    updatedNow: true,
    syncError: null,
    lastUpdatedAt: "2026-04-23T09:05:02.000Z",
    lastSuccessAt: "2026-04-23T09:05:02.000Z",
    lastError: null,
    lastErrorAt: null,
    availability: {
      workspaceAvailable: true,
      historyReadable: true,
      runtimeReadable: true,
      legacyWorkspaceAvailable: false,
      replyContextAvailable: true,
      sendAvailable: true,
      autopilotAvailable: true,
      canLoadOlder: true,
    },
    messageSource: {
      backend: "new_runtime",
      chatKey: "telegram:-100777",
      runtimeChatId: -100777,
      localChatId: null,
      oldestMessageKey: "telegram:-100777:41",
      newestMessageKey: "telegram:-100777:41",
      oldestRuntimeMessageId: 41,
      newestRuntimeMessageId: 41,
    },
    route: {},
    sendPath: { effective: "new" },
    sendDisabledReason: null,
  };
}
