import { titleCase } from "./case.ts";

export function paymentsHeading(name: string): string {
  return titleCase(name);
}
