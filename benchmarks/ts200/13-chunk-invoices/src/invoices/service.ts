import { chunk } from "./batch.ts";

export function invoicesBatches(ids: number[]): number[][] {
  return chunk(ids, 3);
}
