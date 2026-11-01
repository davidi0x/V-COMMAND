import { chunk } from "./batch.ts";

export function couponsBatches(ids: number[]): number[][] {
  return chunk(ids, 4);
}
