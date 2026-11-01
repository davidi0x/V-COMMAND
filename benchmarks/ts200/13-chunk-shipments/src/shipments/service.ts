import { chunk } from "./batch.ts";

export function shipmentsBatches(ids: number[]): number[][] {
  return chunk(ids, 3);
}
