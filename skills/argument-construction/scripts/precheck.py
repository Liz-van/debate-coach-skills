#!/usr/bin/env python3
"""辩论备赛资料预检：出文件前校验数据 JSON（可配合 md 报告一起查）。

用法:
  precheck.py <数据.json> [--md <报告.md>] [--tier 精简|标准|完整]
              [--no-link-check] [--allow-link-fail]

硬项（不通过 → 退出码 1，先修再出文件）:
  H1 论点 sheet 数 ≥ 3（论点数量三档一致，固定 3 个）
  H2 每个论点 sheet 的证据行 ≥ 档位下限
  H3 来源索引条数 ≥ 档位下限
  H4 有「来源」列的 sheet 中，来源单元格不得为空
  H5 来源索引编号不得重复
  H6 链接必须可达（403/405/429/999 视为反爬可疑，仅告警）

软项（告警，不阻断）:
  S1 md 正文引用的 [n] 是否都在来源索引里
  S2 md 是否残留「辩称」等战斗化措辞
  S3 来源编号是否连续

退出码: 0 通过 / 1 硬项失败 / 2 输入或调用错误
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

# Windows 控制台默认 GBK，✓/✗ 会 UnicodeEncodeError；统一按 UTF-8 输出（stderr 同理，argparse 用法提示也走它）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

TIERS = {
    "精简": {"arguments": 3, "per_argument": 2, "sources": 6},
    "标准": {"arguments": 3, "per_argument": 2, "sources": 8},
    "完整": {"arguments": 3, "per_argument": 3, "sources": 12},
}

SOURCE_SHEET = "来源索引"
URL_RE = re.compile(r"https?://[^\s，。；、）)】\]\"'<>]+")
REF_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
BLOCKED_STATUS = {401, 403, 405, 406, 429, 999}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

HARD_FAIL = []
WARN = []


def rows_of(sheet):
    """数据行（剔除 divider / summary 装饰行）。"""
    out = []
    for r in sheet.get("rows", []):
        if isinstance(r, dict) and ("divider" in r or "summary" in r):
            continue
        out.append(r)
    return out


def col_index(headers, *keys):
    for i, h in enumerate(headers):
        if any(k in str(h) for k in keys):
            return i
    return None


def cell(row, idx):
    if idx is None or idx >= len(row):
        return ""
    v = row[idx]
    return "" if v is None else str(v).strip()


def collect_urls(sheets):
    urls = set()
    for s in sheets:
        for r in rows_of(s):
            for v in r:
                if isinstance(v, str):
                    urls.update(URL_RE.findall(v))
    return sorted(urls)


def probe(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return url, resp.status
    except urllib.error.HTTPError as e:
        return url, e.code
    except Exception:  # noqa: BLE001 - 网络层异常（DNS/超时/连接）统一记为 0
        return url, 0


def norm_ids(values):
    ids = []
    for v in values:
        m = re.search(r"\d+", str(v))
        if m:
            ids.append(int(m.group()))
    return ids


def main():
    ap = argparse.ArgumentParser(description="辩论备赛资料预检")
    ap.add_argument("data", help="数据 JSON（同 generate_report.py xlsx）")
    ap.add_argument("--md", help="报告 Markdown，用于交叉检查引用编号")
    ap.add_argument("--tier", default="标准", choices=list(TIERS))
    ap.add_argument("--no-link-check", action="store_true")
    ap.add_argument("--allow-link-fail", action="store_true",
                    help="链接失败降级为告警（默认硬失败）")
    args = ap.parse_args()

    try:
        with open(args.data, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:  # noqa: BLE001
        print(f"✗ 无法读取数据 JSON：{e}")
        return 2

    sheets = data.get("sheets", [])
    if not sheets:
        print("✗ 数据 JSON 里没有 sheets")
        return 2

    tier = TIERS[args.tier]
    names = [str(s.get("name", "")) for s in sheets]
    print(f"== precheck · 档位 {args.tier} · sheet {len(names)} 个 ==")

    # H1 论点 sheet 数
    arg_sheets = [s for s in sheets if str(s.get("name", "")).startswith("论点")]
    n_arg = len(arg_sheets)
    line = (f"H1 论点 sheet 数 {n_arg}（下限 {tier['arguments']}）")
    if n_arg >= tier["arguments"]:
        print(f"  ✓ {line}")
    else:
        print(f"  ✗ {line}")
        HARD_FAIL.append(line)

    # H2 每论点证据行
    for s in arg_sheets:
        n = len(rows_of(s))
        line = f"H2 {s.get('name')} 证据行 {n}（下限 {tier['per_argument']}）"
        if n >= tier["per_argument"]:
            print(f"  ✓ {line}")
        else:
            print(f"  ✗ {line}")
            HARD_FAIL.append(line)

    # H3 来源索引条数
    src_sheet = next((s for s in sheets if str(s.get("name", "")) == SOURCE_SHEET), None)
    src_ids = []
    if src_sheet is None:
        line = f"H3 缺少「{SOURCE_SHEET}」sheet"
        print(f"  ✗ {line}")
        HARD_FAIL.append(line)
    else:
        src_rows = rows_of(src_sheet)
        line = f"H3 {SOURCE_SHEET} 条数 {len(src_rows)}（下限 {tier['sources']}）"
        if len(src_rows) >= tier["sources"]:
            print(f"  ✓ {line}")
        else:
            print(f"  ✗ {line}")
            HARD_FAIL.append(line)
        sidx = col_index(src_sheet.get("headers", []), "编号")
        src_ids = norm_ids(cell(r, sidx) for r in src_rows)
        dup = sorted({i for i in src_ids if src_ids.count(i) > 1})
        line = f"H5 {SOURCE_SHEET} 编号重复 {dup if dup else '无'}"
        if dup:
            print(f"  ✗ {line}")
            HARD_FAIL.append(line)
        else:
            print(f"  ✓ {line}")
        if src_ids and sorted(src_ids) != list(range(min(src_ids), min(src_ids) + len(src_ids))):
            WARN.append(f"S3 {SOURCE_SHEET} 编号不连续：{sorted(src_ids)}")

    # H4 来源列不得为空
    empty_refs = []
    for s in sheets:
        headers = s.get("headers", [])
        idx = col_index(headers, "来源")
        if idx is None:
            continue
        for r in rows_of(s):
            if not cell(r, idx):
                empty_refs.append(f"{s.get('name')}·{cell(r, 0) or '?'}")
    line = f"H4 来源单元格为空 {len(empty_refs)} 处"
    if empty_refs:
        print(f"  ✗ {line}：{', '.join(empty_refs[:8])}")
        HARD_FAIL.append(line)
    else:
        print(f"  ✓ {line}")

    # H6 链接可达
    urls = collect_urls(sheets)
    if args.no_link_check:
        print(f"  – H6 链接检查已跳过（共 {len(urls)} 条）")
    elif not urls:
        print("  ⚠ H6 未发现任何链接")
        WARN.append("H6 数据中没有 URL")
    else:
        with ThreadPoolExecutor(max_workers=8) as ex:
            results = dict(ex.map(probe, urls))
        bad, blocked = [], []
        for u, st in results.items():
            if isinstance(st, int) and 200 <= st < 400:
                continue
            (blocked if st in BLOCKED_STATUS else bad).append(f"{u} → {st}")
        if blocked:
            WARN.append(f"H6 疑似反爬 {len(blocked)} 条：{'; '.join(blocked[:3])}")
        line = f"H6 链接可达（共 {len(urls)}，打不开 {len(bad)}）"
        if bad and not args.allow_link_fail:
            print(f"  ✗ {line}")
            for b in bad[:8]:
                print(f"      - {b}")
            HARD_FAIL.append(line)
        elif bad:
            print(f"  ⚠ {line}（已降级为告警）")
            WARN.append(line)
        else:
            print(f"  ✓ {line}")

    # S1/S2 md 交叉检查
    if args.md:
        try:
            with open(args.md, encoding="utf-8") as f:
                md = f.read()
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ 无法读取 md：{e}")
            return 2
        cited = set()
        for m in REF_RE.finditer(md):
            cited.update(int(x) for x in m.group(1).split(",") if x.strip().isdigit())
        missing = sorted(cited - set(src_ids))
        line = f"S1 md 引用 {len(cited)} 个编号，来源索引缺 {missing if missing else '无'}"
        if missing:
            print(f"  ⚠ {line}")
            WARN.append(line)
        else:
            print(f"  ✓ {line}")
        unused = sorted(set(src_ids) - cited)
        if unused:
            WARN.append(f"S1 来源索引中未被引用：{unused}")
        if "辩称" in md:
            print("  ⚠ S2 md 残留「辩称」等战斗化措辞")
            WARN.append("S2 残留战斗化措辞")

    print()
    if WARN:
        print("告警：")
        for w in WARN:
            print(f"  ⚠ {w}")
    if HARD_FAIL:
        print(f"\n✗ 硬项失败 {len(HARD_FAIL)} 项，先修再出文件")
        return 1
    print("\n✓ 预检通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
