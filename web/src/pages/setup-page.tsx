import type { ReactNode } from "react";
import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { KeyRound, Server } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useGen3d } from "@/app/gen3d-provider";
import { Button, Card, TextField } from "@/components/ui/primitives";
import { getDefaultBaseUrl } from "@/lib/api";

interface SetupLocationState {
  from?: string;
}

const eyebrowClassName = "font-display text-[0.6875rem] font-semibold uppercase tracking-[0.05em] text-text-muted";

export function SetupPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const { config, saveConfig } = useGen3d();
  const defaultServerUrl = getDefaultBaseUrl();
  const [apiKey, setApiKey] = useState(config.token);
  const [serverUrl, setServerUrl] = useState(config.baseUrl || defaultServerUrl);
  const [isSaving, setIsSaving] = useState(false);

  const canSubmit = apiKey.trim().length > 0 && serverUrl.trim().length > 0 && !isSaving;
  const fallbackPath = (location.state as SetupLocationState | null)?.from || "/generate";

  const handleSave = async () => {
    if (!canSubmit) {
      return;
    }

    setIsSaving(true);
    try {
      await saveConfig({
        token: apiKey,
        baseUrl: serverUrl,
      });

      navigate(fallbackPath, { replace: true });
    } catch (error) {
      setIsSaving(false);
      throw error;
    }
  };

  return (
    <div className="flex min-h-[calc(100vh-11rem)] items-center justify-center py-6">
      <Card className="w-full max-w-2xl p-6 md:p-8">
        <div className="grid gap-6">
          <div className="grid gap-3">
            <div>
              <div className={eyebrowClassName}>{t("user.shell.nav.setup")}</div>
              <h2 className="mt-1 text-3xl font-semibold tracking-[-0.04em] text-text-primary">{t("user.setup.title")}</h2>
            </div>
          </div>

          <div className="grid gap-4">
            <FieldCard label={t("user.setup.apiKeyLabel")} htmlFor="setup-api-key" descriptionIcon={<KeyRound className="h-4 w-4" />}>
              <TextField
                id="setup-api-key"
                type="password"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                placeholder={t("user.setup.apiKeyPlaceholder")}
                className="pl-10"
              />
            </FieldCard>

            <FieldCard label={t("user.setup.serverUrlLabel")} htmlFor="setup-server-url" descriptionIcon={<Server className="h-4 w-4" />}>
              <TextField
                id="setup-server-url"
                value={serverUrl}
                onChange={(event) => setServerUrl(event.target.value)}
                placeholder={defaultServerUrl}
                className="pl-10"
              />
            </FieldCard>
          </div>

          <div className="rounded-2xl border border-outline bg-surface-container-low p-4">
            <div className={eyebrowClassName}>{t("user.setup.noteLabel")}</div>
            <p className="mt-2 text-sm leading-6 text-text-secondary">{t("user.setup.helper")}</p>
          </div>

          <div className="flex items-center justify-end gap-2">
            <Button
              variant="secondary"
              className="min-w-24 justify-center"
              onClick={() => {
                if (window.history.length > 1) {
                  navigate(-1);
                  return;
                }
                navigate(fallbackPath, { replace: true });
              }}
              disabled={isSaving}
            >
              {t("user.setup.cancelButton")}
            </Button>
            <Button
              variant="primary"
              className="min-w-28 justify-center"
              onClick={() => {
                handleSave().catch(() => undefined);
              }}
              disabled={!canSubmit}
            >
              {t("user.setup.connectButton")}
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
}

function FieldCard({
  children,
  descriptionIcon,
  htmlFor,
  label,
}: {
  children: ReactNode;
  descriptionIcon: ReactNode;
  htmlFor: string;
  label: string;
}) {
  return (
    <label className="grid gap-3 rounded-2xl border border-outline bg-surface-container-low p-4" htmlFor={htmlFor}>
      <div className="flex items-center gap-2 text-sm font-medium text-text-primary">
        <span className="text-text-muted">{descriptionIcon}</span>
        <span>{label}</span>
      </div>
      <div className="relative">
        <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-muted">
          {descriptionIcon}
        </span>
        {children}
      </div>
    </label>
  );
}
