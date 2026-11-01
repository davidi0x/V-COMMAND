import { percent } from "./math.ts";

export function membersProgress(done: number, total: number): number {
  return percent(done, total);
}
