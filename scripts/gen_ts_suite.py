"""Generate benchmarks/ts200: 200 TypeScript bug-fix tasks (20 bug families x 10 domains).

Each task is a small repository:
  src/<domain>/<helper>.ts      the bug lives here
  src/<domain>/service.ts       public function that uses the helper (the task's focus)
  src/<domain>/service.test.ts  node:test test of the service (the gate)
  src/<domain>/legacy.ts        a similar-looking distractor that is not used
The goal describes the symptom at the service level, not where the bug is. The reference fix is
written to benchmarks/ts200/_solutions/<task>/ (never copied into task templates) and
tests/test_ts_suite.py checks every task both ways: the gate fails as generated and passes with the
reference fix. Gates run with `node --experimental-strip-types --test` (Node >= 22.6).

These are generated, parameterised bugs — realistic in kind (off-by-one, wrong operator, swapped
bounds, nullish defaults, ...) but not mined from real projects. Usage:
  python scripts/gen_ts_suite.py [out_dir]
"""
from __future__ import annotations

from pathlib import Path
import json
import shutil
import sys

DOMAINS = [("orders", "Order"), ("invoices", "Invoice"), ("tickets", "Ticket"), ("payments", "Payment"),
           ("shipments", "Shipment"), ("products", "Product"), ("sessions", "Session"), ("reports", "Report"),
           ("coupons", "Coupon"), ("members", "Member")]


def family_line_total(d, D, i):
    price, qty = 3 + i, 2 + i % 3
    buggy = "export function lineTotal(price: number, quantity: number): number {\n  return price;\n}\n"
    fixed = "export function lineTotal(price: number, quantity: number): number {\n  return price * quantity;\n}\n"
    service = (f'import {{ lineTotal }} from "./pricing.ts";\n\nexport interface {D}Line {{ price: number; quantity: number }}\n\n'
               f"export function {d}Total(lines: {D}Line[]): number {{\n"
               "  return lines.reduce((sum, l) => sum + lineTotal(l.price, l.quantity), 0);\n}\n")
    test = (f'import {{ {d}Total }} from "./service.ts";\n'
            f'test("{d} total", () => {{\n  assert.equal({d}Total([{{ price: {price}, quantity: {qty} }}, {{ price: 1, quantity: 1 }}]), {price * qty + 1});\n}});\n')
    return "pricing.ts", buggy, fixed, service, test, f"{d}Total", f"{D} totals are too low when a line has quantity above 1."


def family_retry(d, D, i):
    n = 3 + i % 3
    buggy = ("export async function retry<T>(fn: () => Promise<T>, attempts: number): Promise<T> {\n"
             "  let last: unknown;\n  for (let i = 1; i < attempts; i++) {\n    try {\n      return await fn();\n"
             "    } catch (e) {\n      last = e;\n    }\n  }\n  throw last;\n}\n")
    fixed = buggy.replace("i < attempts", "i <= attempts")
    service = (f'import {{ retry }} from "./retry.ts";\n\nexport async function fetch{D}(load: () => Promise<string>): Promise<string> {{\n'
               f"  return retry(load, {n});\n}}\n")
    test = (f'import {{ fetch{D} }} from "./service.ts";\n'
            f'test("{d} retries", async () => {{\n  let calls = 0;\n'
            f'  const v = await fetch{D}(async () => {{ calls++; if (calls < {n}) throw new Error("flaky"); return "ok"; }});\n'
            f'  assert.equal(v, "ok");\n  assert.equal(calls, {n});\n}});\n')
    return "retry.ts", buggy, fixed, service, test, f"fetch{D}", f"fetch{D} gives up one attempt too early on flaky loads."


