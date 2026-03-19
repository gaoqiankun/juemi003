import { ImagePlus, UploadCloud, X } from "lucide-react";

import { Button } from "@/components/ui/button";

export function UploadDropzone({
  previewUrl,
  fileName,
  onFileSelect,
  onClear,
  disabled,
}: {
  previewUrl?: string;
  fileName?: string;
  onFileSelect: (file: File | null) => void;
  onClear: () => void;
  disabled?: boolean;
}) {
  return (
    <label
      className="group relative block cursor-pointer overflow-hidden rounded-[32px] border border-white/10 bg-[linear-gradient(145deg,rgba(14,22,38,0.96),rgba(5,8,18,0.92))] p-6 transition hover:border-cyan-400/30 hover:bg-[linear-gradient(145deg,rgba(17,27,46,0.98),rgba(6,10,18,0.96))]"
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => {
        event.preventDefault();
        onFileSelect(event.dataTransfer.files?.[0] || null);
      }}
    >
      <input
        type="file"
        accept="image/png,image/jpeg,image/webp"
        className="hidden"
        disabled={disabled}
        onChange={(event) => onFileSelect(event.target.files?.[0] || null)}
      />

      <div className="grid gap-6 md:grid-cols-[1.04fr_0.96fr] md:items-center">
        <div>
          <h2 className="mt-4 font-display text-3xl font-semibold tracking-[-0.04em] text-white md:text-4xl">
            拖拽图片到这里，或点击选择
          </h2>
          <p className="mt-4 max-w-xl text-sm leading-7 text-slate-300 md:text-base">
            支持 JPG、PNG、WEBP
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <Button type="button" variant="secondary" disabled={disabled}>
              <UploadCloud className="h-4 w-4" />
              选择图片
            </Button>
            <Button type="button" variant="outline" onClick={(event) => {
              event.preventDefault();
              onClear();
            }} disabled={!previewUrl || disabled}>
              <X className="h-4 w-4" />
              清除
            </Button>
          </div>
        </div>

        <div className="relative overflow-hidden rounded-[28px] border border-white/10 bg-slate-950 min-h-[260px]">
          {previewUrl ? (
            <img src={previewUrl} alt="上传图片预览" className="size-full object-cover" />
          ) : (
            <div className="flex h-full min-h-[260px] flex-col items-center justify-center gap-4 px-8 text-center">
              <ImagePlus className="h-12 w-12 text-slate-300" />
              <div>
                <div className="font-display text-lg font-semibold text-white">上传一张主图</div>
                <div className="mt-2 text-sm leading-6 text-slate-400">主体清晰、背景干净的图片更容易生成稳定结果。</div>
              </div>
            </div>
          )}
          <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-slate-950 via-slate-950/70 to-transparent px-4 py-4 text-sm text-slate-200">
            {fileName || "等待输入图片"}
          </div>
        </div>
      </div>
    </label>
  );
}
