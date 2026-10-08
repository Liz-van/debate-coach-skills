#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""九人赛制辩论对局记录预检：出交付物前校验 match record JSON（可配合交付文件夹一起查）。

用法:
  check_match.py <record.json> --tier 精简|标准|完整 [--deliverable <交付文件夹>]
                 [--strict-words] [--json]

硬项（不通过 → 退出码 1，先修再出文件）:
  H1 头部：motion 非空；tier ∈ {精简, 标准, 完整}
  H2 场次：matches 非空；n 从 1 起连续；场次数 = 档位值，除非 final.left_early 为 true
       （此时允许少于档位值但必须 ≥1，且 left_early_reason 非空且 ≥10 字）
  H3 每场 segments 恰好 13 条，phase/side/speaker/target 与赛制逐字一致；质询环节必须有 target；
       非自由辩论环节 summary 非空，自由辩论给 turns
  H4 每场时长：1–10、12、13 项 seconds 等于赛制值；第 11 项必须用 seconds_per_side = 240
  H5 每场 judge.segment_votes 恰好 7 条，phase 覆盖七环节且不重复；winner ∈ {正方,反方}；
       reason ≥10 字；layers 同时含 事实/价值/身份 三键，每值 ∈ {正方,反方,打平}
  H6 judge.impression_vote：winner ∈ {正方,反方}，reason ≥10 字
  H7 judge.battle_summary ≥50 字
  H8 judge.gains_losses 恰好 2 条，side 覆盖 {正方,反方}，good/bad 均非空
  H9 judge.argument_issues 恰好 6 条：正方 A1/A2/A3 与 反方 A1/A2/A3 各一条不重不漏；
       issue 与 demand 均非空（无问题要显式写「无」/「保持」）
  H10 每场 revisions 恰好 2 条，side 覆盖 {正方,反方}；report ∈ {有修改,无修改}；
       有修改 → patches 非空，每条含 id(∈A1/A2/A3)、action(∈ACTION_ENUM)、detail(≥8 字)、cost(非空)；
       无修改 → patches 必须为空且 reason ≥8 字；discussion/materials 给了就必须是列表
  H11 final.arguments 含 正方/反方 两键，各恰好 3 条，id 为 A1/A2/A3 不重不漏，
       result ∈ RESULT_ENUM，patches 为非负整数；每方 result ∈ ALIVE_ENUM 的条数必须 = 3
  H12 只在传了 --deliverable 时启用：交付结构完整（辩论实录.md、双方 立论报告.md / 资料.xlsx、
       双方 辩手资料/ 下各 7 个 md，文件名分别包含七个稿件名）
  H13 只在传了 --strict-words 且有 --deliverable 时启用：双方 立论报告.md 字数各自 ≥ 档位下限
  H14 只在传了 --deliverable 时启用：两份 立论报告.md 的「持方论点体系」一节不出现预判反驳句式
  H15 每场每段发言记了 words 时，必须落在该环节的字数区间内（时长 → 字数，见 speech_bands.py）；
       质询与自由辩论改按「每方实际发言总量」判，不要求逐次发言都达标
  H16 只在传了 --deliverable 时启用：立论类稿只算「该环节自己那段」并落在区间内——
       一辩立论稿数立论正文、二辩申论稿数申论正文、三辩小结稿数整份、四辩结辩稿数结辩正文；
       标题含「答话 / 质询 / 预计回答」的小节整节不计入（现场短攻防的备用弹药）。
       要点类稿（三辩质询稿、自由辩要点）不卡字数

软项（告警，不阻断）:
  S1 某环节 summary <20 字
  S2 某场七张技术票全部投给同一方
  S3 某场双方 report 都是「无修改」（提前结束的那一场不算）
  S4 字数未达档位下限（未开 --strict-words 时走这条）
  S5 某场自由辩论 turns 少于 8 条，或 turns 里同一 speaker 连续出现两次
  S6 记录档位与命令行 --tier 不一致
  S7 某方 patches 总数超过 12 条（改得太多，回头看是不是论点是硬凑的）
  S8 立论报告正文出现辩论过程字样（场次 / 票 / 评委 / 实录）：过程只该进 辩论实录.md
  S9 某段发言没记 words，没法核对按 260 字/分钟念不念得完
  S10 要点类稿（三辩质询稿、自由辩要点）写成了逐字稿的规模，提示一声——它们本该是弹药库

字数口径：去掉全部空白字符后的字符数（含标点）。H13/S4 **只数双方各自的 立论报告.md**，
辩手稿、数据资料、辩论实录.md 一律不计入（报告是备赛分析稿，稿子是能上台念的口语稿，两套分开算）。
口播稿的字数区间按 260 字/分钟、中心 ±10% 算，真源在 scripts/speech_bands.py。
立论类稿只数「该环节自己那段」：答话、质询这类小节是现场短攻防的备用弹药，
不计入任何区间——否则立论会被答话偷走预算。质询与自由辩论是现场短攻防，
辩手按对方刚说的话临时调整，交付的只是「要点·弹药库」不卡字数，
这两个环节改在实录里按每方实际发言总量卡（质询每方 175–215，自由辩每方 940–1140）。

