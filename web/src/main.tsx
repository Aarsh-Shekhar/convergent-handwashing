import "@fontsource-variable/nunito";
import "@fontsource-variable/inter";
import "./styles/tokens.css";
import "./styles/app.css";
import "./styles/kid.css";
import "./styles/parent.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
