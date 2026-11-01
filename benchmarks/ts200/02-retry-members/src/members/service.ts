import { retry } from "./retry.ts";

export async function fetchMember(load: () => Promise<string>): Promise<string> {
  return retry(load, 3);
}