退出码: 0 通过 / 1 硬项失败 / 2 输入或调用错误
"""

import argparse
import json
import os
import re
import sys

# 字数区间真源与 count_speech.py 共用同一份（同目录模块）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import speech_bands as sb  # noqa: E402

# Windows 控制台默认 GBK，✓/✗ 会 UnicodeEncodeError；统一按 UTF-8 输出（stderr 同理，argparse 用法提示也走它）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 档位表：场次数与报告字数下限（论点个数不随档位变，固定 3 个，见 H11）
TIERS = {
    "精简": {"matches": 2, "words": 20000},
    "标准": {"matches": 3, "words": 35000},
    "完整": {"matches": 4, "words": 50000},
}

ACTION_ENUM = {"修补", "换证据", "改判准", "让步删点", "拒绝并说明"}
RESULT_ENUM = {"存活", "修补后存活", "降级", "删除"}
ALIVE_ENUM = {"存活", "修补后存活"}
SIDE_ENUM = {"正方", "反方"}
REPORT_ENUM = {"有修改", "无修改"}
LAYER_KEYS = ("事实", "价值", "身份")
LAYER_ENUM = {"正方", "反方", "打平"}
ARG_IDS = ("A1", "A2", "A3")
VOTE_PHASES = ("一辩立论", "四质询一", "二辩申论", "三质询二", "三辩小结", "自由辩论", "结辩")
SIDES = ("正方", "反方")

# H14 立论不预判反驳：§4 持方论点体系里出现这些句式就算越界（猜对方怎么打属于 §6/§8）
REPORT_SEC_ARG = "持方论点体系"
PREDICT_RE = re.compile(
    r"(?:对方|反方|正方)\s*(?:会|可能|或许|一定|大概|恐怕|多半|势必)"
)
# S8 报告只管立论，辩论过程（场次/票/评委/实录）不许进报告正文
PROCESS_RE = re.compile(r"第[一二三四五六七八九十\d]+场|技术票|印象票|评委|辩论实录|环节摘要|发言板")

# 九人赛制固定 13 个发言单元：phase/side/speaker/target 逐字固定（H3 真源），时长见 H4
SEG_SPEC = [
    {"phase": "一辩立论", "side": "正方", "speaker": "正方一辩", "target": None, "seconds": 180},
    {"phase": "四质询一", "side": "反方", "speaker": "反方四辩", "target": "正方一辩", "seconds": 90},
    {"phase": "一辩立论", "side": "反方", "speaker": "反方一辩", "target": None, "seconds": 180},
    {"phase": "四质询一", "side": "正方", "speaker": "正方四辩", "target": "反方一辩", "seconds": 90},
    {"phase": "二辩申论", "side": "正方", "speaker": "正方二辩", "target": None, "seconds": 120},
    {"phase": "三质询二", "side": "反方", "speaker": "反方三辩", "target": "正方二辩", "seconds": 90},
    {"phase": "二辩申论", "side": "反方", "speaker": "反方二辩", "target": None, "seconds": 120},
    {"phase": "三质询二", "side": "正方", "speaker": "正方三辩", "target": "反方二辩", "seconds": 90},
    {"phase": "三辩小结", "side": "正方", "speaker": "正方三辩", "target": None, "seconds": 120},
    {"phase": "三辩小结", "side": "反方", "speaker": "反方三辩", "target": None, "seconds": 120},
    {"phase": "自由辩论", "side": "双方", "speaker": None, "target": None, "seconds_per_side": 240},
    {"phase": "结辩", "side": "反方", "speaker": "反方四辩", "target": None, "seconds": 180},
    {"phase": "结辩", "side": "正方", "speaker": "正方四辩", "target": None, "seconds": 180},
]

WS_RE = re.compile(r"\s+")

# H12 交付结构
DELIVERABLE_MAIN = "辩论实录.md"
DELIVERABLE_SIDE_FILES = ("立论报告.md", "资料.xlsx")
PLAYER_DOCS = ("一辩立论稿", "二辩申论稿", "三辩质询稿", "三辩小结稿",
               "四辩结辩稿", "自由辩要点", "数据资料")

HARD_FAIL = []
WARN = []
JSON_MODE = False


def say(msg=""):
    """--json 时保持 stdout 是纯 JSON，人类可读行一律走这里。"""
    if not JSON_MODE:
        print(msg)


def s(v):
    return "" if v is None else str(v).strip()


def as_list(v):
    return v if isinstance(v, list) else []


def num(v):
    """容错取整数（"240" 与 240 都认）；取不到返回 None。bool 不算数。"""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    try:
        return int(str(v).strip())
    except Exception:  # noqa: BLE001
        return None


def fail(line):
    say(f"  ✗ {line}")
    HARD_FAIL.append(line)


def word_count(text):
    """字数口径：去掉全部空白字符后的字符数（含标点）。"""
    return len(WS_RE.sub("", text))


# ---------------------------------------------------------------- H1

def check_header(data):
    bad = []
    if not s(data.get("motion")):
        bad.append("缺 motion（辩题）")
    record_tier = s(data.get("tier"))
    if record_tier not in TIERS:
        bad.append(f"tier「{record_tier or '空'}」不合法（只取 精简/标准/完整）")
    if bad:
        fail(f"H1 头部 {'；'.join(bad)}")
    else:
        say("  ✓ H1 头部完整（motion + tier）")
    return record_tier


# ---------------------------------------------------------------- H2

def check_matches(data, tier_name):
    tier = TIERS[tier_name]
    matches = as_list(data.get("matches"))
    final = data.get("final") if isinstance(data.get("final"), dict) else {}
    left_early = final.get("left_early") is True
    reason = s(final.get("left_early_reason"))

    bad = []
    if not matches:
        bad.append("matches 为空（一场都没有）")
    for i, m in enumerate(matches, 1):
        if not isinstance(m, dict):
            bad.append(f"第{i}场不是对象")
            continue
        if num(m.get("n")) != i:
            bad.append(f"第{i}场 n = {m.get('n')}（应连续从 1 起）")

    if matches and not bad:
        need = tier["matches"]
        if not left_early:
            if len(matches) != need:
                bad.append(f"场次 {len(matches)} 场（{tier_name}档应为 {need} 场；"
                           f"真提前结束请把 final.left_early 置 true）")
        else:
            if len(matches) < 1:
                bad.append("left_early 为 true 但场次为 0（至少要有 1 场）")
            elif len(matches) < need and len(reason) < 10:
                bad.append(f"left_early 为 true 且只打了 {len(matches)} 场，"
                           f"left_early_reason 为空或过短（{len(reason)} 字，应 ≥10）")

    if bad:
        for b in bad:
            fail(f"H2 场次：{b}")
    else:
        tail = "（提前结束）" if left_early else ""
        say(f"  ✓ H2 场次 {len(matches)} 场，n 连续{tail}")
    return matches, left_early


# ---------------------------------------------------------------- H3

def check_segments(mi, m):
    segs = as_list(m.get("segments"))
    bad = []
    if len(segs) != len(SEG_SPEC):
        bad.append(f"第{mi}场 segments 共 {len(segs)} 条（九人赛制固定 {len(SEG_SPEC)} 条）")

    for i, spec in enumerate(SEG_SPEC):
        if i >= len(segs):
            break
        seg = segs[i]
        pos = f"第{mi}场 第{i + 1}项（{spec['phase']}）"
        if not isinstance(seg, dict):
            bad.append(f"{pos} 不是对象")
            continue
        item = []
        if s(seg.get("phase")) != spec["phase"]:
            item.append(f"phase「{s(seg.get('phase')) or '空'}」应为「{spec['phase']}」")
        if s(seg.get("side")) != spec["side"]:
            item.append(f"side「{s(seg.get('side')) or '空'}」应为「{spec['side']}」")
        if spec["speaker"] is None:
            if s(seg.get("speaker")):
                item.append(f"speaker 应为空（自由辩论按 side=双方 记），实为「{s(seg.get('speaker'))}」")
        elif s(seg.get("speaker")) != spec["speaker"]:
            item.append(f"speaker「{s(seg.get('speaker')) or '空'}」应为「{spec['speaker']}」")
        if spec["target"] is None:
            if s(seg.get("target")):
                item.append(f"target 应为空，实为「{s(seg.get('target'))}」")
        elif s(seg.get("target")) != spec["target"]:
            item.append(f"target「{s(seg.get('target')) or '空'}」应为「{spec['target']}」")
        if spec["phase"] == "自由辩论":
            if not as_list(seg.get("turns")):
                item.append("缺 turns（自由辩论要记双方回合）")
        elif not s(seg.get("summary")):
            item.append("summary 为空")
        if item:
            bad.append(f"{pos}：{'；'.join(item)}")

    if bad:
        for b in bad:
            fail(f"H3 {b}")
    else:
        say(f"  ✓ H3 第{mi}场 13 个环节 phase/side/speaker/target 与赛制逐字一致")


# ---------------------------------------------------------------- H4

def check_durations(mi, m):
    segs = as_list(m.get("segments"))
    bad = []
    for i, spec in enumerate(SEG_SPEC):
        if i >= len(segs) or not isinstance(segs[i], dict):
            continue
        seg = segs[i]
        pos = f"第{mi}场 第{i + 1}项（{spec['phase']}）"
        if "seconds_per_side" in spec:
            if "seconds" in seg:
                bad.append(f"{pos}：自由辩论用了 seconds，必须用 seconds_per_side")
            got = num(seg.get("seconds_per_side"))
            if got != spec["seconds_per_side"]:
                bad.append(f"{pos}：seconds_per_side {seg.get('seconds_per_side')}"
                           f" 应为 {spec['seconds_per_side']}")
        else:
            got = num(seg.get("seconds"))
            if got != spec["seconds"]:
                bad.append(f"{pos}：seconds {seg.get('seconds')} 应为 {spec['seconds']}")

    if bad:
        for b in bad:
            fail(f"H4 {b}")
    else:
        say(f"  ✓ H4 第{mi}场 13 项时长与赛制一致（自由辩论 seconds_per_side=240）")


# ---------------------------------------------------------------- H5–H9

def check_judge(mi, m):
    judge = m.get("judge") if isinstance(m.get("judge"), dict) else None
    if judge is None:
        fail(f"H5 第{mi}场缺 judge 对象")
        fail(f"H6 第{mi}场缺 judge.impression_vote")
        fail(f"H7 第{mi}场缺 judge.battle_summary")
        fail(f"H8 第{mi}场缺 judge.gains_losses")
        fail(f"H9 第{mi}场缺 judge.argument_issues")
        return

    # --- H5 技术票
    votes = as_list(judge.get("segment_votes"))
    bad = []
    if len(votes) != len(VOTE_PHASES):
        bad.append(f"第{mi}场 segment_votes 共 {len(votes)} 条（应为 7 条：七个环节各一张）")
    seen_phase = []
    for vi, v in enumerate(votes, 1):
        if not isinstance(v, dict):
            bad.append(f"第{mi}场 技术票第{vi}条不是对象")
            continue
        ph = s(v.get("phase"))
        tag = f"第{mi}场 技术票「{ph or '空'}」"
        if ph not in VOTE_PHASES:
            bad.append(f"{tag}：phase 不在七环节里")
        elif ph in seen_phase:
            bad.append(f"{tag}：phase 重复")
        seen_phase.append(ph)
        if s(v.get("winner")) not in SIDE_ENUM:
            bad.append(f"{tag}：winner「{s(v.get('winner')) or '空'}」不合法（只取 正方/反方）")
        if len(s(v.get("reason"))) < 10:
            bad.append(f"{tag}：reason 为空或过短（{len(s(v.get('reason')))} 字，应 ≥10）")
        layers = v.get("layers")
        if not isinstance(layers, dict):
            bad.append(f"{tag}：缺 layers（要同时含 事实/价值/身份）")
        else:
            miss = [k for k in LAYER_KEYS if k not in layers]
            if miss:
                bad.append(f"{tag}：layers 缺 {'/'.join(miss)}")
            for k in LAYER_KEYS:
                if k in layers and s(layers.get(k)) not in LAYER_ENUM:
                    bad.append(f"{tag}：layers.{k}「{s(layers.get(k)) or '空'}」不合法"
                               f"（只取 正方/反方/打平）")
    miss_phase = [p for p in VOTE_PHASES if p not in seen_phase]
    if miss_phase:
        bad.append(f"第{mi}场 技术票缺环节：{'、'.join(miss_phase)}")
    if bad:
        for b in bad:
            fail(f"H5 {b}")
    else:
        say(f"  ✓ H5 第{mi}场 技术票 7 张，七环节齐备，winner/reason/layers 合法")

    # --- H6 印象票
    imp = judge.get("impression_vote")
    if not isinstance(imp, dict):
        fail(f"H6 第{mi}场缺 impression_vote（印象票）对象")
    else:
        bad = []
        if s(imp.get("winner")) not in SIDE_ENUM:
            bad.append(f"winner「{s(imp.get('winner')) or '空'}」不合法（只取 正方/反方）")
        if len(s(imp.get("reason"))) < 10:
            bad.append(f"reason 为空或过短（{len(s(imp.get('reason')))} 字，应 ≥10）")
        if bad:
            fail(f"H6 第{mi}场 impression_vote：{'；'.join(bad)}")
        else:
            say(f"  ✓ H6 第{mi}场 印象票合法")

    # --- H7 战场总结
    n = len(s(judge.get("battle_summary")))
    if n < 50:
        fail(f"H7 第{mi}场 battle_summary {n} 字（应 ≥50）")
    else:
        say(f"  ✓ H7 第{mi}场 battle_summary {n} 字")

    # --- H8 得失
    gl = as_list(judge.get("gains_losses"))
    bad = []
    if len(gl) != 2:
        bad.append(f"第{mi}场 gains_losses 共 {len(gl)} 条（应为 2 条：正方/反方各一条）")
    sides = []
    for g in gl:
        if not isinstance(g, dict):
            bad.append(f"第{mi}场 gains_losses 里有非对象条目")
            continue
        sd = s(g.get("side"))
        tag = f"第{mi}场 得失「{sd or '空'}」"
        if sd not in SIDE_ENUM:
            bad.append(f"{tag}：side 不合法")
        sides.append(sd)
        if not s(g.get("good")):
            bad.append(f"{tag}：good 为空（没好处也要写「无」）")
        if not s(g.get("bad")):
            bad.append(f"{tag}：bad 为空（没坏处也要写「无」）")
    if not SIDE_ENUM <= set(sides):
        bad.append(f"第{mi}场 gains_losses 未覆盖 正方/反方（现有 {sides}）")
    if bad:
        for b in bad:
            fail(f"H8 {b}")
    else:
        say(f"  ✓ H8 第{mi}场 gains_losses 2 条，双方 good/bad 齐全")

    # --- H9 论点问题
    issues = as_list(judge.get("argument_issues"))
    want = {(sd, aid) for sd in SIDE_ENUM for aid in ARG_IDS}
    got = []
    bad = []
    if len(issues) != len(want):
        bad.append(f"第{mi}场 argument_issues 共 {len(issues)} 条（应为 6 条：双方 A1/A2/A3 各一条）")
    for it in issues:
        if not isinstance(it, dict):
            bad.append(f"第{mi}场 argument_issues 里有非对象条目")
            continue
        key = (s(it.get("side")), s(it.get("target")))
        tag = f"第{mi}场 论点问题「{key[0] or '空'}·{key[1] or '空'}」"
        if key[0] not in SIDE_ENUM or key[1] not in ARG_IDS:
            bad.append(f"{tag}：side/target 不合法（target 只取 A1/A2/A3）")
        elif key in got:
            bad.append(f"{tag}：重复")
        got.append(key)
        if not s(it.get("issue")):
            bad.append(f"{tag}：issue 为空（没问题也要显式写「无」）")
        if not s(it.get("demand")):
            bad.append(f"{tag}：demand 为空（没要求也要显式写「保持」）")
    miss = sorted(want - set(got))
    if miss:
        bad.append(f"第{mi}场 argument_issues 缺：{'、'.join(f'{a}·{b}' for a, b in miss)}")
    if bad:
        for b in bad:
            fail(f"H9 {b}")
    else:
        say(f"  ✓ H9 第{mi}场 argument_issues 6 条，双方 A1/A2/A3 不重不漏")


# ---------------------------------------------------------------- H10

def check_revisions(mi, m):
    revs = as_list(m.get("revisions"))
    bad = []
    if len(revs) != 2:
        bad.append(f"第{mi}场 revisions 共 {len(revs)} 条（应为 2 条：正方/反方各一条）")
    sides = []
    for r in revs:
        if not isinstance(r, dict):
            bad.append(f"第{mi}场 revisions 里有非对象条目")
            continue
        sd = s(r.get("side"))
        tag = f"第{mi}场 修改报告「{sd or '空'}」"
        if sd not in SIDE_ENUM:
            bad.append(f"{tag}：side 不合法")
        sides.append(sd)
        report = s(r.get("report"))
        if report not in REPORT_ENUM:
            bad.append(f"{tag}：report「{report or '空'}」不合法（只取 有修改/无修改）")
        patches = r.get("patches")
        patches = patches if isinstance(patches, list) else []
        if report == "有修改":
            if not patches:
                bad.append(f"{tag}：report=有修改 但 patches 为空")
            for pi, p in enumerate(patches, 1):
                ptag = f"{tag} 修补第{pi}条"
                if not isinstance(p, dict):
                    bad.append(f"{ptag} 不是对象")
                    continue
                if s(p.get("id")) not in ARG_IDS:
                    bad.append(f"{ptag}：id「{s(p.get('id')) or '空'}」不合法（只取 A1/A2/A3）")
                if s(p.get("action")) not in ACTION_ENUM:
                    bad.append(f"{ptag}：action「{s(p.get('action')) or '空'}」不合法")
                if len(s(p.get("detail"))) < 8:
                    bad.append(f"{ptag}：detail 为空或过短"
                               f"（{len(s(p.get('detail')))} 字，应 ≥8）")
                if not s(p.get("cost")):
                    bad.append(f"{ptag}：缺 cost（没代价也要写「无」）")
        elif report == "无修改":
            if patches:
                bad.append(f"{tag}：report=无修改 却带了 {len(patches)} 条 patches（应为空）")
            if len(s(r.get("reason"))) < 8:
                bad.append(f"{tag}：无修改但 reason 为空或过短"
                           f"（{len(s(r.get('reason')))} 字，应 ≥8）")
        for key, label in (("discussion", "discussion"), ("materials", "materials")):
            v = r.get(key)
            if v is not None and not isinstance(v, list):
                bad.append(f"{tag}：{label} 给了但不是列表")
    if not SIDE_ENUM <= set(sides):
        bad.append(f"第{mi}场 revisions 未覆盖 正方/反方（现有 {sides}）")
    if bad:
        for b in bad:
            fail(f"H10 {b}")
    else:
        say(f"  ✓ H10 第{mi}场 revisions 2 条，report/patches/reason 自洽")


# ---------------------------------------------------------------- H11

def check_final(data):
    final = data.get("final") if isinstance(data.get("final"), dict) else {}
    args_map = final.get("arguments")
    if not isinstance(args_map, dict):
        fail("H11 final.arguments 缺失或不是对象（要含 正方/反方 两键）")
        return
    bad = []
    for sd in ("正方", "反方"):
        if sd not in args_map:
            bad.append(f"final.arguments 缺「{sd}」")
    for sd in ("正方", "反方"):
        rows = args_map.get(sd)
        if not isinstance(rows, list):
            bad.append(f"final.arguments.{sd} 不是列表")
            continue
        tag = f"最终论点「{sd}」"
        if len(rows) != len(ARG_IDS):
            bad.append(f"{tag} 共 {len(rows)} 条（应为 3 条：A1/A2/A3）")
        ids = []
        alive = 0
        for i, a in enumerate(rows, 1):
            if not isinstance(a, dict):
                bad.append(f"{tag} 第{i}条不是对象")
                continue
            aid = s(a.get("id"))
            atag = f"{tag} {aid or f'第{i}条'}"
            if aid not in ARG_IDS:
                bad.append(f"{atag}：id「{aid or '空'}」不合法（只取 A1/A2/A3）")
            elif aid in ids:
                bad.append(f"{atag}：id 重复")
            ids.append(aid)
            res = s(a.get("result"))
            if res not in RESULT_ENUM:
                bad.append(f"{atag}：result「{res or '空'}」不合法（只取 存活/修补后存活/降级/删除）")
            elif res in ALIVE_ENUM:
                alive += 1
            pc = num(a.get("patches"))
            if pc is None or pc < 0:
                bad.append(f"{atag}：patches 必须是非负整数（现有 {a.get('patches')}）")
        miss = [x for x in ARG_IDS if x not in ids]
        if miss:
            bad.append(f"{tag} 缺论点：{'、'.join(miss)}")
        if alive != len(ARG_IDS):
            bad.append(f"{tag} 存活（存活/修补后存活）{alive} 个，必须 = {len(ARG_IDS)}"
                       f"（掉了的论点要回炉补回 3 个，不许降到 2 个）")
    if bad:
        for b in bad:
            fail(f"H11 {b}")
    else:
        say("  ✓ H11 final.arguments 双方各 3 个论点，A1/A2/A3 齐备，存活各 3 个")


# ---------------------------------------------------------------- H12 / H13

def list_md(dirpath):
    if not os.path.isdir(dirpath):
        return None
    out = []
    for fn in os.listdir(dirpath):
        if fn.lower().endswith(".md") and os.path.isfile(os.path.join(dirpath, fn)):
            out.append(fn)
    return out


def read_text(path):
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            return f.read()
    except Exception:  # noqa: BLE001
        return None


def heading_level(line):
    """标题行的层级（# = 1）；不是标题返回 0。"""
    t = line.lstrip()
    n = 0
    while n < len(t) and t[n] == "#":
        n += 1
    if 0 < n <= 6 and len(t) > n and t[n] in " \t":
        return n
    return 0


