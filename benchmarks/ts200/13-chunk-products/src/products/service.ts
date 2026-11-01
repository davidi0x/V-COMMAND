import { chunk } from "./batch.ts";

export function productsBatches(ids: number[]): number[][] {
  return chunk(ids, 4);
}
