import { Ban, Download, GalleryHorizontalEnd, RotateCcw, Sparkles, UploadCloud } from "lucide-react";
import { Link } from "react-router-dom";

import { canCancelTask, useGen3d } from "@/app/gen3d-provider";
import { ThreeViewer } from "@/components/three-viewer";
import { TaskStatusBadge } from "@/components/task-status-badge";
import { UploadDropzone } from "@/components/upload-dropzone";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { formatStage, formatTime, formatTaskStatus, getTaskShortId } from "@/lib/format";

export function GeneratePage() {
  const {
    config,
    connection,
    generate,
    currentTask,
    generateView,
    selectFile,
    clearSelectedFile,
    submitCurrentFile,
    retryCurrentTask,
    cancelTask,
    setCurrentTaskId,
  } = useGen3d();

  const connectionLabel = connection.tone === "ready"
    ? "服务在线"
    : generate.currentTaskId
      ? "服务检测不阻断提交"
      : "请先配置 API Key";

  if (generateView === "uploading") {
    return (
      <section className="grid gap-6 lg:grid-cols-[1.14fr_0.86fr]">
        <Card className="bg-[linear-gradient(160deg,rgba(10,18,34,0.98),rgba(7,11,22,0.94))]">
          <CardHeader>
            <div className="text-xs uppercase tracking-[0.26em] text-slate-500">Generate</div>
            <CardTitle className="text-4xl md:text-5xl">上传已接管，马上进入生成流水线。</CardTitle>
            <CardDescription className="max-w-2xl text-base text-slate-300">
              当前隐藏重复上传入口，避免误操作。上传完成后会自动创建任务并切入实时进度视图。
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="rounded-[28px] border border-white/10 bg-white/5 p-6">
              <div className="flex items-center justify-between gap-3 text-sm text-slate-300">
                <span>{generate.name || "输入图片"}</span>
                <span>{Math.max(0, Math.min(100, generate.uploadProgress || 0))}%</span>
              </div>
              <Progress value={generate.uploadProgress} className="mt-4 h-2.5" />
              <div className="mt-4 text-sm text-cyan-100">{generate.statusMessage}</div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-5">
            <div className="overflow-hidden rounded-[28px] border border-white/10 bg-slate-950">
              {generate.previewDataUrl ? (
                <img src={generate.previewDataUrl} alt="上传预览" className="h-[320px] w-full object-cover" />
              ) : (
                <div className="flex h-[320px] items-center justify-center text-slate-500">等待图片读入</div>
              )}
            </div>
            <div className="mt-5 space-y-3 text-sm text-slate-300">
              <div className="rounded-[22px] border border-white/10 bg-white/5 px-4 py-4">
                <div className="text-xs uppercase tracking-[0.22em] text-slate-500">Connection</div>
                <div className="mt-2 font-medium text-white">{connectionLabel}</div>
              </div>
              <div className="rounded-[22px] border border-white/10 bg-white/5 px-4 py-4">
                <div className="text-xs uppercase tracking-[0.22em] text-slate-500">Pipeline</div>
                <div className="mt-2 font-medium text-white">Upload → Create Task → SSE</div>
              </div>
            </div>
          </CardContent>
        </Card>
      </section>
    );
  }

  if (generateView === "processing" && currentTask) {
    const progress = Math.max(0, Math.min(100, currentTask.progress || 0));
    const queueMeta = currentTask.queuePosition != null
      ? `队列位置 ${currentTask.queuePosition}`
      : currentTask.estimatedWaitSeconds != null
        ? `预计等待 ${currentTask.estimatedWaitSeconds}s`
        : "等待实时进度推送";
    const canCancel = canCancelTask(currentTask);

    return (
      <section className="space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <Link to="/gallery" className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-300 transition hover:bg-white/10">
            <GalleryHorizontalEnd className="h-4 w-4 text-cyan-200" />
            历史任务在图库查看
          </Link>
          <div className="inline-flex items-center gap-3 rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-300">
            <span className={`h-2.5 w-2.5 rounded-full ${canCancel ? "bg-emerald-400" : "bg-amber-400"}`} />
            {canCancel ? "当前阶段允许取消" : "当前阶段不可取消"}
          </div>
        </div>

        <Card className="bg-[linear-gradient(160deg,rgba(10,18,34,0.98),rgba(7,11,22,0.94))]">
          <CardContent className="grid gap-6 p-6 md:p-8 lg:grid-cols-[1.12fr_0.88fr]">
            <div className="space-y-6">
              <div className="flex flex-wrap items-start justify-between gap-5">
                <div>
                  <div className="text-xs uppercase tracking-[0.26em] text-slate-500">Processing</div>
                  <h1 className="mt-3 font-display text-4xl font-semibold tracking-[-0.04em] text-white md:text-5xl">
                    {formatStage(currentTask.currentStage || currentTask.status)}
                  </h1>
                  <p className="mt-4 max-w-3xl text-base leading-7 text-slate-300">
                    任务 {getTaskShortId(currentTask.taskId)} 正在运行。前端会优先使用带 Authorization 的 fetch SSE，异常时自动降级到 polling。
                  </p>
                </div>
                <div className="rounded-[28px] border border-white/10 bg-white/5 px-5 py-4 text-right">
                  <div className="text-xs uppercase tracking-[0.24em] text-slate-500">Progress</div>
                  <div className="mt-2 font-display text-5xl font-semibold tracking-[-0.05em] text-white">{progress}%</div>
                  <div className="mt-2 text-sm text-slate-400">{queueMeta}</div>
                </div>
              </div>

              <div className="rounded-[30px] border border-white/10 bg-white/5 p-5">
                <div className="flex items-center justify-between gap-3">
                  <TaskStatusBadge task={currentTask} />
                  <span className="rounded-full border border-white/10 bg-slate-950/40 px-3 py-1 text-xs uppercase tracking-[0.2em] text-slate-400">
                    {currentTask.transport}
                  </span>
                </div>
                <Progress value={progress} className="mt-6 h-2.5" />
                <div className="mt-5 grid gap-4 md:grid-cols-3">
                  <div className="rounded-[22px] border border-white/10 bg-slate-950/35 px-4 py-4">
                    <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Task ID</div>
                    <div className="mt-2 text-sm text-white">{currentTask.taskId}</div>
                  </div>
                  <div className="rounded-[22px] border border-white/10 bg-slate-950/35 px-4 py-4">
                    <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Created</div>
                    <div className="mt-2 text-sm text-white">{formatTime(currentTask.createdAt)}</div>
                  </div>
                  <div className="rounded-[22px] border border-white/10 bg-slate-950/35 px-4 py-4">
                    <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Status</div>
                    <div className="mt-2 text-sm text-white">{formatTaskStatus(currentTask.status)}</div>
                  </div>
                </div>
                <div className="mt-5 flex flex-wrap gap-3">
                  <Button variant="outline" disabled={!canCancel} onClick={() => cancelTask(currentTask.taskId).catch(() => undefined)}>
                    <Ban className="h-4 w-4" />
                    {currentTask.pendingCancel ? "取消中…" : "取消任务"}
                  </Button>
                  <Button asChild variant="secondary">
                    <Link to="/gallery">
                      <GalleryHorizontalEnd className="h-4 w-4" />
                      查看图库
                    </Link>
                  </Button>
                </div>
              </div>
            </div>

            <Card className="bg-white/5">
              <CardContent className="p-5">
                <div>
                  <div className="text-xs uppercase tracking-[0.22em] text-slate-500">Live Logs</div>
                  <div className="mt-2 text-sm text-slate-400">最近 30 条任务事件，持续实时更新。</div>
                </div>
                <div className="mt-5 space-y-3 max-h-[460px] overflow-auto pr-1">
                  {currentTask.events.length ? currentTask.events.slice().reverse().map((event) => (
                    <div key={`${event.timestamp}-${event.event}-${event.progress}`} className="rounded-[22px] border border-white/10 bg-slate-950/40 px-4 py-3">
                      <div className="flex items-center justify-between gap-3">
                        <strong className="text-sm text-white">{event.event}</strong>
                        <span className="text-xs text-slate-500">{formatTime(event.timestamp)}</span>
                      </div>
                      <div className="mt-2 text-sm text-slate-300">状态：{formatTaskStatus(event.status)} · 阶段：{formatStage(event.currentStage)}</div>
                      <div className="mt-1 text-xs text-slate-500">进度 {event.progress}% · 来源 {event.source}{event.message ? ` · ${event.message}` : ""}</div>
                    </div>
                  )) : (
                    <div className="rounded-[22px] border border-dashed border-white/10 px-4 py-8 text-center text-sm text-slate-400">等待第一条实时日志…</div>
                  )}
                </div>
              </CardContent>
            </Card>
          </CardContent>
        </Card>
      </section>
    );
  }

  if (generateView === "completed" && currentTask) {
    const downloadUrl = currentTask.resolvedArtifactUrl || currentTask.rawArtifactUrl || "";
    return (
      <section className="space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <Link to="/gallery" className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-300 transition hover:bg-white/10">
            <GalleryHorizontalEnd className="h-4 w-4 text-cyan-200" />
            历史任务在图库查看
          </Link>
          <div className="inline-flex items-center gap-3 rounded-full border border-emerald-400/20 bg-emerald-400/10 px-4 py-2 text-sm text-emerald-100">
            <span className="h-2.5 w-2.5 rounded-full bg-emerald-400" />
            Three.js 查看器已切入完成态
          </div>
        </div>

        <Card className="bg-[linear-gradient(160deg,rgba(10,18,34,0.98),rgba(7,11,22,0.94))]">
          <CardContent className="grid gap-6 p-5 md:p-7 lg:grid-cols-[1.16fr_0.84fr]">
            <div className="space-y-5">
              <div>
                <div className="text-xs uppercase tracking-[0.26em] text-slate-500">Completed</div>
                <h1 className="mt-3 font-display text-4xl font-semibold tracking-[-0.04em] text-white md:text-5xl">模型已生成，主屏直接预览。</h1>
                <p className="mt-4 max-w-3xl text-base leading-7 text-slate-300">
                  任务 {getTaskShortId(currentTask.taskId)} 已完成。新的主任务完成后，会直接替换这里的查看器内容。
                </p>
              </div>
              <div className="h-[440px] overflow-hidden rounded-[30px] border border-white/10 bg-slate-950 md:h-[560px]">
                <ThreeViewer
                  url={downloadUrl}
                  message="当前 artifact 地址无法直接预览。"
                  baseUrl={config.baseUrl}
                  token={config.token}
                />
              </div>
            </div>

            <div className="space-y-4">
              <TaskStatusBadge task={currentTask} />
              <Card>
                <CardContent className="space-y-3 p-5">
                  <div>
                    <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Artifact</div>
                    <div className="mt-2 text-sm text-white">{downloadUrl ? "GLB 已就绪" : "等待 artifact URL"}</div>
                  </div>
                  <div>
                    <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Created</div>
                    <div className="mt-2 text-sm text-white">{formatTime(currentTask.createdAt)}</div>
                  </div>
                  <div>
                    <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Updated</div>
                    <div className="mt-2 text-sm text-white">{formatTime(currentTask.updatedAt || currentTask.lastSeenAt)}</div>
                  </div>
                  <div className="rounded-[22px] border border-white/10 bg-slate-950/35 px-4 py-4 text-sm leading-7 text-slate-300">
                    {currentTask.note || "产物地址已归一化，新创建任务与历史任务共用同一套 URL 解析逻辑。"}
                  </div>
                </CardContent>
              </Card>
              <div className="flex flex-wrap gap-3">
                <Button asChild variant="secondary">
                  <a href={downloadUrl || "#"} target="_blank" rel="noreferrer" download="model.glb" className={!downloadUrl ? "pointer-events-none opacity-50" : ""}>
                    <Download className="h-4 w-4" />
                    下载模型
                  </a>
                </Button>
                <Button asChild variant="outline">
                  <Link to="/gallery">
                    <GalleryHorizontalEnd className="h-4 w-4" />
                    查看图库
                  </Link>
                </Button>
                <Button variant="outline" onClick={() => {
                  setCurrentTaskId("");
                  clearSelectedFile(false);
                }}>
                  <RotateCcw className="h-4 w-4" />
                  再生成一个
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      </section>
    );
  }

  if (generateView === "failed" && currentTask) {
    const title = currentTask.status === "cancelled" ? "任务已取消" : "本次生成未完成。";
    const copy = currentTask.error?.message || currentTask.note || (currentTask.status === "cancelled" ? "后端已确认任务取消。你可以重新提交同一张图。" : "后端返回了失败状态，请检查日志后重试。");
    return (
      <section className="grid gap-6 lg:grid-cols-[1.06fr_0.94fr]">
        <Card className="bg-[linear-gradient(160deg,rgba(27,12,18,0.96),rgba(7,11,22,0.94))]">
          <CardHeader>
            <div className="text-xs uppercase tracking-[0.26em] text-slate-500">Failed</div>
            <CardTitle className="text-4xl md:text-5xl">{title}</CardTitle>
            <CardDescription className="max-w-2xl text-base text-slate-300">{copy}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="rounded-[26px] border border-rose-400/18 bg-rose-500/10 p-5 text-sm leading-7 text-rose-100">
              <div><strong className="text-white">Task ID</strong> · {currentTask.taskId}</div>
              <div className="mt-2"><strong className="text-white">Stage</strong> · {formatStage(currentTask.currentStage || currentTask.status)}</div>
              <div className="mt-2"><strong className="text-white">Last Update</strong> · {formatTime(currentTask.updatedAt || currentTask.lastSeenAt)}</div>
            </div>
            <div className="flex flex-wrap gap-3">
              <Button variant="secondary" onClick={() => retryCurrentTask().catch(() => undefined)}>
                <RotateCcw className="h-4 w-4" />
                重试任务
              </Button>
              <Button variant="outline" onClick={() => {
                setCurrentTaskId("");
                clearSelectedFile(false);
              }}>
                <UploadCloud className="h-4 w-4" />
                重新上传
              </Button>
              <Button asChild variant="ghost">
                <Link to="/gallery">
                  <GalleryHorizontalEnd className="h-4 w-4" />
                  查看图库
                </Link>
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-5">
            <div>
              <div className="text-xs uppercase tracking-[0.22em] text-slate-500">Recent Logs</div>
              <div className="mt-2 text-sm text-slate-400">失败前最后的事件序列，帮助快速定位阶段。</div>
            </div>
            <div className="mt-5 space-y-3">
              {currentTask.events.length ? currentTask.events.slice().reverse().map((event) => (
                <div key={`${event.timestamp}-${event.event}-${event.progress}`} className="rounded-[22px] border border-white/10 bg-slate-950/40 px-4 py-3">
                  <div className="flex items-center justify-between gap-3">
                    <strong className="text-sm text-white">{event.event}</strong>
                    <span className="text-xs text-slate-500">{formatTime(event.timestamp)}</span>
                  </div>
                  <div className="mt-2 text-sm text-slate-300">状态：{event.status} · 阶段：{formatStage(event.currentStage)}</div>
                  <div className="mt-1 text-xs text-slate-500">进度 {event.progress}% · 来源 {event.source}{event.message ? ` · ${event.message}` : ""}</div>
                </div>
              )) : (
                <div className="rounded-[22px] border border-dashed border-white/10 px-4 py-8 text-center text-sm text-slate-400">暂无可用日志。</div>
              )}
            </div>
          </CardContent>
        </Card>
      </section>
    );
  }

  return (
    <section className="grid gap-6 lg:grid-cols-[1.08fr_0.92fr]">
      <Card className="bg-[linear-gradient(160deg,rgba(10,18,34,0.98),rgba(7,11,22,0.94))]">
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-4">
            <Link to="/gallery" className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-300 transition hover:bg-white/10">
              <GalleryHorizontalEnd className="h-4 w-4 text-cyan-200" />
              历史任务在图库查看
            </Link>
            <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-300">
              <span className={`h-2.5 w-2.5 rounded-full ${generate.previewDataUrl ? "bg-emerald-400" : "bg-amber-400"}`} />
              {generate.previewDataUrl ? "图片已准备，可直接提交" : "先选择输入图片"}
            </span>
          </div>
          <div className="pt-2">
            <div className="text-xs uppercase tracking-[0.26em] text-slate-500">Generate</div>
            <CardTitle className="mt-3 text-4xl md:text-5xl">上传一张图片，进入单任务状态机。</CardTitle>
            <CardDescription className="max-w-3xl text-base text-slate-300">
              参考 Meshy / Tripo 的工作台布局，把注意力收拢在一个主任务上：上传、处理、预览、下载都在同一条视觉主线上完成。
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent className="space-y-5">
          <UploadDropzone
            previewUrl={generate.previewDataUrl}
            fileName={generate.name}
            onFileSelect={(file) => selectFile(file).catch(() => undefined)}
            onClear={() => clearSelectedFile(false)}
            disabled={generate.isSubmitting}
          />

          <div className="grid gap-5 rounded-[28px] border border-white/10 bg-white/5 px-4 py-5 md:grid-cols-[1fr_auto] md:items-center md:px-5">
            <div>
              <div className="text-sm font-medium text-white">{generate.name || "尚未选择图片"}</div>
              <div className={`mt-2 text-sm ${generate.statusTone === "error" ? "text-rose-200" : generate.statusTone === "success" ? "text-emerald-200" : "text-slate-300"}`}>
                {generate.statusMessage}
              </div>
            </div>
            <div className="flex flex-wrap gap-3">
              <Button asChild variant="outline">
                <Link to="/settings">连接设置</Link>
              </Button>
              <Button disabled={generate.isSubmitting} onClick={() => submitCurrentFile().catch(() => undefined)}>
                <Sparkles className="h-4 w-4" />
                {generate.isSubmitting ? "正在创建任务…" : "开始生成"}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="space-y-5 self-start">
        <Card>
          <CardContent className="p-5">
            <div className="text-xs uppercase tracking-[0.22em] text-slate-500">Connection</div>
            <div className="mt-3 font-display text-2xl font-semibold text-white">{connectionLabel}</div>
            <p className="mt-3 text-sm leading-7 text-slate-400">
              右上角绿点基于 /health 检测进程存活；任务提交只依赖 /v1/tasks 本身的响应结果。
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-5">
            <div className="text-xs uppercase tracking-[0.22em] text-slate-500">Rules</div>
            <ul className="mt-4 space-y-3 text-sm leading-7 text-slate-300">
              <li>• 生成页不展示历史任务卡片，避免干扰主任务处理。</li>
              <li>• 新任务完成后自动切入 Three.js 完成态，无需跳转。</li>
              <li>• 仅 `gpu_queued` 阶段允许取消，其余阶段统一 disabled。</li>
              <li>• 历史任务统一进入图库详情侧栏查看与删除。</li>
            </ul>
          </CardContent>
        </Card>
      </div>
    </section>
  );
}
