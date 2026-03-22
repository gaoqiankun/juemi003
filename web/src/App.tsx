import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { ProtectedUserRoute } from "@/components/guards/protected-user-route";
import { AdminShell } from "@/components/layout/admin-shell";
import { UserShell } from "@/components/layout/user-shell";
import { ApiKeysPage } from "@/pages/api-keys-page";
import { GalleryPage } from "@/pages/gallery-page";
import { GeneratePage } from "@/pages/generate-page";
import { ModelsPage } from "@/pages/models-page";
import { SettingsPage } from "@/pages/settings-page";
import { SetupPage } from "@/pages/setup-page";
import { TasksPage } from "@/pages/tasks-page";
import { ViewerPage } from "@/pages/viewer-page";

export default function App() {
  const basename = import.meta.env.BASE_URL.endsWith("/")
    ? import.meta.env.BASE_URL.slice(0, -1)
    : import.meta.env.BASE_URL;

  return (
    <BrowserRouter
      basename={basename || "/"}
      future={{
        v7_relativeSplatPath: true,
        v7_startTransition: true,
      }}
    >
      <Routes>
        <Route element={<UserShell />}>
          <Route path="/" element={<Navigate to="/generate" replace />} />
          <Route path="/setup" element={<SetupPage />} />
          <Route element={<ProtectedUserRoute />}>
            <Route path="/generate" element={<GeneratePage />} />
            <Route path="/gallery" element={<GalleryPage />} />
            <Route path="/viewer/:taskId" element={<ViewerPage />} />
          </Route>
        </Route>

        <Route path="/admin" element={<AdminShell />}>
          <Route index element={<Navigate to="/admin/tasks" replace />} />
          <Route path="tasks" element={<TasksPage />} />
          <Route path="models" element={<ModelsPage />} />
          <Route path="api-keys" element={<ApiKeysPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/admin/tasks" replace />} />
        </Route>

        <Route path="*" element={<Navigate to="/generate" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
