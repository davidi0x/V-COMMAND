import { percent } from "./math.ts";

export function paymentsProgress(done: number, total: number): number {
  return percent(done, total);
}
