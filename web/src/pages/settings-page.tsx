import { Eye, EyeOff, LoaderCircle, Save } from "lucide-react";
import { useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { useGen3d } from "@/app/gen3d-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function SettingsPage() {
  const { config, connection, saveConfig, pingHealth } = useGen3d();
  const navigate = useNavigate();
  const location = useLocation();
  const [baseUrl, setBaseUrl] = useState(config.baseUrl);
  const [token, setToken] = useState(config.token);
  const [revealToken, setRevealToken] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  const connectionText = useMemo(() => {
    if (connection.tone === "ready") {
      return "已连接";
    }
    if (connection.tone === "empty") {
      return "等待连接";
    }
    return "连接失败";
  }, [connection.tone]);

  const fallbackPath = typeof location.state === "object"
    && location.state
    && "from" in location.state
    && typeof location.state.from === "string"
    ? location.state.from
    : "/";
  const goBack = () => {
    const historyIndex = window.history.state?.idx;
    if (typeof historyIndex === "number" && historyIndex > 0) {
      navigate(-1);
      return;
    }
    navigate(fallbackPath, { replace: true });
  };

  return (
    <section className="mx-auto max-w-3xl space-y-6 px-6 py-6">
      <header className="space-y-2">
        <p className="text-[12px] text-[#666666]">设置</p>
        <h1 className="text-[20px] font-medium text-white">连接配置</h1>
        <p className="text-[13px] text-[#888888]">管理 API 密钥和服务地址。</p>
      </header>

      <div className="overflow-hidden rounded-[18px] border border-[#1a1a1a] bg-[#0f0f0f]">
        <div className="flex items-center justify-between gap-4 border-b border-[#1a1a1a] px-5 py-4">
          <div className="flex items-center gap-2 text-[13px] text-white">
            <span
              className={`h-2 w-2 rounded-full ${
                connection.tone === "ready"
                  ? "bg-[#16a34a]"
                  : connection.tone === "empty"
                    ? "bg-[#666666]"
                    : "bg-[#dc2626]"
              }`}
            />
            <span>{connectionText}</span>
          </div>
          <Button
            type="button"
            variant="outline"
            className="h-9 rounded-xl border border-[#2a2a2a] bg-[#111111] px-4 text-[13px] font-medium text-white shadow-none hover:bg-[#1a1a1a] hover:text-white"
            disabled={isSaving}
            onClick={() => pingHealth(false).catch(() => undefined)}
          >
            检测连接
          </Button>
        </div>

        <form
          className="grid gap-5 px-5 py-5"
          onSubmit={async (event) => {
            event.preventDefault();
            if (isSaving) {
              return;
            }
            setIsSaving(true);
            try {
              await saveConfig({ baseUrl, token });
              goBack();
            } catch {
              setIsSaving(false);
            }
          }}
        >
          <div className="grid gap-2">
            <Label htmlFor="settings-api-key" className="text-[13px] font-medium text-white">API 密钥</Label>
            <div className="relative">
              <Input
                id="settings-api-key"
                type={revealToken ? "text" : "password"}
                value={token}
                onChange={(event) => setToken(event.target.value)}
                autoComplete="off"
                placeholder="sk-..."
                disabled={isSaving}
                className="h-12 rounded-xl border-[#2a2a2a] bg-[#111111] pr-28 text-[14px] text-white placeholder:text-[#555555] focus:border-white/15 focus:bg-[#151515] focus:ring-0"
              />
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="absolute right-2 top-1/2 h-8 -translate-y-1/2 rounded-lg px-3 text-[12px] text-[#aaaaaa] hover:bg-[#1a1a1a] hover:text-white"
                disabled={isSaving}
                onClick={() => setRevealToken((previous) => !previous)}
              >
                {revealToken ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                {revealToken ? "隐藏" : "显示"}
              </Button>
            </div>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="settings-base-url" className="text-[13px] font-medium text-white">服务地址</Label>
            <Input
              id="settings-base-url"
              type="url"
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
              placeholder="http://localhost:8000"
              disabled={isSaving}
              className="h-12 rounded-xl border-[#2a2a2a] bg-[#111111] text-[14px] text-white placeholder:text-[#555555] focus:border-white/15 focus:bg-[#151515] focus:ring-0"
            />
          </div>

          <div className="flex items-center justify-between gap-3 pt-2">
            <p className="text-[12px] text-[#666666]">
              {isSaving ? "正在保存并同步连接..." : "保存后将返回上一页"}
            </p>
            <div className="flex justify-end gap-3">
              <Button
                type="button"
                variant="outline"
                className="h-11 rounded-xl border border-[#2a2a2a] bg-[#1f1f1f] px-5 text-[13px] font-medium text-white shadow-none hover:bg-[#252525] hover:text-white"
                disabled={isSaving}
                onClick={goBack}
              >
                取消
              </Button>
              <Button
                type="submit"
                disabled={isSaving}
                className="h-11 rounded-xl bg-[#16a34a] px-5 text-[13px] font-medium text-white shadow-none hover:bg-[#15803d]"
              >
                {isSaving ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                {isSaving ? "保存中" : "保存"}
              </Button>
            </div>
          </div>
        </form>
      </div>
    </section>
  );
}
