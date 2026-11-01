import { percent } from "./math.ts";

export function productsProgress(done: number, total: number): number {
  return percent(done, total);
}
