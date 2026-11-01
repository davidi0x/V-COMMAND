import { retry } from "./retry.ts";

export async function fetchSession(load: () => Promise<string>): Promise<string> {
  return retry(load, 3);
}
