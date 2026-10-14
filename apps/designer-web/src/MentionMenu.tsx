import { BookOpen, FileJson, Layers } from "lucide-react";
import { KIND_LABEL, type ProjectFile, type ProjectFileKind, initials } from "./projectFiles";

const KIND_ICON: Record<ProjectFileKind, typeof FileJson> = {
    ba_package: FileJson,
    designer_output: Layers,
    wiki_source: BookOpen,
};

/** "@" picker shown above the composer, like file mentions in IDE agents. */
export function MentionMenu({
    files,
    activeIndex,
    query,
    onPick,
    onHover,
}: {
    files: ProjectFile[];
    activeIndex: number;
    query: string;
    onPick: (file: ProjectFile) => void;
    onHover: (index: number) => void;
}) {
    return (
        <div className="mention-menu" role="listbox" aria-label="Files dự án">
            <div className="mention-head">
                Files dự án{query ? <span> · “{query}”</span> : null}
                <span className="mention-keys">↑↓ chọn · Enter đính kèm · Esc đóng</span>
            </div>
            {files.length === 0 ? (
                <div className="mention-empty">Không có file nào khớp.</div>
            ) : (
                files.map((file, index) => {
                    const Icon = KIND_ICON[file.kind];
                    return (
                        <button
                            key={`${file.kind}:${file.id}`}
                            type="button"
                            role="option"
                            aria-selected={index === activeIndex}
                            className={`mention-item ${index === activeIndex ? "active" : ""}`}
                            onMouseDown={(e) => {
                                e.preventDefault(); // keep focus in the textarea
                                onPick(file);
                            }}
                            onMouseEnter={() => onHover(index)}
                        >
                            <Icon size={15} className={`mention-icon kind-${file.kind}`} />
                            <span className="mention-name">{file.title}</span>
                            <span className="mention-kind">{KIND_LABEL[file.kind]}</span>
                            <span className="mention-by" title={file.created_by_name ?? ""}>
                                {initials(file.created_by_name)}
                            </span>
                        </button>
                    );
                })
            )}
        </div>
    );
}
