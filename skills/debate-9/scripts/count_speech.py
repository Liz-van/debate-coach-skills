#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""辩手发言前的字数自查：把环节时长换算成字数区间，稿子写完先跑这个再上场。

用法:
  count_speech.py --list                       打印全部环节的时长与字数区间
  count_speech.py <草稿.md> --unit <环节名> [--part <小节标题关键字>]
  count_speech.py <草稿.md> --seconds <秒数>   按时长临时算区间
  count_speech.py --dir <辩手资料目录>          一份持方的口播稿批量自查

计字规则（口径见 speech_bands.py）:
  立论类稿只算「该环节自己那段」——一辩立论稿数立论正文、二辩申论稿数申论正文、
  三辩小结稿数整份、四辩结辩稿数结辩正文。标题含「答话 / 质询 / 预计回答」的小节
  整节不计入：那是现场短攻防的备用弹药，不该偷走立论的时间预算。
  要点类稿（三辩质询稿、自由辩要点）不卡字数——质询与自由辩是现场短攻防，
  辩手按对方刚说的话临时调整，字数改在《辩论实录》里按每方实际发言总量卡。

字数口径：去掉全部空白字符后的字符数（含标点），与立论报告同一套。
换算基准：260 字/分钟，区间 = 中心 ±10%。

退出码: 0 全部落在区间 / 1 有出区间的稿子 / 2 输入或调用错误
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import speech_bands as sb  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BAD = []


def say(msg=""):
    print(msg)


def fail(msg):
    BAD.append(msg)
    say(f"  ✗ {msg}")


def read_text(path):
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            return f.read()
    except Exception as e:  # noqa: BLE001
        say(f"✗ 读不了 {path}：{e}")
        return None


def show_table():
    say(f"口播稿字数区间（{sb.RATE} 字/分钟，中心 ±10%，去空白字符数含标点）")
    say("")
    say(f"  {'环节':<8} {'时长':>5}  {'字数区间':<12} {'谁':<12} 稿子")
    for ph in sb.PHASE_ORDER:
        u = sb.UNITS[ph]
        dur = f"{u['seconds']}s"
        say(f"  {ph:<8} {dur:>5}  {u['lo']}–{u['hi']:<8} {u['who']:<12} {u['file']}")
        if u["note"]:
            say(f"  {'':<8} {'':>5}  {u['note']}")
    say("")
    say(f"  立论类稿（{'、'.join(sb.BANDED_FILES)}）只算「自己那段」：答话、质询小节整节不计入")
    say(f"  要点类稿（{'、'.join(sb.NOTE_FILES)}）不卡字数：质询与自由辩是现场短攻防，")
    say(f"  字数在《辩论实录》里按每方实际发言总量卡（质询每方 {sb.ASK_LO}–{sb.ASK_HI} 字）")
    say("")


def check_one(title, text, lo, hi):
    n = sb.word_count(text)
    ok, why = sb.verdict(n, lo, hi)
    if ok:
        say(f"  ✓ {title}：{n} 字（区间 {lo}–{hi}），{why}")
        return True
    fail(f"{title}：{n} 字，{why}")
    return False


def run_dir(dirpath):
    if not os.path.isdir(dirpath):
        say(f"✗ 不是目录：{dirpath}")
        return 2
    say(f"== 口播稿字数自查 · {dirpath} ==")
    names = os.listdir(dirpath)
    for key, ph in sb.BANDED_FILES.items():
        hit = [fn for fn in names if key in fn and fn.lower().endswith(".md")]
        if not hit:
            fail(f"找不到含「{key}」的 md")
            continue
        text = read_text(os.path.join(dirpath, hit[0]))
        if text is None:
            fail(f"读不了 {hit[0]}")
            continue
        u = sb.UNITS[ph]
        n = sb.script_words(text)
        ok, why = sb.verdict(n, u["lo"], u["hi"])
        label = f"{hit[0]}[{ph}]"
        if ok:
            say(f"  ✓ {label}：{n} 字（区间 {u['lo']}–{u['hi']}），{why}")
        else:
            fail(f"{label}：{n} 字，{why}（答话/质询段已剔除，不计入）")
    for key in sb.NOTE_FILES:
        hit = [fn for fn in names if key in fn and fn.lower().endswith(".md")]
        if not hit:
            say(f"  · 没有「{key}」（要点类稿不卡字数，可以不交）")
            continue
        text = read_text(os.path.join(dirpath, hit[0]))
        if text is None:
            continue
        say(f"  · {hit[0]}：{sb.word_count(text)} 字，要点类不卡字数"
            f"（该环节按每方实际发言总量卡）")
    return finish()


def finish():
    say("")
    if BAD:
        say(f"✗ 有 {len(BAD)} 处出区间，先改稿再上场")
        return 1
    say("✓ 全部落在字数区间内")
    return 0


def main():
    ap = argparse.ArgumentParser(description="辩手发言前的字数自查（时长 → 字数区间）")
    ap.add_argument("file", nargs="?", help="草稿 md")
    ap.add_argument("--unit", choices=list(sb.UNITS), help="环节名（按它的时长与区间判）")
    ap.add_argument("--part", help="只数标题含这个关键字的某一节（如 结辩 / 质询）")
    ap.add_argument("--seconds", type=int, help="按时长临时算区间（不认 --unit 时用）")
    ap.add_argument("--dir", help="辩手资料目录：批量自查这一方的六份口播稿")
    ap.add_argument("--list", action="store_true", dest="show_list", help="打印全部环节的字数区间")
    args = ap.parse_args()

    if args.show_list:
        show_table()
        return 0

    if args.dir:
        return run_dir(args.dir)

    if not args.file:
        ap.print_help()
        return 2
    text = read_text(args.file)
    if text is None:
        return 2

    if args.part:
        sec = sb.section_text(text, args.part)
        if sec is None:
            say(f"✗ {args.file} 里找不到标题含「{args.part}」的一节")
            return 2
        text = sec
        label = os.path.basename(args.file) + f"·{args.part}节"
    else:
        label = os.path.basename(args.file)
        if args.unit in sb.BANDED_FILES.values():
            text = sb.counted_text(text)
            label += "（只算该环节自己那段，答话/质询段已剔除）"

    if args.unit:
        u = sb.UNITS[args.unit]
        lo, hi = u["lo"], u["hi"]
        say(f"== {label} · {args.unit}（{u['seconds']}s）==")
    elif args.seconds:
        lo, hi, center = sb.band(args.seconds)
        say(f"== {label} · {args.seconds}s（≈{center} 字）==")
    else:
        say("✗ 要么给 --unit，要么给 --seconds")
        return 2

    check_one(label, text, lo, hi)
    return finish()


if __name__ == "__main__":
    sys.exit(main())
