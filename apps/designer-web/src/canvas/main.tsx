// Design page (opened in its own tab from the Designer studio): login/project first.
import "../platform";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "../styles.css";
import "./canvas.css";
import { CanvasApp } from "./CanvasApp";

createRoot(document.getElementById("root")!).render(
    <StrictMode>
        <CanvasApp />
    </StrictMode>,
);
