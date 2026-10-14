import { api } from "./api";
import type { WorkflowEvent } from "./types";

const EVENT_TYPES = [
  "run.created", "run.finished", "run.failed", "run.cancelled", "stage.changed",
  "assistant.message", "specification.ready", "review.required", "review.accepted",
  "review.changes_requested", "components.discovered", "bindings.ready",
  "openpencil.checkpoint", "openpencil.assembled", "workspace.updated",
  "workspace.inspecting", "workspace.page_updated", "component.batch_resolved",
  "layout.checked", "action.required", "design.tool", "run.retrying",
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
