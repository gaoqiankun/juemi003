import React from "react";
import ReactDOM from "react-dom/client";
import { Toaster } from "sonner";

import App from "@/App";
import { Gen3dProvider } from "@/app/gen3d-provider";
import "@/styles.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <Gen3dProvider>
      <App />
      <Toaster
        theme="dark"
        richColors
        position="top-right"
        toastOptions={{
          classNames: {
            toast: "border border-white/10 bg-[rgba(7,11,22,0.96)] text-white shadow-[0_25px_80px_rgba(0,0,0,0.45)]",
            description: "text-slate-300",
          },
        }}
      />
    </Gen3dProvider>
  </React.StrictMode>,
);
