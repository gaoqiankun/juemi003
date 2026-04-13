import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Badge, Card } from "@/components/ui/primitives";
import {
  getGpuState,
  type GpuStateDevice,
  type GpuStateHolder,
  type GpuStateResponse,
} from "@/lib/admin-api";

const POLL_INTERVAL_MS = 3_000;

function formatVramMb(value: number): string {
  return `${Math.max(0, Math.round(value))} MB`;
}
function toPercent(value: number, total: number): number {
  if (total <= 0) return 0;
  return Math.max(0, Math.min(100, (value / total) * 100));
}
function getRuntimeTone(state: string): "neutral" | "success" | "warning" | "danger" {
  if (state === "ready") return "success";
  if (state === "loading") return "warning";
  if (state === "error") return "danger";
  return "neutral";
}
function getRuntimeLabel(state: string, t: (key: string) => string): string {
  const key = `models.runtime.${state}`;
  const translated = t(key);
  return translated === key ? state || t("models.runtime.unknown") : translated;
}
function getHolderLabel(holder: GpuStateHolder): string {
  if (holder.kind === "weight") return holder.modelName || "-";
  return `${holder.modelName || "-"} · ${holder.allocationId || "-"}`;
}
function renderUsageBar({
  total,
  reserved,
  weight,
  inference,
  external,
}: {
  total: number;
  reserved: number;
  weight: number;
  inference: number;
  external: number;
}) {
  const effectiveFree = Math.max(0, total - reserved - weight - inference - external);
  return (
    <div className="h-3 w-full overflow-hidden rounded-full border border-outline bg-surface-container-lowest">
      <div className="flex h-full w-full">
        <div className="h-full bg-surface-container-highest" style={{ width: `${toPercent(reserved, total)}%` }} />
        <div className="h-full bg-[color:color-mix(in_srgb,var(--accent)_70%,var(--surface-container-low))]" style={{ width: `${toPercent(weight, total)}%` }} />
        <div className="h-full bg-[color:color-mix(in_srgb,var(--warning)_66%,var(--surface-container-low))]" style={{ width: `${toPercent(inference, total)}%` }} />
        <div className="h-full bg-danger/60" style={{ width: `${toPercent(external, total)}%` }} />
        <div className="h-full border-l border-outline bg-transparent" style={{ width: `${toPercent(effectiveFree, total)}%` }} />
      </div>
    </div>
  );
}

