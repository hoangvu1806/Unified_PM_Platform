import { Maximize2, Monitor, Smartphone, Tablet, X } from "lucide-react";
import type { CSSProperties } from "react";
import type { Run, UiNode, UiSpecification } from "./types";

export type PreviewSize = "fit" | "desktop" | "tablet" | "mobile";

function contentText(node: UiNode): string {
    for (const key of [
        "text",
        "title",
        "label",
        "description",
        "name",
        "value",
    ]) {
        const value = node.content?.[key];
        if (typeof value === "string" && value.trim()) return value.trim();
    }
    return node.name;
}

function classToken(value: unknown): string {
    return typeof value === "string"
        ? value
              .toLowerCase()
              .replace(/[^a-z0-9]+/g, "-")
              .replace(/^-|-$/g, "")
        : "";
}

function PreviewNode({ node, depth = 0 }: { node: UiNode; depth?: number }) {
    const style = node.layout
        ? ({
              display:
                  node.layout.mode === "grid"
                      ? "grid"
                      : node.layout.mode === "flex"
                        ? "flex"
                        : "block",
              flexDirection: node.layout.direction,
              gap: `${Math.min(node.layout.gap, 32)}px`,
              padding: `${Math.min(node.layout.padding, 32)}px`,
              "--preview-columns": node.layout.columns ?? 1,
          } as CSSProperties)
        : undefined;
    const text = contentText(node);

    if (node.kind === "text") {
        const textType = classToken(node.content?.text_type);
        const className = `preview-text ${textType ? `preview-text-${textType}` : ""}`;
        if (textType === "heading-1")
            return <h1 className={className}>{text}</h1>;
        if (textType === "heading-2")
            return <h2 className={className}>{text}</h2>;
        if (textType === "heading-3")
            return <h3 className={className}>{text}</h3>;
        return <p className={className}>{text}</p>;
    }
    if (node.kind === "media") {
        return (
            <div className="preview-media">
                <span>{text}</span>
            </div>
        );
    }
    const layout = node.layout
        ? `preview-layout-${node.layout.mode} preview-direction-${node.layout.direction}`
        : "";
    return (
        <div
            className={`preview-node preview-${node.kind} preview-depth-${Math.min(depth, 4)} ${layout} preview-role-${classToken(node.requirement?.role)}`}
            style={style}
        >
            {node.children?.length ? (
                node.children.map((child) => (
                    <PreviewNode
                        node={child}
                        depth={depth + 1}
                        key={child.id}
                    />
                ))
            ) : (
                <span>{text}</span>
            )}
        </div>
    );
}

export function PreviewToolbar({
    size,
    expanded,
    onSize,
    onExpand,
}: {
    size: PreviewSize;
    expanded: boolean;
    onSize: (size: PreviewSize) => void;
    onExpand: () => void;
}) {
    const options: {
        value: PreviewSize;
        label: string;
        icon: typeof Monitor;
    }[] = [
        { value: "fit", label: "Fit", icon: Maximize2 },
        { value: "desktop", label: "Desktop", icon: Monitor },
        { value: "tablet", label: "Tablet", icon: Tablet },
        { value: "mobile", label: "Mobile", icon: Smartphone },
    ];
    return (
        <div className="preview-toolbar" aria-label="Preview viewport">
            <div>
                {options.map(({ value, label, icon: Icon }) => (
                    <button
                        key={value}
                        className={size === value ? "active" : ""}
                        onClick={() => onSize(value)}
                        title={label}
                        aria-label={label}
                        type="button"
                    >
                        <Icon size={14} />
                        <span>{label}</span>
                    </button>
                ))}
            </div>
            <button
                className="preview-expand"
                onClick={onExpand}
                title={expanded ? "Close expanded preview" : "Expand preview"}
                aria-label={
                    expanded ? "Close expanded preview" : "Expand preview"
                }
                type="button"
            >
                {expanded ? <X size={16} /> : <Maximize2 size={16} />}
            </button>
        </div>
    );
}

export function PreviewCanvas({
    run,
    specification,
    size,
}: {
    run?: Run;
    specification?: UiSpecification;
    size: PreviewSize;
}) {
    const activeSpec = specification ?? run?.specification;

    return (
        <div className="preview-stage">
            <div className={`semantic-preview preview-${size}`}>
                {activeSpec ? (
                    <PreviewNode node={activeSpec.root} />
                ) : (
                    <div
                        style={{
                            padding: "40px 20px",
                            textAlign: "center",
                            color: "var(--text-muted)",
                        }}
                    >
                        <p>
                            Preview becomes available after the UI specification
                            is generated.
                        </p>
                    </div>
                )}
            </div>
        </div>
    );
}
