import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ReplyPanel } from "@/components/system/ReplyPanel";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { ReplyPreviewPayload } from "@/lib/types";

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

    expect(screen.getByText("Astra Reply")).toBeInTheDocument();
    expect(screen.getByText("Фокус ответа")).toBeInTheDocument();
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
                label: "Rejected by guardrails",
                provider: "openai_compatible",
                detail: "Сработали guardrails: слишком_литературно. Сохранён deterministic baseline.",
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
                  detail: "Сработали guardrails: слишком_литературно. Сохранён deterministic baseline.",
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
          workflowState={null}
          onRefresh={vi.fn()}
          onCopy={vi.fn()}
          onUseDraft={vi.fn()}
          onMarkSent={vi.fn()}
          onClearDraft={vi.fn()}
        />
      </TooltipProvider>,
    );

    expect(screen.getByText("Debug / details")).toBeInTheDocument();
    expect(screen.queryByText("Raw LLM candidate")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Debug \/ details/i }));

    expect(screen.getByText("Raw LLM candidate")).toBeInTheDocument();
    expect(screen.getAllByText(/слишком_литературно/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/deterministic baseline/i).length).toBeGreaterThan(0);
  });
});
