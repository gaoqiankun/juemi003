import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import {
  Button,
  Card,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  ToggleSwitch,
} from "@/components/ui/primitives";
import {
  cleanOrphans,
  fetchSettings,
  getStorageStats,
  listOrphans,
  updateSettings,
  type GpuDeviceSetting,
  type OrphanEntry,
  type StorageStats,
} from "@/lib/admin-api";
function formatBytes(bytes: number): string {
  return `${(bytes / (1024 ** 3)).toFixed(1)} GB`;
}
function normalizeGpuDevices(devices: GpuDeviceSetting[] | undefined): GpuDeviceSetting[] {
  if (!Array.isArray(devices)) {
    return [];
  }
  return devices
    .map((device) => ({
      deviceId: String(device.deviceId || "").trim(),
      enabled: Boolean(device.enabled),
      name: device.name ?? null,
      totalMemoryGb: device.totalMemoryGb ?? null,
    }))
    .filter((device) => Boolean(device.deviceId));
}

function extractDisabledDeviceIds(devices: GpuDeviceSetting[]): string[] {
  return devices
    .filter((device) => !device.enabled)
    .map((device) => device.deviceId)
    .sort();
}
export function SystemPage() {
  const { t } = useTranslation();
  const [gpuDevices, setGpuDevices] = useState<GpuDeviceSetting[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [isGpuSaving, setIsGpuSaving] = useState(false);
  const [storageStats, setStorageStats] = useState<StorageStats | null>(null);
  const [isCleaning, setIsCleaning] = useState(false);
  const [isConfirmOpen, setIsConfirmOpen] = useState(false);
  const [orphanList, setOrphanList] = useState<OrphanEntry[] | null>(null);
  const [isLoadingOrphans, setIsLoadingOrphans] = useState(false);

  const refreshStorageStats = useCallback(async () => {
    try {
      const stats = await getStorageStats();
      setStorageStats(stats);
    } catch {
      // ignore — non-critical
    }
  }, []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    fetchSettings()
      .then((settings) => {
        if (!active) return;
        setGpuDevices(normalizeGpuDevices(settings.gpuDevices));
      })
      .catch((loadError) => {
        if (!active) return;
        setError(loadError instanceof Error ? loadError.message : String(loadError));
      })
      .finally(() => {
        if (!active) return;
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    refreshStorageStats().catch(() => undefined);
  }, [refreshStorageStats]);

  const handleGpuToggle = useCallback(async (deviceId: string, enabled: boolean) => {
    if (isGpuSaving) {
      return;
    }
    const previousDevices = gpuDevices;
    const nextDevices = previousDevices.map((device) => (
      device.deviceId === deviceId
        ? { ...device, enabled }
        : device
    ));
    setGpuDevices(nextDevices);
    setIsGpuSaving(true);
    try {
      await updateSettings({
        gpuDisabledDevices: extractDisabledDeviceIds(nextDevices),
      });
    } catch (updateError) {
      setGpuDevices(previousDevices);
      toast.error(updateError instanceof Error ? updateError.message : String(updateError));
    } finally {
      setIsGpuSaving(false);
    }
  }, [gpuDevices, isGpuSaving]);

  const handleOpenCleanConfirm = useCallback(async () => {
    if (!storageStats || storageStats.orphan_count <= 0 || isCleaning || isLoadingOrphans) {
      return;
    }
    setIsLoadingOrphans(true);
    try {
      const items = await listOrphans();
      setOrphanList(items);
      setIsConfirmOpen(true);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setIsLoadingOrphans(false);
    }
  }, [isCleaning, isLoadingOrphans, storageStats]);

  const handleConfirmCleanOrphans = useCallback(async () => {
    if (isCleaning) {
      return;
    }
    setIsCleaning(true);
    try {
      const result = await cleanOrphans();
      toast.success(t("storage.cleaned", { freed: formatBytes(result.freed_bytes) }));
      setIsConfirmOpen(false);
      setOrphanList(null);
      await refreshStorageStats();
    } catch (cleanError) {
      toast.error(cleanError instanceof Error ? cleanError.message : String(cleanError));
    } finally {
      setIsCleaning(false);
    }
  }, [isCleaning, refreshStorageStats, t]);

  const usedBytes = useMemo(
    () => (storageStats ? Math.max(0, storageStats.disk_total_bytes - storageStats.disk_free_bytes) : 0),
    [storageStats],
  );
  const usagePercent = useMemo(() => {
    if (!storageStats || storageStats.disk_total_bytes <= 0) {
      return 0;
    }
    return Math.min(100, (usedBytes / storageStats.disk_total_bytes) * 100);
  }, [storageStats, usedBytes]);
  const orphanCount = storageStats?.orphan_count ?? 0;
  const orphanSize = formatBytes(storageStats?.orphan_bytes ?? 0);

  if (loading) return <div className="flex h-full items-center justify-center"><span className="text-text-secondary">Loading...</span></div>;
  if (error) return <div className="flex h-full items-center justify-center text-red-500">{error}</div>;

  return (
    <div className="grid gap-4">
      <section>
        <Card className="grid gap-3 p-4">
          <h2 className="text-lg font-semibold tracking-[-0.02em] text-text-primary">
            {t("settings.gpuDevices.title")}
          </h2>
          <div className="grid gap-2">
            {gpuDevices.map((device) => (
              <div
                key={device.deviceId}
                className="flex items-center gap-3 rounded-lg border border-outline bg-surface-container-low px-3 py-2.5"
              >
                <span className="font-display text-[0.6875rem] font-semibold uppercase tracking-[0.05em] text-text-muted shrink-0">
                  {t("settings.gpuDevices.device", { deviceId: device.deviceId })}
                </span>
                <span className="min-w-0 flex-1 truncate text-sm font-medium text-text-primary">
                  {device.name ?? device.deviceId}
                </span>
                {device.totalMemoryGb != null ? (
                  <span className="shrink-0 text-xs text-text-secondary">{device.totalMemoryGb} GB</span>
                ) : null}
                <div className="flex shrink-0 items-center gap-1.5">
                  <span className="text-xs font-medium text-text-secondary">
                    {t(device.enabled ? "common.status.active" : "common.status.paused")}
                  </span>
                  <ToggleSwitch
                    checked={device.enabled}
                    onChange={(nextValue) => {
                      void handleGpuToggle(device.deviceId, nextValue);
                    }}
                    label={t("settings.gpuDevices.device", { deviceId: device.deviceId })}
                    className={isGpuSaving ? "opacity-60" : undefined}
                  />
                </div>
              </div>
            ))}
          </div>
        </Card>
      </section>

      <section>
        <Card tone="low" className="grid gap-3 p-4">
          <h2 className="text-lg font-semibold tracking-[-0.02em] text-text-primary">
            {t("storage.diskUsage")}
          </h2>
          {storageStats ? (
            <>
              <div className="grid gap-1.5">
                <div className="flex items-center justify-between text-xs text-text-secondary">
                  <span>{formatBytes(usedBytes)} / {formatBytes(storageStats.disk_total_bytes)}</span>
                  <span>{Math.round(usagePercent)}%</span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-surface-container-highest">
                  <div
                    className="h-full rounded-full bg-primary transition-all"
                    style={{ width: `${usagePercent.toFixed(1)}%` }}
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="grid gap-1 rounded-lg border border-outline bg-surface-container-low p-3">
                  <span className="font-display text-[0.6875rem] font-semibold uppercase tracking-[0.05em] text-text-muted">
                    {t("storage.cache")}
                  </span>
                  <span className="text-sm font-medium text-text-primary">{formatBytes(storageStats.cache_bytes)}</span>
                </div>
                <div className="grid gap-1 rounded-lg border border-outline bg-surface-container-low p-3">
                  <span className="font-display text-[0.6875rem] font-semibold uppercase tracking-[0.05em] text-text-muted">
                    {t("storage.orphaned")}
                  </span>
                  <span className="text-sm font-medium text-text-primary">{orphanSize}</span>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                <Button
                  type="button"
                  size="sm"
                  disabled={isCleaning || isLoadingOrphans || orphanCount <= 0}
                  onClick={() => { void handleOpenCleanConfirm(); }}
                >
                  {isCleaning || isLoadingOrphans ? t("storage.cleaning") : t("storage.cleanOrphans.action")}
                </Button>
              </div>
            </>
          ) : (
            <p className="text-sm text-text-muted">...</p>
          )}
        </Card>
      </section>

      <Dialog
        open={isConfirmOpen}
        onOpenChange={(open) => {
          if (!isCleaning) {
            setIsConfirmOpen(open);
            if (!open) setOrphanList(null);
          }
        }}
      >
        <DialogContent className="w-[min(92vw,520px)] p-4">
          <DialogHeader className="pr-8">
            <DialogTitle>{t("storage.cleanOrphans.confirmTitle")}</DialogTitle>
            <DialogDescription>
              {t("storage.cleanOrphans.confirmDescription", { count: orphanCount, size: orphanSize })}
            </DialogDescription>
          </DialogHeader>
          {orphanList && orphanList.length > 0 && (
            <div className="max-h-48 overflow-y-auto rounded-lg border border-outline bg-surface-container-low">
              {orphanList.map((entry) => (
                <div
                  key={entry.path}
                  className="flex items-center justify-between gap-3 border-b border-outline px-3 py-1.5 last:border-b-0"
                >
                  <span className="truncate font-mono text-xs text-text-secondary" title={entry.path}>
                    {entry.path}
                  </span>
                  <span className="shrink-0 text-xs text-text-muted">{formatBytes(entry.size_bytes)}</span>
                </div>
              ))}
            </div>
          )}
          <div className="flex justify-end gap-2 pt-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={isCleaning}
              onClick={() => { setIsConfirmOpen(false); setOrphanList(null); }}
            >
              {t("storage.cleanOrphans.cancel")}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="danger"
              disabled={isCleaning}
              onClick={() => {
                void handleConfirmCleanOrphans();
              }}
            >
              {isCleaning ? t("storage.cleaning") : t("storage.cleanOrphans.confirm")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
