import { api } from "./api";
import type { WorkflowEvent } from "./types";

const EVENT_TYPES = [
  "run.created", "run.finished", "run.failed", "run.cancelled", "stage.changed",
  "assistant.message", "specification.ready", "review.required", "review.accepted",
  "review.changes_requested", "review.recorded", "action.required", "run.retrying",
  "screen.started", "screen.saved", "screen.finished", "screen.warning", "llm.usage",
];

export function openRunStream(runId: string, onEvent: (event: WorkflowEvent) => void) {
  const source = new EventSource(api.eventUrl(runId));
  for (const type of EVENT_TYPES) {
    source.addEventListener(type, (raw) => {
      onEvent(JSON.parse((raw as MessageEvent).data) as WorkflowEvent);
    });
  }
  return source;
}
