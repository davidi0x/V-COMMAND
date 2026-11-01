import { titleCase } from "./case.ts";

export function sessionsHeading(name: string): string {
  return titleCase(name);
}