export function VramPanel() {
  const { t } = useTranslation();
  const [data, setData] = useState<GpuStateResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let isActive = true;
    let timer: number | null = null;

    const loadState = async (silent: boolean) => {
      if (!silent) setLoading(true);
      try {
        const nextState = await getGpuState();
        if (!isActive) return;
        setData(nextState);
        setError("");
      } catch (loadError) {
        if (!isActive) return;
        setError(loadError instanceof Error ? loadError.message : String(loadError));
      } finally {
        if (isActive && !silent) setLoading(false);
      }
    };
    const stopPolling = () => {
      if (timer === null) return;
      window.clearInterval(timer);
      timer = null;
    };
    const startPolling = () => {
      if (timer !== null) return;
      timer = window.setInterval(() => {
        if (document.visibilityState === "visible") void loadState(true);
      }, POLL_INTERVAL_MS);
    };
    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        void loadState(true);
        startPolling();
      } else {
        stopPolling();
      }
    };

    void loadState(false);
    if (document.visibilityState === "visible") startPolling();
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      isActive = false;
      stopPolling();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, []);

  const cluster = data?.cluster;
  const holders = useMemo(
    () => [...(data?.holders || [])].sort((a, b) => Number(b.vramMb || 0) - Number(a.vramMb || 0)),
    [data?.holders],
  );
  const devices = useMemo(
    () =>
      [...(data?.devices || [])].sort((a, b) => {
        const left = Number(a.deviceId);
        const right = Number(b.deviceId);
        if (Number.isFinite(left) && Number.isFinite(right)) return left - right;
        return String(a.deviceId).localeCompare(String(b.deviceId));
      }),
    [data?.devices],
  );
  const clusterExternalOccupation = cluster
    ? Math.max(0, Number(cluster.freeVramMb || 0) - Number(cluster.effectiveFreeVramMb || 0))
    : 0;
  const clusterUsed = Number(cluster?.usedWeightVramMb || 0) + Number(cluster?.usedInferenceVramMb || 0);
  const clusterUsableTotal = Math.max(0, Number(cluster?.totalVramMb || 0) - Number(cluster?.reservedVramMb || 0));

  return (
    <Card className="grid gap-3 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h2 className="text-lg font-semibold tracking-[-0.02em] text-text-primary">{t("system.vramPanel.title")}</h2>
        {clusterExternalOccupation > 0 ? (
          <span className="inline-flex items-center gap-1 text-xs text-danger-text" title={t("system.vramPanel.externalOccupation.tooltip", { value: formatVramMb(clusterExternalOccupation) })}>
            <span className="h-2 w-2 rounded-full bg-danger" />
            <span>{t("system.vramPanel.cluster.externalOccupation")}: {formatVramMb(clusterExternalOccupation)}</span>
          </span>
        ) : null}
      </div>

      {loading && !data ? <p className="text-sm text-text-muted">{t("system.vramPanel.loading")}</p> : null}
      {error ? <p className="text-xs text-danger-text">{error}</p> : null}

      {cluster ? (
        <div className="grid gap-2 rounded-xl border border-outline bg-surface-container-low p-3">
          {renderUsageBar({
            total: Number(cluster.totalVramMb || 0),
            reserved: Number(cluster.reservedVramMb || 0),
            weight: Number(cluster.usedWeightVramMb || 0),
            inference: Number(cluster.usedInferenceVramMb || 0),
            external: clusterExternalOccupation,
          })}
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-text-secondary">
            <div className="flex flex-wrap items-center gap-2">
              <span>{t("system.vramPanel.cluster.total")}: {formatVramMb(cluster.totalVramMb)}</span>
              <span>{t("system.vramPanel.cluster.usedWeight")}: {formatVramMb(cluster.usedWeightVramMb)}</span>
              <span>{t("system.vramPanel.cluster.usedInference")}: {formatVramMb(cluster.usedInferenceVramMb)}</span>
              <span>{t("system.vramPanel.cluster.free")}: {formatVramMb(cluster.freeVramMb)}</span>
              <span>{t("system.vramPanel.cluster.effectiveFree")}: {formatVramMb(cluster.effectiveFreeVramMb)}</span>
            </div>
            <span className="text-sm font-medium text-text-primary">
              {formatVramMb(clusterUsed)} / {formatVramMb(clusterUsableTotal)} ({t("system.vramPanel.cluster.effectiveFree")} {formatVramMb(cluster.effectiveFreeVramMb)})
            </span>
          </div>
        </div>
      ) : null}

      <div className="overflow-x-auto rounded-xl border border-outline">
        <table className="min-w-full text-sm">
          <thead className="bg-surface-container-low text-xs uppercase tracking-[0.04em] text-text-muted">
            <tr>
              <th className="px-3 py-2 text-left">{t("system.vramPanel.holders.columnHolder")}</th>
              <th className="px-3 py-2 text-left">{t("system.vramPanel.holders.columnType")}</th>
              <th className="px-3 py-2 text-left">{t("system.vramPanel.holders.columnDevice")}</th>
              <th className="px-3 py-2 text-right">{t("system.vramPanel.holders.columnVram")}</th>
            </tr>
          </thead>
          <tbody>
            {holders.length === 0 ? (
              <tr>
                <td className="px-3 py-4 text-center text-sm text-text-muted" colSpan={4}>{t("system.vramPanel.holders.empty")}</td>
              </tr>
            ) : holders.map((holder, index) => (
              <tr key={`${holder.kind}-${holder.deviceId}-${holder.modelName}-${holder.allocationId || index}`} className="border-t border-outline">
                <td className="px-3 py-2.5">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="font-medium text-text-primary">{getHolderLabel(holder)}</span>
                    {holder.kind === "weight" ? (
                      <Badge tone={getRuntimeTone(String(holder.runtimeState || ""))}>{getRuntimeLabel(String(holder.runtimeState || ""), t)}</Badge>
                    ) : null}
                  </div>
                </td>
                <td className="px-3 py-2.5">
                  <Badge tone={holder.kind === "weight" ? "accent" : "warning"}>
                    {holder.kind === "weight" ? t("system.vramPanel.holders.typeWeight") : t("system.vramPanel.holders.typeInference")}
                  </Badge>
                </td>
                <td className="px-3 py-2.5 text-text-secondary">{t("settings.gpuDevices.device", { deviceId: holder.deviceId })}</td>
                <td className="px-3 py-2.5 text-right tabular-nums text-text-primary">{formatVramMb(holder.vramMb)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap gap-3">
        {devices.map((device: GpuStateDevice) => {
          const externalOccupation = Math.max(0, Number(device.externalOccupationMb || 0));
          return (
            <div key={device.deviceId} className="min-w-[260px] flex-1 rounded-xl border border-outline bg-surface-container-low p-3">
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-text-primary">{device.name || `GPU ${device.deviceId}`}</p>
                  <p className="text-xs text-text-muted">{t("settings.gpuDevices.device", { deviceId: device.deviceId })}</p>
                </div>
                <Badge tone={device.enabled ? "success" : "neutral"}>
                  {device.enabled ? t("system.vramPanel.device.enabled") : t("system.vramPanel.device.disabled")}
                </Badge>
              </div>

              <div className="mt-2 grid gap-2">
                {renderUsageBar({
                  total: Number(device.totalVramMb || 0),
                  reserved: Number(device.reservedVramMb || 0),
                  weight: Number(device.usedWeightVramMb || 0),
                  inference: Number(device.usedInferenceVramMb || 0),
                  external: externalOccupation,
                })}
                <div className="grid gap-1 text-xs text-text-secondary">
                  <span>{t("system.vramPanel.cluster.total")}: {formatVramMb(device.totalVramMb)}</span>
                  <span>{t("system.vramPanel.cluster.usedWeight")}: {formatVramMb(device.usedWeightVramMb)}</span>
                  <span>{t("system.vramPanel.cluster.usedInference")}: {formatVramMb(device.usedInferenceVramMb)}</span>
                  <span>{t("system.vramPanel.cluster.free")}: {formatVramMb(device.freeVramMb)}</span>
                  <span>{t("system.vramPanel.cluster.effectiveFree")}: {formatVramMb(device.effectiveFreeVramMb)}</span>
                </div>
                {externalOccupation > 0 ? (
                  <span className="inline-flex items-center gap-1 text-xs text-danger-text" title={t("system.vramPanel.externalOccupation.tooltip", { value: formatVramMb(externalOccupation) })}>
                    <span className="h-2 w-2 rounded-full bg-danger" />
                    <span>{t("system.vramPanel.cluster.externalOccupation")}: {formatVramMb(externalOccupation)}</span>
                  </span>
                ) : null}
                <div className="flex flex-wrap gap-1.5">
                  {device.weightModels.length === 0 ? (
                    <span className="text-xs text-text-muted">-</span>
                  ) : device.weightModels.map((model) => (
                    <span key={`${device.deviceId}-${model.name}`} className="inline-flex items-center gap-1 rounded-full border border-outline px-2 py-0.5 text-xs text-text-secondary">
                      <span className="truncate">{model.name}</span>
                      <span className="tabular-nums">{formatVramMb(model.vramMb)}</span>
                    </span>
                  ))}
                </div>
                <p className="text-xs text-text-secondary">{t("system.vramPanel.device.inferenceCount")}: {Math.max(0, Number(device.inferenceCount || 0))}</p>
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
