import { Check, Circle, Loader2, Sparkles, X } from "lucide-react";
import type { RunStage } from "./types";

interface StageInfo {
  id: RunStage;
  label: string;
  description: string;
}

const projectStages: StageInfo[] = [
  { id: "requirement", label: "Request", description: "Requirement intake" },
  { id: "specification", label: "UI Spec", description: "Semantic UI structure" },
  { id: "review_spec", label: "Review", description: "Specification gate" },
  { id: "components", label: "Components", description: "Library mapping" },
  { id: "binding", label: "Bind", description: "Content & state binding" },
  { id: "assembly", label: "Build", description: "OpenPencil canvas assembly" },
  { id: "layout_check", label: "Layout", description: "Visual & layout validation" },
  { id: "review_final", label: "Final", description: "Human approval gate" },
];

const workspaceStages: StageInfo[] = [
  { id: "requirement", label: "Understand", description: "Interpret the follow-up request" },
  { id: "assembly", label: "Create / Edit", description: "Inspect, plan, and apply changes with OpenPencil" },
  { id: "review_final", label: "Verify", description: "Refine, verify, and save the workspace" },
];

export function BuildRail({
  stage,
  status,
  mode = "project",
}: {
  stage?: RunStage;
  status?: string;
  mode?: "project" | "workspace";
}) {
  const stages = mode === "workspace" ? workspaceStages : projectStages;
  const activeIndex = stages.findIndex((item) => item.id === stage);
    const isFinished = stage === "finished";
    const isFailed = status === "failed" || status === "blocked";

  return (
    <div className="build-rail" role="region" aria-label="Workflow progress">
      {stages.map((item, index) => {
        const isDone = isFinished || (activeIndex > -1 && activeIndex > index);
        const isActive = activeIndex === index;
        const isRunning = isActive && (status === "running" || status === "queued");
        const isNextDone = isFinished || (activeIndex > -1 && activeIndex > index);

        return (
          <div
            className={`build-step ${isDone ? "done" : ""} ${isActive ? "active" : ""} ${isRunning ? "running" : ""} ${isActive && isFailed ? "failed" : ""}`}
            key={item.id}
            title={`${item.label}: ${item.description}`}
          >
            <div className="step-badge">
              <span className="step-icon">
                {isActive && isFailed ? (
                  <X size={13} strokeWidth={2.5} />
                ) : isDone ? (
                  <Check size={13} strokeWidth={2.5} />
                ) : isRunning ? (
                  <Loader2 size={13} strokeWidth={2.5} />
                ) : isActive ? (
                  <Sparkles size={12} strokeWidth={2.5} />
                ) : (
                  <Circle size={8} />
                )}
              </span>
              <span className="step-label">{item.label}</span>
            </div>
            {index < stages.length - 1 && (
              <div
                className={`step-connector ${isNextDone ? "connector-done" : ""}`}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
