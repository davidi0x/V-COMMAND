import { percent } from "./math.ts";

export function ordersProgress(done: number, total: number): number {
  return percent(done, total);
}
