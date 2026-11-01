import { dedupe } from "./unique.ts";

export function firstPaymentVersions(xs: { id: number; v: string }[]): string[] {
  return dedupe(xs).map((x) => x.v);
}
