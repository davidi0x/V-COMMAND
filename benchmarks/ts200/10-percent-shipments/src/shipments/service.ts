import { percent } from "./math.ts";

export function shipmentsProgress(done: number, total: number): number {
  return percent(done, total);
}
