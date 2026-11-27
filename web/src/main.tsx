import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./index.css";
import { applyTheme, getThemePref } from "./lib/theme";

applyTheme(getThemePref());
const el = document.getElementById("root");
if (!el) throw new Error("root element missing");
createRoot(el).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
