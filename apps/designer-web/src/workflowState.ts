import type { Run, RunStage, WorkflowEvent } from "./types";

const WORKFLOW_STAGES = new Set<RunStage>([
    "requirement",
    "specification",
    "review_spec",
    "components",
    "binding",
    "assembly",
    "layout_check",
    "review_final",
    "finished",
]);

export function sessionWorkflowState(
    activeRun: Run | undefined,
    runs: Run[],
    events: WorkflowEvent[],
) {
    const run =
        activeRun ?? runs.find((item) => item.intent === "design") ?? runs[0];
    if (!run) return undefined;

    let stage = WORKFLOW_STAGES.has(run.stage) ? run.stage : run.error?.stage;
    if (
        (!stage || stage === "blocked" || stage === "failed") &&
        run.id === activeRun?.id
    ) {
        const latest = [...events]
            .reverse()
            .find((event) => event.type === "stage.changed");
        const eventStage = latest?.payload.stage as RunStage | undefined;
        if (eventStage && WORKFLOW_STAGES.has(eventStage)) stage = eventStage;
    }
    return { run, stage, status: run.status };
}
