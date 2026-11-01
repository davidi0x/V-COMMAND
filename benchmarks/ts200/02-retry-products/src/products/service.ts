import { retry } from "./retry.ts";

export async function fetchProduct(load: () => Promise<string>): Promise<string> {
  return retry(load, 5);
}
