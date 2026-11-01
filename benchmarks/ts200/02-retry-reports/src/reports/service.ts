import { retry } from "./retry.ts";

export async function fetchReport(load: () => Promise<string>): Promise<string> {
  return retry(load, 4);
}
