import { chunk } from "./batch.ts";

export function paymentsBatches(ids: number[]): number[][] {
  return chunk(ids, 2);
}
