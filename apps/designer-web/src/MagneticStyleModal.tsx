import React, { useEffect, useRef, useState } from "react";
import {
    Check,
    CircleDot,
    Cpu,
    Feather,
    Gamepad2,
    Newspaper,
    Sparkles,
    Square,
    X,
} from "lucide-react";

export interface StyleOption {
    value: string;
    label: string;
    tagline: string;
    category: string;
    number: string;
    icon: React.ComponentType<{
        size?: number;
        style?: React.CSSProperties;
        className?: string;
    }>;
    primaryColor: string;
    accentColor: string;
    tags: string[];
    description: string;
    posterTheme: {
        bg: string;
        border: string;
        textColor: string;
        accentText: string;
        cardBg: string;
        glow: string;
    };
    renderGraphic: () => React.ReactNode;
}

export const STYLE_POSTERS: StyleOption[] = [
    {
        value: "minimal",
        label: "Minimal Clean",
        tagline: "Swiss Modernism & Pure Whitespace",
        category: "SWISS MODERN",
        number: "01",
        icon: Feather,
        primaryColor: "#2563EB",
        accentColor: "#0F172A",
        tags: ["Helvetica 1957", "Hairline Grid", "High Legibility"],
        description:
            "Clean, spacious, high typography legibility, subtle hairlines, and zero visual noise. Inspired by Josef Müller-Brockmann and Dieter Rams.",
        posterTheme: {
            bg: "linear-gradient(165deg, #0f172a 0%, #1e293b 100%)",
            border: "1px solid rgba(255, 255, 255, 0.12)",
            textColor: "#f8fafc",
            accentText: "#60a5fa",
            cardBg: "rgba(255, 255, 255, 0.04)",
            glow: "0 8px 32px rgba(37, 99, 235, 0.2)",
        },
        renderGraphic: () => (
            <div className="poster-canvas poster-minimal">
                <div className="swiss-grid-lines" />
                <div className="poster-big-type">Aa</div>
                <div className="swiss-badge">1957 / SWISS</div>
                <div className="swiss-bar" />
            </div>
        ),
    },
    {
        value: "glass",
        label: "Glassmorphism",
        tagline: "Translucency & Frosted Aeroglass",
        category: "AERO GLASS",
        number: "02",
        icon: Sparkles,
        primaryColor: "#8B5CF6",
        accentColor: "#38BDF8",
        tags: ["Frosted Blur", "Specular Glow", "Multi-Layer Depth"],
        description:
            "Translucency, frosted glass layers, ambient specular glows, and multi-level depth. Creates a tangible, floating optical illusion.",
        posterTheme: {
            bg: "linear-gradient(165deg, #090d16 0%, #180d2a 100%)",
            border: "1px solid rgba(168, 85, 247, 0.25)",
            textColor: "#ffffff",
            accentText: "#c084fc",
            cardBg: "rgba(255, 255, 255, 0.08)",
            glow: "0 8px 36px rgba(139, 92, 246, 0.35)",
        },
        renderGraphic: () => (
            <div className="poster-canvas poster-glass">
                <div className="glass-orb orb-1" />
                <div className="glass-orb orb-2" />
                <div className="glass-floating-card">
                    <span className="glass-chip">FROSTED 16PX</span>
                    <div className="glass-bar" />
                </div>
            </div>
        ),
    },
    {
        value: "brutalist",
        label: "Neo-Brutalism",
        tagline: "Bold Black Borders & Electric Pastels",
        category: "NEO BRUTAL",
        number: "03",
        icon: Square,
        primaryColor: "#FACC15",
        accentColor: "#000000",
        tags: ["Hard 0-Blur Shadow", "Thick 3px Stroke", "Saturated Coral"],
        description:
            "Thick solid black borders, hard offset 0-blur shadows, electric saturated pastels, stickers, and oversized expressive typography.",
        posterTheme: {
            bg: "linear-gradient(165deg, #fef08a 0%, #fde047 100%)",
            border: "3px solid #000000",
            textColor: "#000000",
            accentText: "#dc2626",
            cardBg: "#ffffff",
            glow: "6px 6px 0px #000000",
        },
        renderGraphic: () => (
            <div className="poster-canvas poster-brutalist">
                <div className="brutal-tag">★ 100% RAW</div>
                <div className="brutal-box">
                    <span>BOLD</span>
                </div>
                <div className="brutal-sticker">NEW // 03</div>
            </div>
        ),
    },
    {
        value: "neomorphic",
        label: "Soft UI",
        tagline: "Dual-Shadow Extrusion & Pillowy Depth",
        category: "SOFT SURFACE",
        number: "04",
        icon: CircleDot,
        primaryColor: "#64748B",
        accentColor: "#38BDF8",
        tags: ["Claymorphism", "Dual Shadows", "Monochromatic"],
        description:
            "Monochromatic surface extrusion, dual complementary shadows (specular highlight + ambient drop), yielding tactile, touchable softness.",
        posterTheme: {
            bg: "linear-gradient(165deg, #1e2430 0%, #171c26 100%)",
            border: "1px solid rgba(255, 255, 255, 0.07)",
            textColor: "#e2e8f0",
            accentText: "#38bdf8",
            cardBg: "#1b212c",
            glow: "0 8px 30px rgba(0, 0, 0, 0.4)",
        },
        renderGraphic: () => (
            <div className="poster-canvas poster-neomorph">
                <div className="neomorph-circle">
                    <div className="neomorph-inner" />
                </div>
                <div className="neomorph-pill" />
            </div>
        ),
    },
    {
        value: "editorial",
        label: "Editorial",
        tagline: "Magazine Typography & Publication Grid",
        category: "VOGUE PRINT",
        number: "05",
        icon: Newspaper,
        primaryColor: "#C2410C",
        accentColor: "#F59E0B",
        tags: ["High-Contrast Serif", "Column Rules", "Warm Paper"],
        description:
            "Magazine-grade high-contrast serif typography, asymmetric publication grid, column rules, and warm paper tones. Chic, refined, editorial.",
        posterTheme: {
            bg: "linear-gradient(165deg, #1c1917 0%, #292524 100%)",
            border: "1px solid rgba(245, 158, 11, 0.2)",
            textColor: "#fafaf9",
            accentText: "#fbbf24",
            cardBg: "rgba(255, 255, 255, 0.04)",
            glow: "0 8px 32px rgba(194, 65, 12, 0.25)",
        },
        renderGraphic: () => (
            <div className="poster-canvas poster-editorial">
                <div className="editorial-masthead">CHRONICLE</div>
                <div className="editorial-rule" />
                <div className="editorial-italic">Vol. 24 — Issue No. 05</div>
            </div>
        ),
    },
    {
        value: "retro",
        label: "Retro Y2K",
        tagline: "90s Windows Chrome & Arcade Nostalgia",
        category: "ARCADE 95",
        number: "06",
        icon: Gamepad2,
        primaryColor: "#008080",
        accentColor: "#E11D48",
        tags: ["3D Bevels", "Pixel Icons", "Desktop OS 95"],
        description:
            "Classic window chrome title bars, 3D beveled push buttons, pixel typography, and nostalgic late-90s early-2000s desktop nostalgia.",
        posterTheme: {
            bg: "linear-gradient(165deg, #0f172a 0%, #004d40 100%)",
            border: "2px solid #008080",
            textColor: "#f8fafc",
            accentText: "#2dd4bf",
            cardBg: "#005a5a",
            glow: "0 8px 30px rgba(0, 128, 128, 0.4)",
        },
        renderGraphic: () => (
            <div className="poster-canvas poster-retro">
                <div className="retro-titlebar">
                    <span>SYS_95.EXE</span>
                    <div className="retro-btns">
                        <span>_</span>
                        <span>□</span>
                        <span>✕</span>
                    </div>
                </div>
                <div className="retro-bevel-btn">CLICK ME</div>
            </div>
        ),
    },
    {
        value: "futuristic",
        label: "Cyber HUD",
        tagline: "Obsidian Dark Mode & Neon Telemetry",
        category: "CYBERPUNK",
        number: "07",
        icon: Cpu,
        primaryColor: "#00F0FF",
        accentColor: "#A855F7",
        tags: ["Sci-Fi HUD", "Luminous Cyan", "Telemetry Crosshairs"],
        description:
            "Deep obsidian dark mode, luminous neon cyan/violet glow, technical wireframe grids, and aerospace HUD telemetry readouts.",
        posterTheme: {
            bg: "linear-gradient(165deg, #030712 0%, #080f25 100%)",
            border: "1px solid rgba(0, 240, 255, 0.3)",
            textColor: "#f8fafc",
            accentText: "#00f0ff",
            cardBg: "rgba(0, 240, 255, 0.05)",
            glow: "0 8px 36px rgba(0, 240, 255, 0.3)",
        },
        renderGraphic: () => (
            <div className="poster-canvas poster-cyber">
                <div className="cyber-hud-coords">[+ 37.77 // -122.41]</div>
                <div className="cyber-crosshair" />
                <div className="cyber-hud-badge">HUD // SEC 07</div>
            </div>
        ),
    },
];

interface MagneticCarouselProps {
    styles: StyleOption[];
    selectedStyle: string;
    onSelect: (value: string) => void;
    onClose: () => void;
    collapsedWidth?: number;
    hoverWidth?: number;
    collapsedHeight?: number;
    hoverHeight?: number;
    openWidth?: number;
    openHeight?: number;
    gap?: number;
    influence?: number;
}

export function MagneticStyleModal({
    styles = STYLE_POSTERS,
    selectedStyle,
    onSelect,
    onClose,
    collapsedWidth = 96,
    hoverWidth = 300,
    collapsedHeight = 440,
    hoverHeight = 570,
    openWidth = 600,
    openHeight = 560,
    gap = 12,
    influence = 130,
}: MagneticCarouselProps) {
    const count = styles.length;
    const containerRef = useRef<HTMLDivElement>(null);
    const [factors, setFactors] = useState<number[]>(() => styles.map(() => 0));
    const [open, setOpen] = useState<number | null>(null);
    const [closing, setClosing] = useState(false);

    const targetRef = useRef<number[]>(styles.map(() => 0));
    const curRef = useRef<number[]>(styles.map(() => 0));
    const loopRef = useRef(0);
    const closeTimer = useRef<any>(0);

    // Close on Escape
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            if (e.key === "Escape") {
                if (open !== null) close();
                else onClose();
            }
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [open, onClose]);

    useEffect(() => {
        targetRef.current = styles.map(() => 0);
        curRef.current = styles.map(() => 0);
        setFactors(styles.map(() => 0));
    }, [count]);

    useEffect(() => {
        return () => {
            cancelAnimationFrame(loopRef.current);
            clearTimeout(closeTimer.current);
        };
    }, []);

    const startLoop = () => {
        if (loopRef.current) return;
        const step = () => {
            const tgt = targetRef.current;
            const cur = curRef.current;
            let moving = false;
            for (let i = 0; i < cur.length; i++) {
                const d = (tgt[i] ?? 0) - cur[i];
                if (Math.abs(d) > 0.001) {
                    cur[i] += d * 0.2; // lerp toward target
                    moving = true;
                } else {
                    cur[i] = tgt[i] ?? 0;
                }
            }
            setFactors([...cur]);
            loopRef.current = moving ? requestAnimationFrame(step) : 0;
        };
        loopRef.current = requestAnimationFrame(step);
    };

    const setTargetFromCursor = (clientX: number) => {
        const el = containerRef.current;
        if (!el) return;
        const cardEls = Array.from(
            el.querySelectorAll<HTMLDivElement>(".magnetic-poster-card"),
        );
        if (cardEls.length === 0) return;

        let closestIdx = -1;
        let minCenterDist = Infinity;

        cardEls.forEach((card, i) => {
            const r = card.getBoundingClientRect();
            if (clientX >= r.left && clientX <= r.right) {
                closestIdx = i;
            }
            const center = r.left + r.width / 2;
            const dist = Math.abs(clientX - center);
            if (dist < minCenterDist) {
                minCenterDist = dist;
                if (closestIdx === -1) closestIdx = i;
            }
        });

        if (closestIdx === -1) return;

        const hoveredRect = cardEls[closestIdx].getBoundingClientRect();
        const hoveredCenter = hoveredRect.left + hoveredRect.width / 2;
        const halfW = hoveredRect.width / 2;
        const offsetRatio = halfW > 0 ? (clientX - hoveredCenter) / halfW : 0;

        targetRef.current = styles.map((_, i) => {
            if (i === closestIdx) return 1;
            if (i === closestIdx - 1 && offsetRatio < 0) {
                return Math.abs(offsetRatio) * 0.08;
            }
            if (i === closestIdx + 1 && offsetRatio > 0) {
                return offsetRatio * 0.08;
            }
            return 0;
        });
        startLoop();
    };

    const onMove = (e: React.MouseEvent) => {
        if (open !== null) return;
        setTargetFromCursor(e.clientX);
    };

    const onLeave = () => {
        if (open !== null) return;
        targetRef.current = styles.map(() => 0);
        startLoop();
    };

    const close = () => {
        targetRef.current = styles.map(() => 0);
        curRef.current = styles.map(() => 0);
        setFactors(styles.map(() => 0));
        setClosing(true);
        clearTimeout(closeTimer.current);
        closeTimer.current = setTimeout(() => setClosing(false), 300);
        setOpen(null);
    };

    const sizeFor = (i: number) => {
        if (open !== null) {
            return i === open
                ? { width: openWidth, height: openHeight }
                : { width: collapsedWidth, height: collapsedHeight };
        }
        const f = factors[i] ?? 0;
        return {
            width: collapsedWidth + (hoverWidth - collapsedWidth) * f,
            height: collapsedHeight + (hoverHeight - collapsedHeight) * f,
        };
    };

    const openEase =
        "width 0.35s cubic-bezier(0.44, 0, 0.56, 1), height 0.35s cubic-bezier(0.44, 0, 0.56, 1), filter 0.35s ease, opacity 0.35s ease";
    const barTransition = open !== null || closing ? openEase : "none";

    return (
        <div className="magnetic-modal-overlay" onClick={onClose}>
            {/* Minimal Close Button */}
            <button
                type="button"
                className="modal-close-btn fixed-close-btn"
                onClick={onClose}
                title="Close (Esc)"
            >
                <X size={20} />
            </button>

            {/* Magnetic carousel viewport */}
            <div
                className="magnetic-carousel-viewport"
                onClick={(e) => e.stopPropagation()}
            >
                <div
                    ref={containerRef}
                    className="magnetic-carousel-track"
                    style={{ gap }}
                    onMouseMove={onMove}
                    onMouseLeave={onLeave}
                >
                    {/* Transparent backdrop when a card is expanded */}
                    <div
                        className="expanded-backdrop"
                        style={{
                            pointerEvents: open !== null ? "auto" : "none",
                        }}
                        onClick={close}
                    />

                    {styles.map((st, i) => {
                        const { width, height } = sizeFor(i);
                        const isExpanded = open === i;
                        const isSelected = selectedStyle === st.value;
                        const blurred = open !== null && !isExpanded;
                        const Icon = st.icon;

                        return (
                            <div
                                key={st.value}
                                className={`magnetic-poster-card ${isSelected ? "selected-style" : ""} ${isExpanded ? "expanded" : ""}`}
                                onClick={() => {
                                    if (open === i) close();
                                    else setOpen(i);
                                }}
                                style={{
                                    width,
                                    height,
                                    borderRadius: 0,
                                    transition: barTransition,
                                    zIndex: isExpanded ? 20 : 2,
                                    filter: blurred ? "blur(3px)" : "none",
                                    opacity: blurred ? 0.45 : 1,
                                    background: st.posterTheme.bg,
                                    border: isSelected
                                        ? "2px solid var(--violet)"
                                        : st.posterTheme.border,
                                    boxShadow: isExpanded
                                        ? "0 24px 60px rgba(0,0,0,0.7), " +
                                          st.posterTheme.glow
                                        : st.posterTheme.glow,
                                    color: st.posterTheme.textColor,
                                }}
                            >
                                {/* Top Tag / Number */}
                                <div className="poster-header-row">
                                    <span
                                        className="poster-number"
                                        style={{
                                            color: st.posterTheme.accentText,
                                        }}
                                    >
                                        {st.number}
                                    </span>
                                    {isSelected && (
                                        <span className="poster-active-chip">
                                            <Check size={11} />
                                            <span>ACTIVE</span>
                                        </span>
                                    )}
                                </div>

                                {/* Graphic art */}
                                <div className="poster-graphic-wrapper">
                                    {st.renderGraphic()}
                                </div>

                                {/* Collapsed bar footer */}
                                {!isExpanded && (
                                    <div className="poster-footer-collapsed">
                                        <div className="icon-badge">
                                            <Icon
                                                size={14}
                                                style={{
                                                    color: st.posterTheme
                                                        .accentText,
                                                }}
                                            />
                                        </div>
                                        <div className="poster-collapsed-title">
                                            <strong>{st.label}</strong>
                                            <span>{st.category}</span>
                                        </div>
                                    </div>
                                )}

                                {/* Expanded full view */}
                                {isExpanded && (
                                    <div className="poster-expanded-details">
                                        <div className="expanded-title-row">
                                            <div>
                                                <span
                                                    className="expanded-category"
                                                    style={{
                                                        color: st.posterTheme
                                                            .accentText,
                                                    }}
                                                >
                                                    {st.category} ARCHETYPE
                                                </span>
                                                <h3>{st.label}</h3>
                                                <p className="expanded-tagline">
                                                    {st.tagline}
                                                </p>
                                            </div>
                                            <div
                                                className="expanded-icon-pill"
                                                style={{
                                                    background:
                                                        st.posterTheme.cardBg,
                                                    border: st.posterTheme
                                                        .border,
                                                }}
                                            >
                                                <Icon
                                                    size={22}
                                                    style={{
                                                        color: st.posterTheme
                                                            .accentText,
                                                    }}
                                                />
                                            </div>
                                        </div>

                                        <p className="expanded-desc">
                                            {st.description}
                                        </p>

                                        {/* Tags */}
                                        <div className="expanded-tags">
                                            {st.tags.map((tag) => (
                                                <span
                                                    key={tag}
                                                    className="expanded-tag-chip"
                                                    style={{
                                                        background:
                                                            st.posterTheme
                                                                .cardBg,
                                                        border: st.posterTheme
                                                            .border,
                                                        color: st.posterTheme
                                                            .textColor,
                                                    }}
                                                >
                                                    {tag}
                                                </span>
                                            ))}
                                        </div>

                                        {/* Action buttons */}
                                        <div className="expanded-actions">
                                            <button
                                                type="button"
                                                className="apply-style-btn"
                                                style={{
                                                    background: isSelected
                                                        ? "var(--mint)"
                                                        : st.posterTheme
                                                              .accentText,
                                                    color:
                                                        st.value ===
                                                            "brutalist" ||
                                                        st.value ===
                                                            "minimal" ||
                                                        st.value === "editorial"
                                                            ? "#000000"
                                                            : "#ffffff",
                                                }}
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    onSelect(st.value);
                                                    onClose();
                                                }}
                                            >
                                                {isSelected ? (
                                                    <>
                                                        <Check size={16} />
                                                        <span>
                                                            Đang Sử Dụng
                                                        </span>
                                                    </>
                                                ) : (
                                                    <span>
                                                        Áp Dụng Phong Cách Này
                                                    </span>
                                                )}
                                            </button>
                                        </div>
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            </div>
        </div>
    );
}