def section_text(text, key):
    """截出标题含 key 的那一节正文（含其下的子标题），到同级或更高级标题为止；找不到返回 None。"""
    if not text:
        return None
    lines = text.splitlines()
    start = lvl = None
    for i, ln in enumerate(lines):
        if key in ln and heading_level(ln):
            start, lvl = i + 1, heading_level(ln)
            break
    if start is None:
        return None
    for j in range(start, len(lines)):
        jl = heading_level(lines[j])
        if jl and jl <= lvl:
            return "\n".join(lines[start:j])
    return "\n".join(lines[start:])


def report_words(root):
    """H13/S4 只数双方各自的 立论报告.md：辩手稿、数据资料、辩论实录.md 一律不计入。"""
    out = {}
    for sd in SIDES:
        txt = read_text(os.path.join(root, sd, DELIVERABLE_SIDE_FILES[0]))
        out[sd] = None if txt is None else word_count(txt)
    return out


def check_deliverable(root):
    """H12 交付结构。返回交付信息字典；目录不存在/不是目录 → 返回 None（调用方按参数错误退 2）。"""
    if not os.path.isdir(root):
        return None
    bad = []
    if not os.path.isfile(os.path.join(root, DELIVERABLE_MAIN)):
        bad.append(f"缺 {DELIVERABLE_MAIN}")
    for sd in SIDES:
        for rel in DELIVERABLE_SIDE_FILES:
            if not os.path.isfile(os.path.join(root, sd, rel)):
                bad.append(f"缺 {sd}/{rel}")
        d = os.path.join(root, sd, "辩手资料")
        files = list_md(d)
        if files is None:
            bad.append(f"缺 {sd}/辩手资料/ 目录")
            continue
        if len(files) != len(PLAYER_DOCS):
            bad.append(f"{sd}/辩手资料/ 有 {len(files)} 个 md（应为 {len(PLAYER_DOCS)} 个）")
        for key in PLAYER_DOCS:
            if not any(key in fn for fn in files):
                bad.append(f"{sd}/辩手资料/ 里没有文件名含「{key}」的 md")
    if bad:
        for b in bad:
            fail(f"H12 {b}")
    else:
        say("  ✓ H12 交付结构完整（实录 + 双方立论报告/资料 + 双方各 7 份辩手资料）")
    return {"words": report_words(root)}


