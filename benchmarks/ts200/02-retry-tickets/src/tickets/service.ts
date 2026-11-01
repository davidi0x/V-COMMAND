import { retry } from "./retry.ts";

export async function fetchTicket(load: () => Promise<string>): Promise<string> {
  return retry(load, 5);
}
