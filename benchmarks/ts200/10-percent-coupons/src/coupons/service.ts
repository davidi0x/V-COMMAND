import { percent } from "./math.ts";

export function couponsProgress(done: number, total: number): number {
  return percent(done, total);
}