def check_report_purity(root):
    """H14 §4 持方论点体系不预判反驳（硬项）；S8 报告正文不出现辩论过程字样（软项）。"""
    for sd in SIDES:
        rel = f"{sd}/{DELIVERABLE_SIDE_FILES[0]}"
        txt = read_text(os.path.join(root, sd, DELIVERABLE_SIDE_FILES[0]))
        if txt is None:
            continue  # 报告缺失已由 H12 报过，这里不再重复
        sec = section_text(txt, REPORT_SEC_ARG)
        if sec is None:
            fail(f"H14 {rel} 找不到「{REPORT_SEC_ARG}」一节，无法确认这一节没有预判反驳")
        else:
            hits = sorted({m.group(0).replace(" ", "") for m in PREDICT_RE.finditer(sec)})
            if hits:
                fail(f"H14 {rel}「{REPORT_SEC_ARG}」出现预判反驳句式：{'、'.join(hits)}"
                     f"（立论不预判对方，猜对方怎么打写进 §6 对方观点与反驳 / §8 攻防预判）")
            else:
                say(f"  ✓ H14 {rel}「{REPORT_SEC_ARG}」只写我方主张，没有预判反驳句式")
        proc = sorted({m.group(0) for m in PROCESS_RE.finditer(txt)})
        if proc:
            WARN.append(f"S8 {rel} 正文出现辩论过程字样：{'、'.join(proc)}"
                        f"（对抗过程、场次、票、评委裁决只进 辩论实录.md）")


