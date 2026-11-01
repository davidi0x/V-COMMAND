import { percent } from "./math.ts";

export function sessionsProgress(done: number, total: number): number {
  return percent(done, total);
}
