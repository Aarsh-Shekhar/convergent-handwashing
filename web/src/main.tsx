import "@fontsource-variable/nunito";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/controls.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
