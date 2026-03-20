import React from "react";
import ReactDOM from "react-dom/client";

import App from "@/App";
import { Gen3dProvider } from "@/app/gen3d-provider";
import "@/i18n";
import { ThemeProvider } from "@/hooks/use-theme";
import "@/styles.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <ThemeProvider>
      <Gen3dProvider>
        <App />
      </Gen3dProvider>
    </ThemeProvider>
  </React.StrictMode>,
);