# ---------------------------------------------------------------- H15 / H16 口播字数

def speech_verdict(tag, label, n, lo, hi):
    """字数是否落在区间内。"""
    if n > hi:
        fail(f"{tag} {label}：{n} 字，超上限 {hi}（按 {sb.RATE} 字/分钟念不完，删到区间内）")
        return False
    if n < lo:
        fail(f"{tag} {label}：{n} 字，低于下限 {lo}（时间用不满，补内容）")
        return False
    say(f"  ✓ {tag} {label}：{n} 字，落在 {lo}–{hi}")
    return True


def segment_word_items(seg, phase):
    """把一段发言的字数记录拆成 [(标签, 字数, 下限, 上限)]；没记字数返回 []。

    认三种写法：普通环节写整数；质询环节写 {"问": n, "答": n}（或直接写 {"正方": n, "反方": n}）；
    自由辩论写 {"正方": n, "反方": n} 或直接在每个 turn 上写 words（脚本自动按发言人归到各方）。

    质询与自由辩论是现场短攻防，辩手按对方刚说的话临时调整，所以只卡「每方在这一环节
    实际说了多少」，不要求每一次发言都落在区间里，也不再把问与答加起来判。
    """
    u = sb.UNITS[phase]
    w = seg.get("words")
    if phase in ("四质询一", "三质询二"):
        # 现场短攻防：只卡「每方在这一环节说了多少」，不要求每一次发言都达标。
        if isinstance(w, dict):
            items = []
            for sd in SIDES:
                n = num(w.get(sd))
                if n is not None:
                    items.append((f"{phase}·{sd}总量", n, sb.ASK_LO, sb.ASK_HI))
            if items:
                return items
            for k, who in (("问", "质询方"), ("答", "被质询方")):
                n = num(w.get(k))
                if n is not None:
                    items.append((f"{phase}·{who}总量", n, sb.ASK_LO, sb.ASK_HI))
            if items:
                return items
        else:
            n = num(w)
            if n is not None:
                return [(f"{phase}总字数", n, u["lo"], u["hi"])]
        # 逐回合记的（现场短攻防最常见）：把 turns 上的 words 按方加起来
        ask = s(seg.get("side"))
        ans = "反方" if ask == "正方" else "正方"
        per = {}
        for t in as_list(seg.get("turns")):
            if not isinstance(t, dict):
                continue
            n = num(t.get("words"))
            if n is None:
                continue
            role, sd, spk = s(t.get("role")), s(t.get("side")), s(t.get("speaker"))
            if sd not in SIDES:
                if role.startswith("问"):
                    sd = ask
                elif role.startswith("答"):
                    sd = ans
                elif spk.startswith("正方"):
                    sd = "正方"
                elif spk.startswith("反方"):
                    sd = "反方"
                else:
                    sd = None
            if sd in SIDES:
                per[sd] = per.get(sd, 0) + n
        return [(f"{phase}·{sd}总量", per[sd], sb.ASK_LO, sb.ASK_HI)
                for sd in SIDES if sd in per]
    if phase == "自由辩论":
        if isinstance(w, dict):
            items = []
            for sd in SIDES:
                n = num(w.get(sd))
                if n is not None:
                    items.append((f"自由辩论·{sd}", n, u["lo"], u["hi"]))
            return items
        per = {}
        for t in as_list(seg.get("turns")):
            if not isinstance(t, dict):
                continue
            spk = s(t.get("speaker"))
            sd = "正方" if spk.startswith("正方") else ("反方" if spk.startswith("反方") else None)
            n = num(t.get("words"))
            if sd and n is not None:
                per[sd] = per.get(sd, 0) + n
        return [(f"自由辩论·{sd}", per[sd], u["lo"], u["hi"]) for sd in SIDES if sd in per]
    n = num(w)
    return [] if n is None else [(phase, n, u["lo"], u["hi"])]


