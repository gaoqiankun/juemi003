import { resolveViewerData } from "@/data/user-mocks";

export function useViewerData(taskId: string) {
  return resolveViewerData(taskId);
}
