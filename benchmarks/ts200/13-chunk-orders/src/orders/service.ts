import { chunk } from "./batch.ts";

export function ordersBatches(ids: number[]): number[][] {
  return chunk(ids, 2);
}