def check_segment_words(mi, m):
    """H15：记了 words 的发言段必须落在该环节的字数区间内；没记的走 S9 告警。"""
    missing = []
    for i, seg in enumerate(as_list(m.get("segments"))):
        if not isinstance(seg, dict) or i >= len(SEG_SPEC):
            continue
        phase = SEG_SPEC[i]["phase"]
        items = segment_word_items(seg, phase)
        if not items:
            missing.append(phase)
            continue
        for label, n, lo, hi in items:
            speech_verdict("H15", f"第{mi}场 {label}", n, lo, hi)
    if missing:
        uniq = [p for p in sb.PHASE_ORDER if p in missing]
        WARN.append(f"S9 第{mi}场 {'、'.join(uniq)} 没记 words，"
                    f"没法核对按 {sb.RATE} 字/分钟念不念得完")


def check_speech_files(root):
    """H16：立论类稿只算「该环节自己那段」并落在区间内；要点类稿不卡字数。

    立论类稿（BANDED_FILES）——一辩立论稿数立论正文、二辩申论稿数申论正文、
    三辩小结稿数整份、四辩结辩稿数结辩正文；标题含「答话 / 质询 / 预计回答」的
    小节整节不计入（那是现场短攻防的备用弹药，不该偷走立论的时间预算）。
    要点类稿（NOTE_FILES）——三辩质询稿、自由辩要点只当弹药库，不卡字数；
    这两个环节的字数在实录里按每方实际发言总量卡（H15）。
    """
    for sd in SIDES:
        d = os.path.join(root, sd, "辩手资料")
        names = os.listdir(d) if os.path.isdir(d) else []
        for key, ph in sb.BANDED_FILES.items():
            hit = [fn for fn in names if key in fn and fn.lower().endswith(".md")]
            if not hit:
                continue  # 缺文件已由 H12 报过
            txt = read_text(os.path.join(d, hit[0]))
            if txt is None:
                continue
            u = sb.UNITS[ph]
            speech_verdict("H16", f"{sd}/{hit[0]}[{ph}]", sb.script_words(txt), u["lo"], u["hi"])
        for key in sb.NOTE_FILES:
            hit = [fn for fn in names if key in fn and fn.lower().endswith(".md")]
            if not hit:
                continue  # 要点类稿可以不交
            txt = read_text(os.path.join(d, hit[0]))
            if txt is None:
                continue
            n = sb.word_count(txt)
            cap = sb.UNITS["三质询二" if key == "三辩质询稿" else "自由辩论"]
            if n > cap["hi"] * 3:
                WARN.append(f"S10 {sd}/{hit[0]}：{n} 字，是该环节上限 {cap['hi']} 的 "
                            f"{n / cap['hi']:.1f} 倍，像是写成了逐字稿——"
                            f"这一份本该只写要点，现场按对方的话临时调整")
            else:
                say(f"  · {sd}/{hit[0]}：{n} 字，要点类不卡字数"
                    f"（该环节按每方实际发言总量卡）")


