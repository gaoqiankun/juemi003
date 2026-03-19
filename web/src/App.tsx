import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/app-shell";
import { DebugErrorBoundary } from "@/components/debug-error-boundary";
import { GalleryPage } from "@/pages/gallery-page";
import { ProofShotsPage } from "@/pages/proof-shots-page";
import { GeneratePage } from "@/pages/generate-page";
import { ReferenceComparePage } from "@/pages/reference-compare-page";
import { SettingsPage } from "@/pages/settings-page";

export default function App() {
  const basename = import.meta.env.BASE_URL.endsWith("/")
    ? import.meta.env.BASE_URL.slice(0, -1)
    : import.meta.env.BASE_URL;

  return (
    <BrowserRouter basename={basename || "/"}>
      <Routes>
        <Route
          path="/__compare"
          element={(
            <DebugErrorBoundary>
              <ReferenceComparePage />
            </DebugErrorBoundary>
          )}
        />
        <Route
          path="/__shots"
          element={(
            <DebugErrorBoundary>
              <ProofShotsPage />
            </DebugErrorBoundary>
          )}
        />
        <Route path="/" element={<AppShell />}>
          <Route index element={<GeneratePage />} />
          <Route path="gallery" element={<GalleryPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
