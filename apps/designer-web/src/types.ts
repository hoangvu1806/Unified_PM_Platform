export type RunStage =
    | "requirement"
    | "specification"
    | "review_spec"
    | "components"
    | "binding"
    | "assembly"
    | "layout_check"
    | "review_final"
    | "finished"
    | "blocked"
    | "failed";

export interface Session {
    id: string;
    title: string;
    created_at: string;
    updated_at: string;
    workspace?: SessionWorkspace | null;
}

export interface SessionWorkspace {
    document_id: string;
    document_path: string;
    document_name: string;
    page_id: string;
    page_name: string;
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

export interface LayoutRule {
    mode: "block" | "flex" | "grid" | "absolute";
    direction: "row" | "column";
    gap: number;
    columns?: number;
    padding: number;
}

export interface UiNode {
    id: string;
    kind: "container" | "component" | "text" | "media" | "icon" | "graphic";
    name: string;
    content: Record<string, unknown>;
    layout?: LayoutRule;
    requirement?: {
        role: string;
        variant_intent?: string;
        required_slots: string[];
        capabilities: string[];
    };
    children: UiNode[];
}

export interface LayoutFinding {
    severity: "info" | "warning" | "error";
    category: string;
    node_ids: string[];
    evidence: string;
    correction: string;
}

export interface RunArtifacts {
    project_specification?: ProjectSpecification;
    openpencil_capability?: Record<string, unknown>;
    openpencil_checkpoint?: Record<string, unknown>;
    cohesion_review?: Record<string, unknown>;
    media_manifest?: { assets?: Record<string, unknown>[] };
    knowledge_snapshot?: { libraries?: string[]; strategy?: string };
    component_candidates: Record<string, unknown>[];
    component_bindings?: { bindings?: Record<string, unknown>[] };
    openpencil_artifact?: {
        document_id: string;
        page_id: string;
        page_name: string;
        output_file: string;
        root_node_id: string;
        created_nodes: number;
        share_url?: string;
    };
    layout_review?: {
        status: "valid" | "advisory" | "invalid";
        summary: string;
        findings: LayoutFinding[];
    };
    workspace_mutation?: Record<string, unknown>;
}

export interface UiSpecification {
    schema_version: "2.0";
    screen_name: string;
    platform: "mobile" | "tablet" | "desktop" | "responsive";
    viewport_width: number;
    viewport_height: number;
    summary: string;
    root: UiNode;
}

export interface ScreenBrief {
    id: string;
    name: string;
    purpose: string;
    platforms: string[];
    source_ui_ids?: string[];
}

export interface ProjectSpecification {
    schema_version: "3.0";
    brief: {
        product_name: string;
        product_description: string;
        platforms: string[];
        screens: ScreenBrief[];
        output_filename: string;
        style_name?: string;
        scope_confirmed: boolean;
    };
    design_context: {
        product_summary: string;
        visual_direction: string;
        style_manifest: Record<string, unknown>;
        navigation: string[];
        shared_patterns: string[];
        content_tone: string;
        responsive_strategy: string;
    };
    screens: {
        screen_id: string;
        platforms: string[];
        specification: UiSpecification;
    }[];
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
    mcp_profile?: OpenPencilProfile;
    specification?: UiSpecification;
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

export interface ConnectionSettings {
    mcpEndpoint: string;
    sourceFile: string;
    knowledgeId: "auto" | "shadcn-ui" | "taptap";
    documentId: string;
    documentPath: string;
    documentName: string;
    pageId: string;
    pageName: string;
}

export interface OpenPencilPage {
    id: string;
    name: string;
}

export interface OpenPencilDocument {
    id: string;
    name: string;
    path?: string;
    active: boolean;
    current_page_id?: string;
    current_page_name?: string;
    pages: OpenPencilPage[];
}

export interface OpenPencilProfile {
    endpoint: string;
    source_file: string;
    output_file?: string;
    target_mode: "new_file" | "existing_file";
    knowledge_id: ConnectionSettings["knowledgeId"];
}

export interface DesignSystemInfo {
    id: string;
    name: string;
    path: string;
    knowledge_id: "auto" | "shadcn-ui" | "taptap";
}