# ---------------------------------------------------------------- 主流程

def main():
    global JSON_MODE
    ap = argparse.ArgumentParser(description="九人赛制辩论对局记录预检")
    ap.add_argument("data", help="对局记录 JSON（match record）")
    ap.add_argument("--tier", required=True, choices=list(TIERS),
                    help="档位：精简 / 标准 / 完整（决定场次数与字数下限）")
    ap.add_argument("--deliverable", help="交付文件夹，启用 H12 交付结构与字数检查")
    ap.add_argument("--strict-words", action="store_true", dest="strict_words",
                    help="把字数下限从软项 S4 升级为硬项 H13（需配合 --deliverable）")
    ap.add_argument("--json", action="store_true", dest="as_json",
                    help="输出机器可读 JSON：{ok, hard, soft, summary}")
    args = ap.parse_args()
    JSON_MODE = args.as_json

    try:
        # utf-8-sig：Windows 编辑器/Out-File 常给 JSON 加 BOM，带上 BOM 也照读（无 BOM 不受影响）
        with open(args.data, encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception as e:  # noqa: BLE001
        say(f"✗ 无法读取对局记录 JSON：{e}")
        return 2

    if not isinstance(data, dict):
        say("✗ 对局记录 JSON 顶层必须是对象（{...}）")
        return 2

    tier = TIERS[args.tier]
    motion = s(data.get("motion")) or "（未填辩题）"
    say(f"== check_match · 档位 {args.tier} · {motion} ==")

    # H12 先跑：交付目录不存在按参数错误退 2，不进硬项统计
    deliv = None
    if args.deliverable:
        deliv = check_deliverable(args.deliverable)
        if deliv is None:
            say(f"✗ --deliverable 目录不存在或不是目录：{args.deliverable}")
            return 2
        check_report_purity(args.deliverable)
        check_speech_files(args.deliverable)
    words = deliv["words"] if deliv else None

    # 摘要行（场次 / 环节 / 票数 / 字数）
    matches = as_list(data.get("matches"))
    seg_n = sum(len(as_list(m.get("segments"))) for m in matches if isinstance(m, dict))
    vote_n = sum(len(as_list((m.get("judge") or {}).get("segment_votes")))
                 for m in matches if isinstance(m, dict) and isinstance(m.get("judge"), dict))
    if words is None:
        word_txt = "未统计（未给 --deliverable）"
    else:
        word_txt = "、".join(f"{sd} {words.get(sd)}" for sd in SIDES)
        word_txt += f"（双方各自下限 {tier['words']}）"
    say(f"  场次 {len(matches)}/{tier['matches']} · 环节 {seg_n} · 技术票 {vote_n} · 报告字数 {word_txt}")

    # ---- 硬项 ----
    record_tier = check_header(data)
    matches, left_early = check_matches(data, args.tier)
    for mi, m in enumerate(matches, 1):
        if not isinstance(m, dict):
            continue
        check_segments(mi, m)
        check_durations(mi, m)
        check_segment_words(mi, m)
        check_judge(mi, m)
        check_revisions(mi, m)
    check_final(data)

    if args.strict_words and args.deliverable and words is not None:
        for sd in SIDES:
            n = words.get(sd)
            if n is None:
                continue  # 报告缺失已由 H12 报过
            if n < tier["words"]:
                fail(f"H13 {sd}/立论报告.md 字数 {n} < 档位下限 {tier['words']}（--strict-words 已开）")
            else:
                say(f"  ✓ H13 {sd}/立论报告.md 字数 {n} ≥ 下限 {tier['words']}")
    elif args.strict_words and not args.deliverable:
        say("  ⚠ --strict-words 需要配合 --deliverable 才生效，本次跳过字数硬项")

    # ---- 软项 ----
    check_soft(data, matches, left_early, record_tier, args, words, tier)

    say()
    if WARN:
        say("告警：")
        for w in WARN:
            say(f"  ⚠ {w}")

    ok = not HARD_FAIL
    if args.as_json:
        summary = {
            "tier": args.tier,
            "motion": s(data.get("motion")),
            "matches": len(matches),
            "expected_matches": tier["matches"],
            "segments": seg_n,
            "votes": vote_n,
            "words": words,
            "word_floor": tier["words"],
            "word_floor_per_side": True,
            "left_early": left_early,
        }
        print(json.dumps({"ok": ok, "hard": HARD_FAIL, "soft": WARN, "summary": summary},
                         ensure_ascii=False, indent=2))

    if not ok:
        say(f"\n✗ 硬项失败 {len(HARD_FAIL)} 项，先修再出文件")
        return 1
    say("\n✓ 对局记录预检通过")
    return 0


def check_soft(data, matches, left_early, record_tier, args, words, tier):
    # S1 环节 summary 过短
    short = []
    for mi, m in enumerate(matches, 1):
        if not isinstance(m, dict):
            continue
        for i, seg in enumerate(as_list(m.get("segments"))):
            if not isinstance(seg, dict) or i >= len(SEG_SPEC):
                continue
            if SEG_SPEC[i]["phase"] == "自由辩论":
                continue
            n = len(s(seg.get("summary")))
            if 0 < n < 20:
                short.append(f"第{mi}场·{SEG_SPEC[i]['phase']} {n} 字")
    if short:
        WARN.append(f"S1 有环节 summary 少于 20 字：{'；'.join(short)}")

    # S2 七张技术票全给同一方
    for mi, m in enumerate(matches, 1):
        if not isinstance(m, dict) or not isinstance(m.get("judge"), dict):
            continue
        votes = as_list(m["judge"].get("segment_votes"))
        winners = {s(v.get("winner")) for v in votes if isinstance(v, dict) and s(v.get("winner"))}
        if len(votes) >= len(VOTE_PHASES) and len(winners) == 1:
            WARN.append(f"S2 第{mi}场七张技术票全投给「{next(iter(winners))}」："
                        f"一边倒要回看是不是陪跑")

    # S3 双方都报「无修改」（提前结束的那一场不算）
    for mi, m in enumerate(matches, 1):
        if not isinstance(m, dict):
            continue
        if left_early and mi == len(matches):
            continue
        reports = [s(r.get("report")) for r in as_list(m.get("revisions")) if isinstance(r, dict)]
        if reports and all(r == "无修改" for r in reports):
            WARN.append(f"S3 第{mi}场双方 report 都是「无修改」：要么没真打，要么没更新记录")

    # S4 / H13：字数下限（--strict-words 时走硬项 H13，这里不再重复告警）
    if words is not None and not args.strict_words:
        for sd in SIDES:
            n = words.get(sd)
            if n is not None and n < tier["words"]:
                WARN.append(f"S4 {sd}/立论报告.md 字数 {n} < 档位下限 {tier['words']}"
                            f"（加 --strict-words 可升级为硬项）")

    # S5 自由辩论回合
    for mi, m in enumerate(matches, 1):
        if not isinstance(m, dict):
            continue
        for seg in as_list(m.get("segments")):
            if not isinstance(seg, dict) or s(seg.get("phase")) != "自由辩论":
                continue
            turns = as_list(seg.get("turns"))
            if len(turns) < 8:
                WARN.append(f"S5 第{mi}场自由辩论只有 {len(turns)} 个回合（建议 ≥8）："
                            f"自由辩论太短说明没交锋")
            speakers = [s(t.get("speaker")) for t in turns if isinstance(t, dict)]
            dup = [speakers[i] for i in range(1, len(speakers))
                   if speakers[i] and speakers[i] == speakers[i - 1]]
            if dup:
                WARN.append(f"S5 第{mi}场自由辩论同一 speaker 连续发言：{'、'.join(sorted(set(dup)))}")

    # S6 记录档位与命令行不一致
    if record_tier and record_tier != args.tier:
        WARN.append(f"S6 记录档位「{record_tier}」与命令行 --tier {args.tier} 不一致")

    # S7 修补条数过多
    per_side = {}
    for m in matches:
        if not isinstance(m, dict):
            continue
        for r in as_list(m.get("revisions")):
            if not isinstance(r, dict):
                continue
            sd = s(r.get("side"))
            patches = r.get("patches")
            if isinstance(patches, list):
                per_side[sd] = per_side.get(sd, 0) + len(patches)
    for sd, n in sorted(per_side.items()):
        if n > 12:
            WARN.append(f"S7 {sd} 修补共 {n} 条（>12）：改得太多，回头看是不是论点是硬凑的")


if __name__ == "__main__":
    sys.exit(main())
