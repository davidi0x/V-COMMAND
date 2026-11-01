import { retry } from "./retry.ts";

export async function fetchPayment(load: () => Promise<string>): Promise<string> {
  return retry(load, 3);
}
