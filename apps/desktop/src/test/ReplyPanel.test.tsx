import { render, screen } from "@testing-library/react";
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
});
