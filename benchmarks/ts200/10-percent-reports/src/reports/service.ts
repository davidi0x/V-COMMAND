import { percent } from "./math.ts";

export function reportsProgress(done: number, total: number): number {
  return percent(done, total);
}
