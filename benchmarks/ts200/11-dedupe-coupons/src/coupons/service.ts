import { dedupe } from "./unique.ts";

export function firstCouponVersions(xs: { id: number; v: string }[]): string[] {
  return dedupe(xs).map((x) => x.v);
}
