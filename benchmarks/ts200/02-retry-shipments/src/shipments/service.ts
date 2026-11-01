import { retry } from "./retry.ts";

export async function fetchShipment(load: () => Promise<string>): Promise<string> {
  return retry(load, 4);
}