def family_paginate(d, D, i):
    size = 2 + i % 3
    buggy = ("export function page<T>(items: T[], page: number, size: number): T[] {\n"
             "  const start = page * size;\n  return items.slice(start, start + size);\n}\n")
    fixed = buggy.replace("page * size", "(page - 1) * size")
    service = (f'import {{ page }} from "./paging.ts";\n\nexport function list{D}s(ids: number[], p: number): number[] {{\n'
               f"  return page(ids, p, {size});\n}}\n")
    ids = list(range(1, 3 * size + 2))
    test = (f'import {{ list{D}s }} from "./service.ts";\n'
            f'test("{d} paging is 1-based", () => {{\n  const ids = {ids};\n'
            f"  assert.deepEqual(list{D}s(ids, 1), {ids[:size]});\n  assert.deepEqual(list{D}s(ids, 4), {ids[3 * size:]});\n}});\n")
    return "paging.ts", buggy, fixed, service, test, f"list{D}s", f"list{D}s skips the first page of results (pages are 1-based)."


def family_clamp(d, D, i):
    lo, hi = i, 10 + i
    buggy = "export function clamp(x: number, lo: number, hi: number): number {\n  return Math.max(hi, Math.min(lo, x));\n}\n"
    fixed = "export function clamp(x: number, lo: number, hi: number): number {\n  return Math.min(hi, Math.max(lo, x));\n}\n"
    service = (f'import {{ clamp }} from "./bounds.ts";\n\nexport function {d}Priority(raw: number): number {{\n'
               f"  return clamp(raw, {lo}, {hi});\n}}\n")
    test = (f'import {{ {d}Priority }} from "./service.ts";\n'
            f'test("{d} priority bounds", () => {{\n  assert.equal({d}Priority({lo + 3}), {lo + 3});\n'
            f"  assert.equal({d}Priority({hi + 50}), {hi});\n  assert.equal({d}Priority({lo - 5}), {lo});\n}});\n")
    return "bounds.ts", buggy, fixed, service, test, f"{d}Priority", f"{d}Priority returns the upper bound even for values inside the range."


def family_slug(d, D, i):
    buggy = ('export function slug(s: string): string {\n'
             '  return (s.match(/[A-Za-z0-9]+/g) ?? []).join("-");\n}\n')
    fixed = ('export function slug(s: string): string {\n'
             '  return (s.toLowerCase().match(/[a-z0-9]+/g) ?? []).join("-");\n}\n')
    service = (f'import {{ slug }} from "./text.ts";\n\nexport function {d}Url(title: string, id: number): string {{\n'
               f'  return `/{d}/${{id}}-${{slug(title)}}`;\n}}\n')
    test = (f'import {{ {d}Url }} from "./service.ts";\n'
            f'test("{d} url is lowercase", () => {{\n  assert.equal({d}Url("Hello World {i}", {i}), "/{d}/{i}-hello-world-{i}");\n}});\n')
    return "text.ts", buggy, fixed, service, test, f"{d}Url", f"{d}Url keeps uppercase letters; URLs must be lowercase."


def family_seconds(d, D, i):
    ms = 1000 * (i + 2)
    buggy = "export function toSeconds(ms: number): number {\n  return ms / 100;\n}\n"
    fixed = "export function toSeconds(ms: number): number {\n  return ms / 1000;\n}\n"
    service = (f'import {{ toSeconds }} from "./time.ts";\n\nexport function {d}AgeSeconds(createdMs: number, nowMs: number): number {{\n'
               "  return toSeconds(nowMs - createdMs);\n}\n")
    test = (f'import {{ {d}AgeSeconds }} from "./service.ts";\n'
            f'test("{d} age", () => {{\n  assert.equal({d}AgeSeconds(5000, {5000 + ms}), {ms // 1000});\n}});\n')
    return "time.ts", buggy, fixed, service, test, f"{d}AgeSeconds", f"{d}AgeSeconds reports ages ten times too large."


def family_sort(d, D, i):
    buggy = ("export function newestFirst<T extends { at: number }>(xs: T[]): T[] {\n"
             "  return [...xs].sort((a, b) => a.at - b.at);\n}\n")
    fixed = buggy.replace("a.at - b.at", "b.at - a.at")
    service = (f'import {{ newestFirst }} from "./order.ts";\n\nexport function recent{D}s(xs: {{ id: number; at: number }}[]): number[] {{\n'
               "  return newestFirst(xs).map((x) => x.id);\n}\n")
    test = (f'import {{ recent{D}s }} from "./service.ts";\n'
            f'test("{d} newest first", () => {{\n  assert.deepEqual(recent{D}s([{{ id: 1, at: {10 + i} }}, {{ id: 2, at: {30 + i} }}, {{ id: 3, at: {20 + i} }}]), [2, 3, 1]);\n}});\n')
    return "order.ts", buggy, fixed, service, test, f"recent{D}s", f"recent{D}s lists the oldest {d} first; it must list the newest first."


