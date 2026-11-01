import { percent } from "./math.ts";

export function invoicesProgress(done: number, total: number): number {
  return percent(done, total);
}
