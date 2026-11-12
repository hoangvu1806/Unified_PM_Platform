import "./platform";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import LogsApp from "./LogsApp";
import "./logs.css";

createRoot(document.getElementById("root")!).render(<StrictMode><LogsApp /></StrictMode>);
