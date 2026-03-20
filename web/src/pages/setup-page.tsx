import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { KeyRound, Server } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button, Card, TextField } from "@/components/ui/primitives";
import { useSetupData } from "@/hooks/use-setup-data";
import { readUserConfig, saveUserConfig } from "@/lib/user-config";

interface SetupLocationState {
  from?: string;
}

export function SetupPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const { defaultServerUrl } = useSetupData();
  const config = readUserConfig();
  const [apiKey, setApiKey] = useState(config.apiKey);
  const [serverUrl, setServerUrl] = useState(config.serverUrl || defaultServerUrl);

  const canSubmit = apiKey.trim().length > 0 && serverUrl.trim().length > 0;

  const handleSave = () => {
    if (!canSubmit) {
      return;
    }

    saveUserConfig({
      apiKey,
      serverUrl,
    });

    const nextPath = (location.state as SetupLocationState | null)?.from || "/generate";
    navigate(nextPath, { replace: true });
  };

  return (
    <div className="setup-page">
      <Card className="setup-card">
        <div className="setup-copy">
          <div className="eyebrow">{t("user.shell.nav.setup")}</div>
          <h2 className="page-title">{t("user.setup.title")}</h2>
          <p className="page-description">{t("user.setup.description")}</p>
        </div>

        <div className="form-stack">
          <div className="form-field-card">
            <label className="field-label" htmlFor="setup-api-key">{t("user.setup.apiKeyLabel")}</label>
            <div className="input-with-icon">
              <KeyRound className="field-leading-icon" />
              <TextField
                id="setup-api-key"
                type="password"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                placeholder={t("user.setup.apiKeyPlaceholder")}
                className="input-with-leading-icon"
              />
            </div>
          </div>

          <div className="form-field-card">
            <label className="field-label" htmlFor="setup-server-url">{t("user.setup.serverUrlLabel")}</label>
            <div className="input-with-icon">
              <Server className="field-leading-icon" />
              <TextField
                id="setup-server-url"
                value={serverUrl}
                onChange={(event) => setServerUrl(event.target.value)}
                placeholder={defaultServerUrl}
                className="input-with-leading-icon"
              />
            </div>
          </div>
        </div>

        <div className="setup-note">
          <div className="eyebrow">{t("user.setup.noteLabel")}</div>
          <p className="section-description">{t("user.setup.helper")}</p>
        </div>

        <Button
          variant="primary"
          className="full-width-button"
          onClick={handleSave}
          disabled={!canSubmit}
        >
          {t("user.setup.connectButton")}
        </Button>
      </Card>
    </div>
  );
}