def family_active(d, D, i):
    buggy = ("export function onlyActive<T extends { active: boolean }>(xs: T[]): T[] {\n"
             "  return xs.filter((x) => !x.active);\n}\n")
    fixed = buggy.replace("!x.active", "x.active")
    service = (f'import {{ onlyActive }} from "./filters.ts";\n\nexport function active{D}Count(xs: {{ active: boolean }}[]): number {{\n'
               "  return onlyActive(xs).length;\n}\n")
    n = 2 + i % 4
    items = ", ".join(["{ active: true }"] * n + ["{ active: false }"])
    test = (f'import {{ active{D}Count }} from "./service.ts";\n'
            f'test("{d} active count", () => {{\n  assert.equal(active{D}Count([{items}]), {n});\n}});\n')
    return "filters.ts", buggy, fixed, service, test, f"active{D}Count", f"active{D}Count counts inactive {d} instead of active ones."


def family_default(d, D, i):
    buggy = "export function orDefault(v: number | undefined, fallback: number): number {\n  return v || fallback;\n}\n"
    fixed = "export function orDefault(v: number | undefined, fallback: number): number {\n  return v ?? fallback;\n}\n"
    service = (f'import {{ orDefault }} from "./defaults.ts";\n\nexport function {d}Limit(configured?: number): number {{\n'
               f"  return orDefault(configured, {50 + i});\n}}\n")
    test = (f'import {{ {d}Limit }} from "./service.ts";\n'
            f'test("{d} limit keeps explicit zero", () => {{\n  assert.equal({d}Limit(0), 0);\n'
            f"  assert.equal({d}Limit(undefined), {50 + i});\n  assert.equal({d}Limit(7), 7);\n}});\n")
    return "defaults.ts", buggy, fixed, service, test, f"{d}Limit", f"{d}Limit ignores an explicitly configured limit of 0."


def family_percent(d, D, i):
    buggy = "export function percent(part: number, whole: number): number {\n  return Math.floor((part / whole) * 100);\n}\n"
    fixed = "export function percent(part: number, whole: number): number {\n  return Math.round((part / whole) * 100);\n}\n"
    service = (f'import {{ percent }} from "./math.ts";\n\nexport function {d}Progress(done: number, total: number): number {{\n'
               "  return percent(done, total);\n}\n")
    test = (f'import {{ {d}Progress }} from "./service.ts";\n'
            f'test("{d} progress rounds to nearest", () => {{\n  assert.equal({d}Progress(2, 3), 67);\n'
            f"  assert.equal({d}Progress(1, 8), 13);\n}});\n")
    return "math.ts", buggy, fixed, service, test, f"{d}Progress", f"{d}Progress truncates percentages; it must round to the nearest integer."


def family_dedupe(d, D, i):
    buggy = ("export function dedupe<T extends { id: number }>(xs: T[]): T[] {\n"
             "  const m = new Map<number, T>();\n  for (const x of xs) m.set(x.id, x);\n  return [...m.values()];\n}\n")
    fixed = ("export function dedupe<T extends { id: number }>(xs: T[]): T[] {\n"
             "  const m = new Map<number, T>();\n  for (const x of xs) if (!m.has(x.id)) m.set(x.id, x);\n  return [...m.values()];\n}\n")
    service = (f'import {{ dedupe }} from "./unique.ts";\n\nexport function first{D}Versions(xs: {{ id: number; v: string }}[]): string[] {{\n'
               "  return dedupe(xs).map((x) => x.v);\n}\n")
    test = (f'import {{ first{D}Versions }} from "./service.ts";\n'
            f'test("{d} keeps first occurrence", () => {{\n'
            f'  assert.deepEqual(first{D}Versions([{{ id: 1, v: "a{i}" }}, {{ id: 2, v: "b" }}, {{ id: 1, v: "c" }}]), ["a{i}", "b"]);\n}});\n')
    return "unique.ts", buggy, fixed, service, test, f"first{D}Versions", f"first{D}Versions keeps the last duplicate; it must keep the first one."


