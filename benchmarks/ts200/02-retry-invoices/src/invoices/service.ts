import { retry } from "./retry.ts";

export async function fetchInvoice(load: () => Promise<string>): Promise<string> {
  return retry(load, 4);
}
