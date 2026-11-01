import { percent } from "./math.ts";

export function ticketsProgress(done: number, total: number): number {
  return percent(done, total);
}