def family_average(d, D, i):
    buggy = "export function average(xs: number[]): number {\n  return xs.reduce((a, b) => a + b, 0) / xs.length;\n}\n"
    fixed = ("export function average(xs: number[]): number {\n  if (xs.length === 0) return 0;\n"
             "  return xs.reduce((a, b) => a + b, 0) / xs.length;\n}\n")
    service = (f'import {{ average }} from "./stats.ts";\n\nexport function average{D}Value(xs: number[]): number {{\n'
               "  return average(xs);\n}\n")
    test = (f'import {{ average{D}Value }} from "./service.ts";\n'
            f'test("{d} average", () => {{\n  assert.equal(average{D}Value([]), 0);\n  assert.equal(average{D}Value([{i}, {i + 2}]), {i + 1});\n}});\n')
    return "stats.ts", buggy, fixed, service, test, f"average{D}Value", f"average{D}Value returns NaN for an empty list; it must return 0."


def family_chunk(d, D, i):
    n = 2 + i % 3
    buggy = ("export function chunk<T>(xs: T[], n: number): T[][] {\n  const out: T[][] = [];\n"
             "  for (let i = 0; i + n <= xs.length; i += n) out.push(xs.slice(i, i + n));\n  return out;\n}\n")
    fixed = buggy.replace("i + n <= xs.length", "i < xs.length")
    service = (f'import {{ chunk }} from "./batch.ts";\n\nexport function {d}Batches(ids: number[]): number[][] {{\n'
               f"  return chunk(ids, {n});\n}}\n")
    ids = list(range(1, 2 * n + 2))
    expected = [ids[k:k + n] for k in range(0, len(ids), n)]
    test = (f'import {{ {d}Batches }} from "./service.ts";\n'
            f'test("{d} batches keep the remainder", () => {{\n  assert.deepEqual({d}Batches({ids}), {json.dumps(expected)});\n}});\n')
    return "batch.ts", buggy, fixed, service, test, f"{d}Batches", f"{d}Batches drops the last, smaller batch."


def family_capitalize(d, D, i):
    buggy = ('export function titleCase(s: string): string {\n  return s.split(" ").map((w, i) =>\n'
             '    i > 0 ? w.charAt(0).toUpperCase() + w.slice(1) : w).join(" ");\n}\n')
    fixed = ('export function titleCase(s: string): string {\n  return s.split(" ").map((w) =>\n'
             '    w.charAt(0).toUpperCase() + w.slice(1)).join(" ");\n}\n')
    service = (f'import {{ titleCase }} from "./case.ts";\n\nexport function {d}Heading(name: string): string {{\n'
               "  return titleCase(name);\n}\n")
    test = (f'import {{ {d}Heading }} from "./service.ts";\n'
            f'test("{d} heading", () => {{\n  assert.equal({d}Heading("annual {d} report"), "Annual {d.capitalize()} Report");\n}});\n')
    return "case.ts", buggy, fixed, service, test, f"{d}Heading", f"{d}Heading leaves the first word lowercase."


def family_divide(d, D, i):
    buggy = "export function ratio(a: number, b: number): number {\n  return a / b;\n}\n"
    fixed = "export function ratio(a: number, b: number): number {\n  return b === 0 ? 0 : a / b;\n}\n"
    service = (f'import {{ ratio }} from "./ratio.ts";\n\nexport function {d}ConversionRate(won: number, seen: number): number {{\n'
               "  return ratio(won, seen);\n}\n")
    test = (f'import {{ {d}ConversionRate }} from "./service.ts";\n'
            f'test("{d} conversion", () => {{\n  assert.equal({d}ConversionRate({i}, 0), 0);\n  assert.equal({d}ConversionRate(1, 4), 0.25);\n}});\n')
    return "ratio.ts", buggy, fixed, service, test, f"{d}ConversionRate", f"{d}ConversionRate returns Infinity when nothing was seen; it must return 0."


