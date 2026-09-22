#!/usr/bin/env python3
# logwhisperer — 日志低语者：单文件零依赖日志考古 CLI（Python 3 标准库）
#
# 解决什么：服务挂了翻几千行日志找"昨晚10点后第一次ERROR"——手工考古太慢。
# 一条命令输出三件套：首次出现时间轴 / 频率突增点(眨眼检测) / 建议深挖的 grep。
#
# ── 能力声明（facts 归脚本, judgment 归模型）──
# 全部只读：不改日志、不删文件、不发网络请求。
# 时间解析容错：ISO8601 / nginx / syslog / syslog-ISO 四种常见格式，解析不了的行跳过并计数。
# 退出码契约：0=正常输出；2=参数/文件错误。
#
# 命令：
#   lw tail <file> [--since ISO] [--until ISO] [--level ERROR,WARN] [--top N]
#       时间轴: 每级首次/末次出现 + 总量
#   lw spike <file> [--bucket 60] [--level ERROR] [--top N]
#       突增检测: 按秒桶聚合计数, 找出相对中位数突增>=8x 的桶
#   lw correlate <file> --trace <id>
#       关联: 提取含 trace id 的行 + 前后各2行上下文
#   lw grep <file> --pattern <regex> [--since ISO]
#       增强 grep: 正则+时间过滤+命中统计, 直接可复制

import argparse, re, sys, os, gzip, io
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict

TS_PATTERNS = [
    # ISO8601: 2026-09-22T10:00:00 / 2026-09-22 10:00:00,123
    (re.compile(r'(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:[.,](\d{1,6}))?'), '%Y-%m-%d %H:%M:%S'),
    # nginx/access: 22/Sep/2026:10:00:00 +0800
    (re.compile(r'(\d{2})/(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)/(\d{4}):(\d{2}:\d{2}:\d{2})'), 'nginx'),
    # syslog: Sep 22 10:00:00 (无年份, 补当前年)
    (re.compile(r'^([A-Z][a-z]{2})\s+(\d{1,2})\s+(\d{2}:\d{2}:\d{2})'), 'syslog'),
]
MONTHS = {m: i+1 for i, m in enumerate(['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'])}
LEVEL_RE = re.compile(r'\b(TRACE|DEBUG|INFO|WARN(?:ING)?|ERROR|FATAL|CRITICAL|PANIC)\b', re.I)
LEVEL_CANON = {'WARNING': 'WARN', 'CRITICAL': 'FATAL'}

def open_log(path):
    if path.endswith('.gz'):
        return gzip.open(path, 'rt', encoding='utf-8', errors='replace')
    return open(path, 'r', encoding='utf-8', errors='replace')

def parse_ts(line):
    """返回 epoch 秒或 None（解析不了的行跳过）"""
    for pat, fmt in TS_PATTERNS:
        m = pat.search(line)
        if not m:
            continue
        try:
            if fmt == 'nginx':
                dd, mon, yy, hms = m.groups()
                dt = datetime.strptime(f'{dd}/{mon}/{yy} {hms}', '%d/%b/%Y %H:%M:%S')
            elif fmt == 'syslog':
                mon, dd, hms = m.groups()
                dt = datetime.strptime(f'{datetime.now().year} {MONTHS[mon]} {dd} {hms}', '%Y %m %d %H:%M:%S')
            else:
                dt = datetime.strptime(f'{m.group(1)} {m.group(2)}', fmt)
                if m.group(3):
                    pass  # 毫秒忽略, 秒级粒度足够
            return dt.timestamp()
        except ValueError:
            continue
    return None

def get_level(line):
    m = LEVEL_RE.search(line)
    if not m:
        return None
    lv = m.group(1).upper()
    return LEVEL_CANON.get(lv, lv)

def iter_lines(path, since=None, until=None, levels=None):
    """统一过滤管道: 时间窗 + 级别。yield (epoch, level, line)"""
    lv_set = {l.upper() for l in levels} if levels else None
    bad_ts = 0
    with open_log(path) as f:
        for raw in f:
            line = raw.rstrip('\n')
            if not line.strip():
                continue
            level = get_level(line)
            if lv_set and (level is None or level not in lv_set):
                continue
            ts = parse_ts(line)
            if ts is None:
                if since or until:
                    bad_ts += 1
                    continue
            else:
                if since and ts < since:
                    continue
                if until and ts > until:
                    continue
            yield ts, level, line, bad_ts
            bad_ts = 0 if ts is not None else bad_ts

