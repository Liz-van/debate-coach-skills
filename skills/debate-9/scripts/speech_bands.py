# -*- coding: utf-8 -*-
"""口播稿字数区间（时长换算）——check_match.py 与 count_speech.py 共用这一份真源。

换算基准：260 字/分钟（辩论语速）。区间 = 中心值 ±10%，取整到 10。
字数口径：去掉全部空白字符后的字符数（含标点）——和立论报告字数同一套算法。

计了两类东西，别混：
  1) 立论类稿（BANDED_FILES）：字数只算「该环节自己那段」。一辩立论稿只数立论正文、
     二辩申论稿只数申论正文、三辩小结稿整份、四辩结辩稿只数结辩正文。
     「被质询时的答话」「质询」这类小节是现场短攻防的备用，整节不计入任何区间——
     否则立论会被答话偷走预算（真实教训：反方一辩立论稿 856 字里 152 字是答话，
     上限 860 只剩 4 字余量，只好删垫字）。
  2) 要点类稿（NOTE_FILES）：质询与自由辩是现场短攻防，辩手按对方刚说的话临时调整，
     交付的只是「要点·弹药库」，不卡字数（NOTE_FILES）。这两个环节的字数改在
     《辩论实录》里按「每方实际发言总量」卡（质询每方 ASK_LO–ASK_HI、自由辩每方
     该环节的 lo–hi）。

基准改了只要改这个文件：RATE、UNITS、BANDED_FILES 三处。
"""

import re

RATE = 260  # 字/分钟
WS_RE = re.compile(r"\s+")


def word_count(text):
    """去掉全部空白字符后的字符数（含标点）。"""
    return len(WS_RE.sub("", text))


def band(seconds, pct=0.10):
    """按时长算字数区间：(下限, 上限, 中心)。"""
    center = seconds * RATE / 60.0
    lo = int(round(center * (1 - pct) / 10.0)) * 10
    hi = int(round(center * (1 + pct) / 10.0)) * 10
    return lo, hi, int(round(center))


# 环节 → 时长与字数区间。note 里写清「问与答共用时间」这类特殊规则。
# file 一栏说清这一段的字数到底落在哪份稿子的哪一部分（立论类按段落判）。
UNITS = {
    "一辩立论": {"seconds": 180, "lo": 700, "hi": 860, "who": "正/反一辩",
                 "file": "一辩立论稿.md 的立论正文（答话段不计）", "note": ""},
    "四质询一": {"seconds": 90, "lo": 350, "hi": 430, "who": "四辩问一辩",
                 "file": "实录里按每方实际发言总量卡；四辩结辩稿只写要点",
                 "note": "问与答共用 90 秒，现场短攻防、可追问：实录里质询方与被质询方各 175–215 字，"
                         "交付的稿子只写要点不卡字数"},
    "二辩申论": {"seconds": 120, "lo": 470, "hi": 570, "who": "正/反二辩",
                 "file": "二辩申论稿.md 的申论正文（答话段不计）", "note": ""},
    "三质询二": {"seconds": 90, "lo": 350, "hi": 430, "who": "三辩问二辩",
                 "file": "实录里按每方实际发言总量卡；三辩质询稿只写要点",
                 "note": "问与答共用 90 秒，现场短攻防、可追问：实录里质询方与被质询方各 175–215 字，"
                         "交付的稿子只写要点不卡字数"},
    "三辩小结": {"seconds": 120, "lo": 470, "hi": 570, "who": "正/反三辩",
                 "file": "三辩小结稿.md（整份）", "note": ""},
    "自由辩论": {"seconds": 240, "lo": 940, "hi": 1140, "who": "四个辩手轮转",
                 "file": "实录里按每方实际发言总量卡；自由辩要点只写弹药库",
                 "note": "每方 4 分钟，现场短攻防：实录里每方 940–1140 字，"
                         "自由辩要点不卡字数（单个时间片 20–40 秒 ≈ 80–190 字）"},
    "结辩": {"seconds": 180, "lo": 700, "hi": 860, "who": "正/反四辩",
             "file": "四辩结辩稿.md 的结辩正文（质询段不计）", "note": ""},
}

# 质询环节单方（问 / 答）的字数区间：90 秒里问与答各占一半
ASK_LO, ASK_HI = 175, 215

# 辩论环节的固定顺序（与 check_match.py 的 SEG_SPEC 同序，只取 phase）
PHASE_ORDER = ("一辩立论", "四质询一", "二辩申论", "三质询二", "三辩小结", "自由辩论", "结辩")

# 立论类稿 → 它要卡的那个环节。字数只算这稿「自己那段」（见 counted_text）。
BANDED_FILES = {
    "一辩立论稿": "一辩立论",
    "二辩申论稿": "二辩申论",
    "三辩小结稿": "三辩小结",
    "四辩结辩稿": "结辩",
}

# 要点类稿：质询与自由辩现场短攻防用的弹药库，不卡字数
# （这两个环节的字数改在《辩论实录》里按每方实际发言总量卡）
NOTE_FILES = ("三辩质询稿", "自由辩要点")

# 立论类稿里，标题命中这些字的小节整节不计入立论时长
EXCLUDE_SECTION_KEYS = ("答话", "质询", "预计回答")


def heading_level(line):
    t = line.lstrip()
    n = 0
    while n < len(t) and t[n] == "#":
        n += 1
    if 0 < n <= 6 and len(t) > n and t[n] in " \t":
        return n
    return 0


def section_text(text, key):
    """截出标题含 key 的那一节正文（含其下的子标题），到同级或更高级标题为止；找不到返回 None。

    只看二级及更深的标题：文稿的一级标题是文件名（比如「# 四辩结辩稿」），
    它里面就含「结辩」二字，不能让文件名冒充小节标题。
    """
    if not text:
        return None
    lines = text.splitlines()
    start = lvl = None
    for i, ln in enumerate(lines):
        jl = heading_level(ln)
        if jl >= 2 and key in ln:
            start, lvl = i + 1, jl
            break
    if start is None:
        return None
    for j in range(start, len(lines)):
        jl = heading_level(lines[j])
        if jl and jl <= lvl:
            return "\n".join(lines[start:j])
    return "\n".join(lines[start:])


def verdict(n, lo, hi):
    """返回 (ok, 说明)。落区间内 → ok。"""
    if n < lo:
        return False, f"少了 {lo - n} 字（下限 {lo}）"
    if n > hi:
        return False, f"多了 {n - hi} 字（上限 {hi}）"
    return True, f"在区间内，余量 {hi - n} 字"


def split_sections(text):
    """把 md 切成 [(标题行 或 None, 该节正文), ...]；只把二级及更深的标题当分节线。"""
    out, title, buf = [], None, []
    for ln in (text or "").splitlines():
        if heading_level(ln) >= 2:
            out.append((title, "\n".join(buf)))
            title, buf = ln.strip(), []
        else:
            buf.append(ln)
    out.append((title, "\n".join(buf)))
    return out


def counted_text(text):
    """立论类稿真正计入时长的正文：去掉「答话 / 质询 / 预计回答」这类小节。

    这些小节是现场短攻防的备用弹药，辩手当场按对方刚说的话临时调整，
    不该占用立论 / 申论 / 结辩的时间预算。
    """
    keep = []
    for title, body in split_sections(text):
        if title is not None and any(k in title for k in EXCLUDE_SECTION_KEYS):
            continue
        keep.append(body)
    return "\n".join(keep)


def script_words(text):
    """一份立论类稿的计字（去空白，只算该环节自己那段）。"""
    return word_count(counted_text(text))
