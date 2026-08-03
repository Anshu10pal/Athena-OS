import React from "react";
import ReactDOM from "react-dom/client";
import "@fontsource/instrument-sans/400.css";
import "@fontsource/instrument-sans/500.css";
import "@fontsource/instrument-sans/600.css";
import "@fontsource/instrument-sans/700.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import App from "./App";
import "./index.css";
import { AuthProvider } from "./store/auth";
import { OrbProvider } from "./store/orb";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AuthProvider>
      <OrbProvider>
        <App />
      </OrbProvider>
    </AuthProvider>
  </React.StrictMode>
);
