import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "@fontsource/dm-sans/latin-400.css";
import "@fontsource/dm-sans/latin-ext-400.css";
import "@fontsource/dm-sans/latin-500.css";
import "@fontsource/dm-sans/latin-ext-500.css";
import "@fontsource/dm-sans/latin-600.css";
import "@fontsource/dm-sans/latin-ext-600.css";
import "@fontsource/manrope/latin-700.css";
import "@fontsource/manrope/latin-ext-700.css";
import "@fontsource/manrope/latin-800.css";
import "@fontsource/manrope/latin-ext-800.css";
import "./style.css";
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
