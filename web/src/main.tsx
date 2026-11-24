import "@fontsource-variable/inter";
import "@fontsource/fredoka/500.css";
import "@fontsource/fredoka/600.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./theme.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
