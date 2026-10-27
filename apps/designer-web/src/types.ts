export type RunStage =
    | "requirement"
    | "specification"
    | "review_spec"
    | "assembly"
    | "review_final"
    | "finished"
    | "blocked"
    | "failed";

export interface Session {
    id: string;
    title: string;
    created_at: string;
    updated_at: string;
    design_system_id?: string | null;
    // Platform: project and provenance (BA handoff -> source_ref = BA feature id)
    project_id?: string | null;
    created_by?: string | null;
    source?: string | null;
    source_ref?: string | null;
    source_artifact_id?: string | null;
}

export interface ParsedAttachment {
    name: string;
    kind: "json" | "text" | "image" | "bpmn";
    markdown: string;
    truncated: boolean;
    asset?: ExactAsset;
}

export interface ExactAsset {
    id: string;
    name: string;
    mime_type: string;
    usage: "exact";
    width?: number;
    height?: number;
    aspect_ratio?: number;
    visual_role?: string;
    dominant_colors?: string[];
    background_type?: string;
    recommended_fit?: "contain" | "cover";
    recommended_placement?: string;
    placement_reason?: string;
    safe_padding_percent?: number;
}

export interface ScreenSpec {
    id: string;
    name: string;
    platform: "mobile" | "tablet" | "desktop";
    purpose?: string;
    layout?: string;
    sections?: string[];
    states?: string[];
    data?: string[];
    navigation?: string[];
    source_ui_ids?: string[];
}

/** UI specification of the HTML designer (schema "html-1"). */
export interface HtmlSpec {
    schema_version: "html-1";
    style_direction?: string;
    screens: ScreenSpec[];
}

export interface Screen {
    id: string;
    name: string;
    platform: "mobile" | "tablet" | "desktop" | "responsive";
    width: number;
    position: number;
    version: number;
    updated_at: string;
    updated_by?: string | null;
    run_id?: string | null;
    html?: string | null;
}

export interface ScreenVersion {
    version: number;
    created_at: string;
    updated_by?: string | null;
    note?: string | null;
}

export interface TokenUsage {
    calls?: number;
    prompt_tokens?: number;
    output_tokens?: number;
    steps?: { step: string; calls?: number; prompt_tokens?: number; output_tokens?: number }[];
}

export interface RunArtifacts {
    token_usage?: TokenUsage;
    exact_assets?: ExactAsset[];
    [key: string]: unknown;
}

export interface Run {
    id: string;
    session_id: string;
    revision: number;
    prompt: string;
    screen_name: string;
    platform: string;
    style_name?: string;
    stage: RunStage;
    status: string;
    intent?: "chat" | "clarify_design" | "start_design" | "gather" | "design";
    assistant_message?: string;
    library_ids: string[];
    specification?: HtmlSpec | null;
    error?: {
        code: string;
        detail: string;
        retryable?: boolean;
        action?: string;
        stage?: RunStage;
    };
    created_at: string;
    updated_at: string;
}

export interface DesignStyleOption {
    key: string;
    name: string;
    label: string;
    tagline: string;
    badge: string;
}

export const AVAILABLE_STYLES: DesignStyleOption[] = [
    {
        key: "minimal",
        name: "Minimal",
        label: "Swiss Clean",
        tagline: "High contrast, spacious, hairline borders",
        badge: "Clean",
    },
    {
        key: "glass",
        name: "Glass",
        label: "Glassmorphism",
        tagline: "Translucency, blur, specular highlights",
        badge: "Glass",
    },
    {
        key: "brutalist",
        name: "Brutalist",
        label: "Neo-Brutalism",
        tagline: "Thick black strokes, bold vivid pastels",
        badge: "Bold",
    },
    {
        key: "neomorphic",
        name: "Neomorphic",
        label: "Soft UI",
        tagline: "Dual shadows, smooth extruded surfaces",
        badge: "Soft",
    },
    {
        key: "editorial",
        name: "Editorial",
        label: "Editorial",
        tagline: "Magazine typography, asymmetric columns",
        badge: "Serif",
    },
    {
        key: "retro",
        name: "Retro",
        label: "Retro OS",
        tagline: "Classic window chrome, 90s push buttons",
        badge: "Y2K",
    },
    {
        key: "futuristic",
        name: "Futuristic",
        label: "Cyber HUD",
        tagline: "Obsidian dark mode, luminous neon cyan",
        badge: "HUD",
    },
];

export interface WorkflowEvent {
    id: string;
    run_id: string;
    revision: number;
    sequence: number;
    type: string;
    time: string;
    payload: Record<string, unknown>;
}

export interface DesignSystemInfo {
    id: string;
    name: string;
    project_id?: string | null;
    status: "importing" | "ready" | "failed";
    error?: string | null;
    source_name?: string | null;
    created_at?: string | null;
    summary: { components?: number; tokens?: Record<string, unknown> };
}
