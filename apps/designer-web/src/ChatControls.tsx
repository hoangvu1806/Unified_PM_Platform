import {
    Check,
    ChevronDown,
    CircleDot,
    Cpu,
    Feather,
    Gamepad2,
    Monitor,
    MonitorSmartphone,
    Newspaper,
    Palette,
    Smartphone,
    Sparkles,
    Square,
    Tablet,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { MagneticStyleModal, STYLE_POSTERS } from "./MagneticStyleModal";

export const STARTER_PROMPTS = [
    {
        title: "Analytics Dashboard",
        prompt: "Design a modern SaaS analytics dashboard with KPI metric cards, revenue growth chart, and recent transaction list.",
        screenName: "Analytics Overview",
        platform: "desktop",
    },
    {
        title: "E-Commerce Checkout",
        prompt: "Design a streamlined 2-column e-commerce checkout page with order summary, shipping address form, and payment methods.",
        screenName: "Checkout Flow",
        platform: "responsive",
    },
    {
        title: "Mobile Authentication",
        prompt: "Design an iOS mobile login and registration screen with social sign-in (Apple, Google), biometric toggle, and clean inputs.",
        screenName: "Mobile Sign In",
        platform: "mobile",
    },
    {
        title: "Team & Billing Settings",
        prompt: "Design an account settings page with subscription plan tier switcher, team member permission table, and invoice history.",
        screenName: "Billing & Team",
        platform: "desktop",
    },
] as const;

const PLATFORMS = [
    { value: "responsive", label: "Responsive", icon: MonitorSmartphone },
    { value: "desktop", label: "Desktop", icon: Monitor },
    { value: "tablet", label: "Tablet", icon: Tablet },
    { value: "mobile", label: "Mobile", icon: Smartphone },
];

export function PlatformSelector({
    value,
    onChange,
}: {
    value: string;
    onChange: (value: string) => void;
}) {
    const [open, setOpen] = useState(false);
    const ref = useRef<HTMLDivElement>(null);
    const current =
        PLATFORMS.find((item) => item.value === value) || PLATFORMS[0];
    const Icon = current.icon;

    useEffect(() => {
        if (!open) return;
        const closeOutside = (event: MouseEvent) => {
            if (ref.current && !ref.current.contains(event.target as Node))
                setOpen(false);
        };
        const closeKey = (event: KeyboardEvent) => {
            if (event.key === "Escape") setOpen(false);
        };
        document.addEventListener("mousedown", closeOutside);
        document.addEventListener("keydown", closeKey);
        return () => {
            document.removeEventListener("mousedown", closeOutside);
            document.removeEventListener("keydown", closeKey);
        };
    }, [open]);

    return (
        <div className="custom-dropdown-container" ref={ref}>
            <button
                type="button"
                className={`composer-mini-pill dropdown-trigger ${open ? "active" : ""}`}
                onClick={() => setOpen(!open)}
                title="Select target viewport platform"
            >
                <Icon size={13} style={{ color: "var(--violet)" }} />
                <span>{current.label}</span>
                <ChevronDown
                    size={12}
                    className={`dropdown-chevron ${open ? "rotate" : ""}`}
                />
            </button>
            {open && (
                <div className="custom-dropdown-menu" role="menu">
                    {PLATFORMS.map(
                        ({ value: option, label, icon: OptionIcon }) => (
                            <button
                                key={option}
                                type="button"
                                className={`custom-dropdown-item ${option === value ? "selected" : ""}`}
                                onClick={() => {
                                    onChange(option);
                                    setOpen(false);
                                }}
                                role="menuitem"
                            >
                                <OptionIcon size={14} />
                                <span>{label}</span>
                                {option === value && (
                                    <Check size={13} className="check-icon" />
                                )}
                            </button>
                        ),
                    )}
                </div>
            )}
        </div>
    );
}

export const STYLES = [
    {
        value: "minimal",
        label: "Minimal Clean",
        icon: Feather,
        badge: "Swiss",
        desc: "Clean, spacious, high legibility",
    },
    {
        value: "glass",
        label: "Glassmorphism",
        icon: Sparkles,
        badge: "Glass",
        desc: "Translucent frosted depth",
    },
    {
        value: "brutalist",
        label: "Neo-Brutalist",
        icon: Square,
        badge: "Bold",
        desc: "Thick borders & electric pastels",
    },
    {
        value: "neomorphic",
        label: "Soft UI",
        icon: CircleDot,
        badge: "Neomorph",
        desc: "Dual shadows, extruded feel",
    },
    {
        value: "editorial",
        label: "Editorial",
        icon: Newspaper,
        badge: "Serif",
        desc: "Magazine publication grid",
    },
    {
        value: "retro",
        label: "Retro Y2K",
        icon: Gamepad2,
        badge: "90s",
        desc: "90s OS windows & bevels",
    },
    {
        value: "futuristic",
        label: "Cyber HUD",
        icon: Cpu,
        badge: "Sci-Fi",
        desc: "Obsidian dark mode & neon glow",
    },
] as const;

export function StyleSelector({
    value,
    onChange,
}: {
    value: string;
    onChange: (value: string) => void;
}) {
    const [open, setOpen] = useState(false);
    const current =
        STYLE_POSTERS.find((item) => item.value === value) || STYLE_POSTERS[0];
    const Icon = current.icon;

    return (
        <>
            <button
                type="button"
                className={`composer-mini-pill dropdown-trigger style-trigger-pill ${open ? "active" : ""}`}
                onClick={() => setOpen(true)}
                title="Browse visual styles gallery (Magnetic Carousel)"
            >
                <Palette size={13} style={{ color: "var(--violet)" }} />
                <span>Style: {current.label}</span>
                <Sparkles
                    size={11}
                    style={{
                        opacity: 0.7,
                        color: "var(--violet)",
                        marginLeft: 2,
                    }}
                />
            </button>

            {open && (
                <MagneticStyleModal
                    styles={STYLE_POSTERS}
                    selectedStyle={value}
                    onSelect={(selectedVal) => {
                        onChange(selectedVal);
                    }}
                    onClose={() => setOpen(false)}
                />
            )}
        </>
    );
}