def family_range(d, D, i):
    buggy = ("export function range(start: number, end: number): number[] {\n  const out: number[] = [];\n"
             "  for (let i = start; i < end; i++) out.push(i);\n  return out;\n}\n")
    fixed = buggy.replace("i < end", "i <= end")
    service = (f'import {{ range }} from "./range.ts";\n\nexport function {d}Years(from: number, to: number): number[] {{\n'
               "  return range(from, to);\n}\n")
    a = 2020 + i
    test = (f'import {{ {d}Years }} from "./service.ts";\n'
            f'test("{d} years inclusive", () => {{\n  assert.deepEqual({d}Years({a}, {a + 2}), [{a}, {a + 1}, {a + 2}]);\n}});\n')
    return "range.ts", buggy, fixed, service, test, f"{d}Years", f"{d}Years misses the last year; the range must be inclusive."


def family_group(d, D, i):
    buggy = ("export function countBy<T extends { id: string; category: string }>(xs: T[]): Record<string, number> {\n"
             "  const out: Record<string, number> = {};\n  for (const x of xs) out[x.id] = (out[x.id] ?? 0) + 1;\n  return out;\n}\n")
    fixed = buggy.replace("out[x.id] = (out[x.id] ?? 0)", "out[x.category] = (out[x.category] ?? 0)")
    service = (f'import {{ countBy }} from "./group.ts";\n\nexport function {d}PerCategory(xs: {{ id: string; category: string }}[]): Record<string, number> {{\n'
               "  return countBy(xs);\n}\n")
    test = (f'import {{ {d}PerCategory }} from "./service.ts";\n'
            f'test("{d} per category", () => {{\n'
            f'  assert.deepEqual({d}PerCategory([{{ id: "a", category: "x{i}" }}, {{ id: "b", category: "x{i}" }}, {{ id: "c", category: "y" }}]), {{ x{i}: 2, y: 1 }});\n}});\n')
    return "group.ts", buggy, fixed, service, test, f"{d}PerCategory", f"{d}PerCategory counts per id instead of per category."


def family_truncate(d, D, i):
    m = 8 + i
    buggy = ('export function truncate(s: string, max: number): string {\n'
             '  return s.length <= max ? s : s.slice(0, max) + "…";\n}\n')
    fixed = ('export function truncate(s: string, max: number): string {\n'
             '  return s.length <= max ? s : s.slice(0, max - 1) + "…";\n}\n')
    service = (f'import {{ truncate }} from "./truncate.ts";\n\nexport function {d}Preview(text: string): string {{\n'
               f"  return truncate(text, {m});\n}}\n")
    test = (f'import {{ {d}Preview }} from "./service.ts";\n'
            f'test("{d} preview fits", () => {{\n  const p = {d}Preview("x".repeat({m + 10}));\n'
            f'  assert.equal(p.length, {m});\n  assert.ok(p.endsWith("…"));\n  assert.equal({d}Preview("short"), "short");\n}});\n')
    return "truncate.ts", buggy, fixed, service, test, f"{d}Preview", f"{d}Preview is one character longer than the limit when it truncates."


def family_query(d, D, i):
    buggy = ('export function parseQuery(q: string): Record<string, string> {\n  const out: Record<string, string> = {};\n'
             '  for (const part of q.replace(/^\\?/, "").split("&")) {\n    if (!part) continue;\n'
             '    const [k, v = ""] = part.split("=");\n    out[k] = v;\n  }\n  return out;\n}\n')
    fixed = buggy.replace("out[k] = v;", "out[decodeURIComponent(k)] = decodeURIComponent(v.replace(/\\+/g, \" \"));")
    service = (f'import {{ parseQuery }} from "./query.ts";\n\nexport function {d}Search(url: string): string {{\n'
               '  return parseQuery(url.split("?")[1] ?? "").q ?? "";\n}\n')
    test = (f'import {{ {d}Search }} from "./service.ts";\n'
            f'test("{d} search decodes", () => {{\n  assert.equal({d}Search("/{d}?q=caf%C3%A9+{i}%26co"), "café {i}&co");\n}});\n')
    return "query.ts", buggy, fixed, service, test, f"{d}Search", f"{d}Search returns the raw percent-encoded query instead of the decoded text."


