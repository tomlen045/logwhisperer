---
name: logwhisperer
version: 1.0.0
description: "日志考古三件套：时间轴/突增检测/trace关联。触发：服务异常后翻日志（tail -f 几千行找不到重点）、问昨晚报错（什么时候开始/频率）、给一条日志找上下文、比较前后异常频率。一条命令输出时间轴+突增点+建议深挖的grep，替代手工 tail|grep 考古。"
---

# logwhisperer — 日志低语者

> 单文件零依赖 CLI（Python 3 标准库，拷走就能跑）。全部只读：不改日志、不删文件、不发网络。

## 三条约定

1. **facts 归脚本，judgment 归模型**——lw 只输出时间轴/计数/突增点等事实，根因判断由你+agent 完成
2. **无时间戳的行不神秘消失**——跳过时计数，tail 输出里以最后已知时间归位
3. **解析不了的行大声报**——四种常见格式（ISO8601/nginx/syslog/syslog-ISO）之外的格式统计跳过数，不许静默吞

## 快速使用

| 你说 | 它做 |
| --- | --- |
| "服务昨晚挂了，看下日志" | `lw tail app.log --since "2026-09-22 22:00"` → 各级别首次/末次/条数时间轴 |
| "ERROR 是什么时候开始爆的" | `lw spike app.log --level ERROR` → 按秒桶找突增点（相对中位数基线 ≥8x） |
| "TRC-99 这条 trace 全链路" | `lw correlate app.log --trace TRC-99` → 命中行+前后上下文 |
| "找所有 db timeout" | `lw grep app.log --pattern timeout --since ...` → 正则+时间窗+时段分布 |

## 命令

```
scripts/lw.py — Python 3 标准库，无依赖
  tail <file> [--since] [--until] [--level ERROR,WARN]   时间轴
  spike <file> [--bucket 60] [--threshold 8.0] [--level]  突增检测
  correlate <file> --trace <id>                           trace 关联+上下文
  grep <file> --pattern <regex> [--since]                 增强 grep
  # 支持 .gz 自动解压；无时间戳坏行计数跳过不崩溃
```

自测：`python3 scripts/lw.test.py`（13 项：三种时间格式/gzip/风暴检出/平稳不误报/边界）。

## 何时不用

- 需要全文检索聚合（用 loki/elasticsearch）
- 需要实时 tail（这是考古工具不是 watch 工具）
- 日志格式完全无时间戳（解析器无用武之地）