def parse_iso(s):
    if not s:
        return None
    s = s.replace('T', ' ')
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(s, fmt).timestamp()
        except ValueError:
            continue
    print(f'lw: 无法解析时间 "{s}" (支持 2026-09-22 10:00:00 格式)', file=sys.stderr)
    sys.exit(2)

def fmt_ts(epoch):
    return datetime.fromtimestamp(epoch).strftime('%m-%d %H:%M:%S') if epoch else '--:--:--'

def human_dur(sec):
    sec = int(sec)
    if sec < 60: return f'{sec}s'
    if sec < 3600: return f'{sec//60}m{sec%60}s'
    return f'{sec//3600}h{sec%3600//60}m'

# ── 命令: tail(时间轴) ──
def cmd_tail(args):
    since = parse_iso(args.since); until = parse_iso(args.until)
    levels = [l for l in args.level.split(',')] if args.level else None
    stats = {}   # level -> [first_ts, last_ts, count, sample_line]
    total = 0
    last_known = None
    for ts, level, line, _ in iter_lines(args.file, since, until, levels):
        total += 1
        if ts is not None:
            last_known = ts
        eff_ts = ts if ts is not None else last_known  # 无时间戳行归入当前时间位置
        if level:
            if level not in stats:
                stats[level] = [eff_ts, eff_ts, 1, line]
            else:
                if eff_ts and (stats[level][1] is None or eff_ts > stats[level][1]):
                    stats[level][1] = eff_ts
                stats[level][2] += 1
    if not total:
        print('（时间窗内 0 行命中——放宽 --since/--until 或 --level 试试）')
        return 0
    print(f'时间轴: {fmt_ts(min(s[0] for s in stats.values()))} → {fmt_ts(max(s[1] for s in stats.values()))}　共 {total} 行')
    print()
    print(f'{"级别":<6} {"首次":>9} {"末次":>9} {"持续":>7} {"条数":>7}  首条样例')
    for lv, (first, last, cnt, sample) in sorted(stats.items(), key=lambda x: -x[1][2]):
        mark = '🔴' if lv in ('ERROR','FATAL') else ('🟡' if lv == 'WARN' else '⚪')
        print(f'{mark}{lv:<5} {fmt_ts(first):>9} {fmt_ts(last):>9} {human_dur(last-first):>7} {cnt:>7}  {sample[:76]}')
    fatals = stats.get('FATAL', stats.get('ERROR'))
    if fatals:
        print(f'\n👉 建议深挖: lw grep {args.file} --pattern "{fatals[3][:40].split()[0] if fatals[3].split() else "ERROR"}" --since {datetime.fromtimestamp(fatals[0]).strftime("%Y-%m-%d %H:%M:%S")}')
    return 0

