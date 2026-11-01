import { retry } from "./retry.ts";

export async function fetchCoupon(load: () => Promise<string>): Promise<string> {
  return retry(load, 5);
}
