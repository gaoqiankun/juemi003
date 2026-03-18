import { Activity, Eye, EyeOff, Save } from "lucide-react";
import { useState } from "react";

import { useGen3d } from "@/app/gen3d-provider";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

export function SettingsPage() {
  const { config, connection, saveConfig, pingHealth } = useGen3d();
  const [baseUrl, setBaseUrl] = useState(config.baseUrl);
  const [token, setToken] = useState(config.token);
  const [revealToken, setRevealToken] = useState(false);

  const dotClass = connection.tone === "ready"
    ? "bg-emerald-400 shadow-[0_0_0_10px_rgba(74,222,128,0.14)]"
    : "bg-rose-400 shadow-[0_0_0_10px_rgba(251,113,133,0.08)]";

  return (
    <section className="grid gap-6 lg:grid-cols-[1.02fr_0.98fr]">
      <Card className="bg-[linear-gradient(160deg,rgba(10,18,34,0.98),rgba(7,11,22,0.94))]">
        <CardHeader>
          <div className="text-xs uppercase tracking-[0.26em] text-slate-500">Settings</div>
          <CardTitle className="text-4xl md:text-5xl">把连接配置固定下来。</CardTitle>
          <CardDescription className="max-w-3xl text-base text-slate-300">
            设置页负责存储 API Key / Base URL，并用 /health 做连通性测试。保存后立即刷新顶部连接状态与任务列表。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="grid gap-5"
            onSubmit={(event) => {
              event.preventDefault();
              saveConfig({ baseUrl, token }).catch(() => undefined);
            }}
          >
            <div className="grid gap-2">
              <Label htmlFor="settings-api-key">API Key</Label>
              <div className="relative">
                <Input
                  id="settings-api-key"
                  type={revealToken ? "text" : "password"}
                  value={token}
                  onChange={(event) => setToken(event.target.value)}
                  autoComplete="off"
                  placeholder="sk-..."
                  className="pr-28"
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="absolute right-2 top-1/2 -translate-y-1/2"
                  onClick={() => setRevealToken((previous) => !previous)}
                >
                  {revealToken ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  {revealToken ? "隐藏" : "显示"}
                </Button>
              </div>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="settings-base-url">API Base URL</Label>
              <Input
                id="settings-base-url"
                type="url"
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                placeholder="http://localhost:8000"
              />
            </div>

            <div className="flex flex-wrap gap-3 pt-2">
              <Button type="submit" variant="secondary">
                <Save className="h-4 w-4" />
                保存配置
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  saveConfig({ baseUrl, token })
                    .then(() => pingHealth(false))
                    .catch(() => undefined);
                }}
              >
                <Activity className="h-4 w-4" />
                测试 /health
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <div className="grid gap-5 self-start">
        <Card>
          <CardContent className="flex items-center justify-between gap-4 p-6">
            <div>
              <div className="text-xs uppercase tracking-[0.22em] text-slate-500">Connection Status</div>
              <div className="mt-3 font-display text-2xl font-semibold text-white">{connection.label || "等待检测"}</div>
              <div className="mt-3 text-sm leading-7 text-slate-400">{connection.detail || "保存配置后，可随时用 /health 验证服务状态。"}</div>
            </div>
            <span className={cn("h-3.5 w-3.5 rounded-full", dotClass)} />
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="text-xs uppercase tracking-[0.22em] text-slate-500">Persistence</div>
            <ul className="mt-4 space-y-3 text-sm leading-7 text-slate-300">
              <li>• API Key 与 Base URL 保存到 localStorage。</li>
              <li>• 当前主任务 ID 保存到 sessionStorage，刷新页面仍可回到进行中的任务。</li>
              <li>• 修改配置后会自动刷新任务列表并恢复活跃任务订阅。</li>
            </ul>
          </CardContent>
        </Card>
      </div>
    </section>
  );
}