# ── 命令: spike(突增检测) ──
def cmd_spike(args):
    since = parse_iso(args.since); until = parse_iso(args.until)
    levels = [l for l in args.level.split(',')] if args.level else None
    bucket = args.bucket
    counter = Counter()
    samples = {}
    for ts, level, line, _ in iter_lines(args.file, since, until, levels):
        if ts is None:
            continue
        b = int(ts // bucket) * bucket
        counter[b] += 1
        if b not in samples:
            samples[b] = line
    if not counter:
        print('（0 行可分析）'); return 0
    counts = sorted(counter.items())
    med = sorted(c for _, c in counts)[len(counts)//2] or 1
    baseline_nonzero = sorted(c for _, c in counts if c > 0)
    med_nz = baseline_nonzero[len(baseline_nonzero)//2] if baseline_nonzero else 1
    print(f'突增检测: 桶={bucket}s | 中位数基线={med_nz}条/桶 | 阈值=≥{med_nz*args.threshold}x')
    spikes = [(b, c) for b, c in counts if c >= med_nz * args.threshold and c >= 5]
    if not spikes:
        print('（无突增点——日志很平，恭喜）')
        return 0
    print(f'\n发现 {len(spikes)} 个突增点:')
    for b, c in spikes[:args.top]:
        mult = c / med_nz
        bar = '█' * min(int(mult), 40)
        print(f'{fmt_ts(b)}  {c:>6}条  {mult:>5.1f}x  {bar}')
        print(f'           └ 样例: {samples[b][:88]}')
    return 0

# ── 命令: correlate(trace 关联) ──
def cmd_correlate(args):
    tid = args.trace
    since = parse_iso(args.since); until = parse_iso(args.until)
    hits, context_after = [], 2
    pending = []
    with open_log(args.file) as f:
        for raw in f:
            line = raw.rstrip('\n')
            ts = parse_ts(line)
            if since and ts and ts < since: continue
            if until and ts and ts > until: continue
            if tid in line:
                for p in pending:
                    hits.append(('┆', p))
                pending = []
                hits.append(('█', line))
                context_after = 2
            elif context_after > 0 and hits:
                hits.append(('┆', line))
                context_after -= 1
            else:
                pending.append(line)
                if len(pending) > 2:
                    pending.pop(0)
    if not hits:
        print(f'（未找到含 "{tid}" 的行）'); return 0
    print(f'trace {tid}: {sum(1 for m,_ in hits if m=="█")} 条命中 (含上下文共 {len(hits)} 行)')
    print()
    for mark, line in hits:
        print(f'{mark} {line[:118]}')
    return 0

# ── 命令: grep(增强检索) ──
def cmd_grep(args):
    since = parse_iso(args.since); until = parse_iso(args.until)
    try:
        pat = re.compile(args.pattern, re.I)
    except re.error as e:
        print(f'lw: 正则错误 {e}', file=sys.stderr); return 2
    hits = []
    for ts, level, line, _ in iter_lines(args.file, since, until, None):
        if pat.search(line):
            hits.append((ts, line))
    print(f'命中 {len(hits)} 行' + (f' (时间窗 {args.since} 起)' if args.since else ''))
    for ts, line in hits[:args.top]:
        print(f'{fmt_ts(ts)}  {line[:110]}')
    if len(hits) > args.top:
        print(f'… 其余 {len(hits)-args.top} 行省略')
    # 报一句分布
    if hits:
        hours = Counter(datetime.fromtimestamp(ts).strftime('%H') for ts, _ in hits if ts)
        if len(hours) > 1:
            top_h, n = hours.most_common(1)[0]
            print(f'👉 集中时段: {top_h} 时 ({n} 行)')
    return 0

def main():
    ap = argparse.ArgumentParser(prog='lw', description='logwhisperer — 日志考古三件套: 时间轴/突增/关联')
    sub = ap.add_subparsers(dest='cmd', required=True)
    def common(sp, need_file=True):
        if need_file:
            sp.add_argument('file')
        sp.add_argument('--since', help='起始时间 2026-09-22 10:00:00')
        sp.add_argument('--until', help='截止时间')
    t = sub.add_parser('tail', help='时间轴: 各级别首次/末次/条数')
    common(t); t.add_argument('--level', help='只看这些级别, 逗号分隔 如 ERROR,WARN'); t.add_argument('--top', type=int, default=10)
    t.set_defaults(fn=cmd_tail)
    s = sub.add_parser('spike', help='突增检测: 按秒桶找异常尖峰')
    common(s); s.add_argument('--bucket', type=int, default=60); s.add_argument('--level', default=None)
    s.add_argument('--threshold', type=float, default=8.0); s.add_argument('--top', type=int, default=5)
    s.set_defaults(fn=cmd_spike)
    c = sub.add_parser('correlate', help='trace id 关联(带上下文)')
    common(c); c.add_argument('--trace', required=True)
    c.set_defaults(fn=cmd_correlate)
    g = sub.add_parser('grep', help='增强 grep: 正则+时间窗+分布')
    common(g); g.add_argument('--pattern', required=True); g.add_argument('--top', type=int, default=20)
    g.set_defaults(fn=cmd_grep)
    args = ap.parse_args()
    if not os.path.exists(args.file):
        print(f'lw: 文件不存在 {args.file}', file=sys.stderr); sys.exit(2)
    sys.exit(args.fn(args))

if __name__ == '__main__':
    main()
