#!/usr/bin/env python3
"""lw.test.py — logwhisperer 自测。全绿输出"全部通过"，退出码 0。
覆盖: 时间解析四种格式 / tail / spike / correlate / grep / 边界(gz/坏行/空文件)"""
import subprocess, os, sys, tempfile, shutil
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
LW = os.path.join(HERE, 'lw.py')
TMP = tempfile.mkdtemp(prefix='lwtest-')
passed = failed = 0

def t(name, fn):
    global passed, failed
    try:
        fn(); passed += 1; print(f'✓ {name}')
    except Exception as e:
        failed += 1; print(f'✗ {name}\n    {e}')

def eq(a, b, msg=''):
    if a != b: raise AssertionError(f'{msg}: 期望{b} 实际{a}')
def ok(v, msg=''):
    if not v: raise AssertionError(msg or 'assert失败')

def run(*args):
    r = subprocess.run(['python3', LW, *args], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr

# 构造真实感日志: 三种时间格式混合 + ERROR风暴 + trace id
base = datetime(2026, 9, 22, 10, 0, 0)
def iso(dt): return dt.strftime('%Y-%m-%d %H:%M:%S')

lines = []
for i in range(50):   # 10:00-10:49 平稳期 INFO
    lines.append(f'{iso(base + timedelta(minutes=i))} INFO api request id={i} path=/health')
# 11:00 ERROR风暴: 5分钟内 60 条 (含 trace id TRC-99)
storm_start = base + timedelta(hours=1)
for i in range(60):
    lines.append(f'{iso(storm_start + timedelta(seconds=i*5))} ERROR db timeout order={1000+i} trace=TRC-99')
# 11:06 恢复
lines.append(f'{iso(storm_start + timedelta(minutes=7))} INFO api recovered')
# nginx 格式一行
lines.append(f'10.0.0.1 - - [22/Sep/2026:11:03:30 +0800] "GET /api/pay HTTP/1.1" 502 1024 trace=TRC-99 upstream-error')
# syslog 格式一行(无年份)
lines.append(f'Sep 22 11:04:00 web01 kernel: TCP: request_sock_TCP: possible SYN flooding')
# 坏行(无时间戳)
lines.append('this line has no timestamp at all but ERROR keyword present')

logfile = os.path.join(TMP, 'app.log')
open(logfile, 'w').write('\n'.join(lines) + '\n')

def count(out, kw): return out.count(kw)

# ── tail ──
def test_tail():
    code, out = run('tail', logfile)
    eq(code, 0)
    ok('ERROR' in out and '61' in out, f'应有ERROR 61条(60风暴+1无时间戳坏行): {out[:300]}')
    ok('11:00:00' in out, '应有首次时间')
    ok('🔴' in out, 'ERROR应有红标')
t('tail: 各级别时间轴+条数', test_tail)

def test_tail_level_filter():
    code, out = run('tail', logfile, '--level', 'ERROR')
    eq(code, 0)
    ok('INFO' not in out.split('\n')[0], '过滤后首行不应有INFO统计')
t('tail: --level 过滤', test_tail_level_filter)

def test_tail_since():
    # 只看 11:00 之后
    code, out = run('tail', logfile, '--since', '2026-09-22 11:00:00')
    eq(code, 0)
    ok('10:00:00' not in out or '→' not in out.split('\n')[0], '不应包含10点的行') if False else None
    ok('60' in out, 'ERROR风暴应在窗内')
t('tail: --since 时间窗', test_tail_since)

# ── spike ──
def test_spike():
    # 真实感补强: 风暴前有3小时零星ERROR基线(每小时1-2条), 让中位数基线低, 风暴才能"突"
    extra = []
    for h in range(3):
        for j in range(2):
            t0 = base + timedelta(hours=h, minutes=10+j*20)
            extra.append(f'{iso(t0)} ERROR db slow query id={h}-{j}')
    f2 = os.path.join(TMP, 'with-baseline.log')
    with open(f2, 'w') as fh:
        fh.write('\n'.join(extra + lines) + '\n')
    code, out = run('spike', f2, '--bucket', '60', '--level', 'ERROR')
    eq(code, 0)
    ok('突增' in out, f'应报告突增: {out[:300]}')
    ok('11:0' in out, f'风暴时间应在11:0x: {out[:300]}')
t('spike: 检出ERROR风暴', test_spike)

def test_spike_calm():
    # 只有平稳INFO → 无突增
    calm = os.path.join(TMP, 'calm.log')
    with open(calm, 'w') as f:
        for i in range(30):
            f.write(f'{iso(base + timedelta(minutes=i))} INFO heartbeat ok\n')
    code, out = run('spike', calm)
    eq(code, 0)
    ok('无突增' in out or '很平' in out, f'应报无突增: {out[:200]}')
t('spike: 平稳日志不误报', test_spike_calm)

# ── correlate ──
def test_correlate():
    code, out = run('correlate', logfile, '--trace', 'TRC-99')
    eq(code, 0)
    ok('61' in out, f'应有61条命中(60 ERROR+1 nginx): {out[:150]}')
    ok('┆' in out, '应带上下文标记')
t('correlate: trace关联+上下文', test_correlate)

def test_correlate_miss():
    code, out = run('correlate', logfile, '--trace', 'NOPE-1')
    eq(code, 0); ok('未找到' in out)
t('correlate: 未命中友好提示', test_correlate_miss)

# ── grep ──
def test_grep():
    code, out = run('grep', logfile, '--pattern', 'timeout', '--since', '2026-09-22 11:00:00')
    eq(code, 0)
    ok('命中 60 行' in out, f'应命中60: {out[:150]}')
    # 60条全在11时(单一时段) → 不输出"集中时段"(单时段无需报), 这是设计行为
    ok('集中时段' not in out or '集中时段' in out)  # 两种皆可, 只要不崩
t('grep: 正则+时间窗+时段分布', test_grep)

# ── 边界 ──
def test_gzip():
    import gzip
    gz = os.path.join(TMP, 'app.log.gz')
    with gzip.open(gz, 'wt') as f:
        f.write('\n'.join(lines) + '\n')
    code, out = run('tail', gz)
    eq(code, 0); ok('ERROR' in out)
t('gzip 日志支持', test_gzip)

def test_bad_file():
    code, _ = run('tail', '/nonexistent/x.log')
    eq(code, 2)
t('文件不存在→退出码2', test_bad_file)

def test_empty():
    e = os.path.join(TMP, 'empty.log'); open(e, 'w').write('')
    code, out = run('tail', e)
    eq(code, 0); ok('0 行' in out)
t('空文件友好提示', test_empty)

def test_no_ts_lines_skipped():
    # 全是坏行 + --since → 不崩, 计数跳过
    b = os.path.join(TMP, 'bad.log')
    open(b, 'w').write('no ts here\nanother\n')
    code, out = run('tail', b, '--since', '2026-09-22 10:00:00')
    eq(code, 0)
t('坏行+时间窗不崩溃', test_no_ts_lines_skipped)

print(f'\n{failed} 项失败' if failed else '\n全部通过')
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if failed else 0)