def family_tax(d, D, i):
    rate, disc = 20 + i, 10
    buggy = ("export function finalPrice(net: number, discountPct: number, taxPct: number): number {\n"
             "  const taxed = net * (1 + taxPct / 100);\n  return Math.round((taxed - net * discountPct / 100) * 100) / 100;\n}\n")
    fixed = ("export function finalPrice(net: number, discountPct: number, taxPct: number): number {\n"
             "  const discounted = net * (1 - discountPct / 100);\n  return Math.round(discounted * (1 + taxPct / 100) * 100) / 100;\n}\n")
    service = (f'import {{ finalPrice }} from "./tax.ts";\n\nexport function {d}Gross(net: number): number {{\n'
               f"  return finalPrice(net, {disc}, {rate});\n}}\n")
    expected = round(100 * (1 - disc / 100) * (1 + rate / 100), 2)
    test = (f'import {{ {d}Gross }} from "./service.ts";\n'
            f'test("{d} gross applies discount before tax", () => {{\n  assert.equal({d}Gross(100), {expected});\n}});\n')
    return "tax.ts", buggy, fixed, service, test, f"{d}Gross", f"{d}Gross is wrong: the {disc}% discount must be applied to the net price before {rate}% tax."


FAMILIES = [family_line_total, family_retry, family_paginate, family_clamp, family_slug, family_seconds,
            family_sort, family_active, family_default, family_percent, family_dedupe, family_average,
            family_chunk, family_capitalize, family_divide, family_range, family_group, family_truncate,
            family_query, family_tax]

TEST_HEADER = 'import { test } from "node:test";\nimport assert from "node:assert/strict";\n'
DISTRACTOR = ("// Legacy helpers kept for an old export job. Not used by service.ts.\n"
              "export function legacyFormat(x: number): string {\n  return x.toFixed(2);\n}\n")


def generate(out: Path) -> list[dict]:
    if out.exists():
        shutil.rmtree(out)
    (out / "_solutions").mkdir(parents=True)
    tasks = []
    for f_index, family in enumerate(FAMILIES):
        for i, (d, D) in enumerate(DOMAINS):
            helper, buggy, fixed, service, test, fn, goal = family(d, D, i)
            task_id = f"{f_index + 1:02d}-{family.__name__.removeprefix('family_').replace('_', '-')}-{d}"
            base = out / task_id / "src" / d
            base.mkdir(parents=True)
            (base / helper).write_text(buggy, encoding="utf-8")
            (base / "service.ts").write_text(service, encoding="utf-8")
            (base / "service.test.ts").write_text(TEST_HEADER + test, encoding="utf-8")
            (base / "legacy.ts").write_text(DISTRACTOR, encoding="utf-8")
            (out / task_id / "package.json").write_text('{"type": "module", "private": true}\n', encoding="utf-8")
            sol = out / "_solutions" / task_id / "src" / d
            sol.mkdir(parents=True)
            (sol / helper).write_text(fixed, encoding="utf-8")
            tasks.append({"id": task_id, "dir": task_id, "goal": goal, "family": family.__name__[7:],
                          "focus": [f"src/{d}/service.ts:{fn}"],
                          "gates": [["node", "--experimental-strip-types", "--test", f"src/{d}/service.test.ts"]],
                          "solution": f"_solutions/{task_id}"})
    suite = {"name": "ts200",
             "description": "200 generated TypeScript bug-fix tasks: 20 bug families x 10 domains. The bug is in a "
                            "helper; the goal describes the symptom at the service. See scripts/gen_ts_suite.py.",
             "requires": "node >= 22.6 (type stripping)", "tasks": tasks}
    (out / "suite.json").write_text(json.dumps(suite, indent=1) + "\n", encoding="utf-8")
    return tasks


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "benchmarks/ts200")
    print(f"generated {len(generate(target))} tasks in {target}")
