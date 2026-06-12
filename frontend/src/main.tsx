import React from "react";
import ReactDOM from "react-dom/client";
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
