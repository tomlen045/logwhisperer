# logwhisperer

**日志考古三件套：时间轴 / 突增检测 / trace 关联** —— 单文件零依赖 CLI（Python 3 标准库），拷走就能跑，macOS / Linux / Windows 通吃。

简体中文 | [English](README_EN.md) ｜ [Gitee](https://gitee.com/tomlen/logwhisperer)

## 解决什么问题

* 服务挂了翻几千行日志找"昨晚 10 点后第一次 ERROR" → **`lw tail`** 一条命令输出各级别首次/末次/条数时间轴
* "ERROR 是什么时候开始爆的"说不清 → **`lw spike`** 按秒桶聚合计数，自动找出相对基线突增 ≥8x 的异常尖峰
* 拿着一条 trace id 翻上翻下 → **`lw correlate`** 命中行 + 前后上下文一次给全
* grep 完还要自己数条数看时段 → **`lw grep`** 正则 + 时间窗 + 集中时段分布

## 快速使用

```bash
# 时间轴：各级别首次出现、末次出现、持续时长、条数
python3 lw.py tail app.log --since "2026-09-22 22:00"

# 突增检测：60秒一桶，找相对中位数基线突增 8 倍的点
python3 lw.py spike app.log --level ERROR --bucket 60

# trace 关联：命中 + 前后上下文
python3 lw.py correlate app.log --trace TRC-99

# 增强 grep
python3 lw.py grep app.log --pattern "db timeout" --since "2026-09-22 22:00"
```

输出示例（tail）：

```
时间轴: 09-22 10:00:00 → 09-22 11:07:00　共 114 行

级别     首次      末次      持续    条数  首条样例
🔴ERROR 09-22 11:00:00 09-22 11:04:55  4m55s      61  ...ERROR db timeout...
⚪INFO  09-22 10:00:00 09-22 11:07:00  1h7m       51  ...INFO api recovered...
```

## 设计要点

- **facts 归脚本，judgment 归模型**——lw 只报事实（时间/计数/突增倍数），不下根因结论
- **时间解析容错**——ISO8601 / nginx / syslog / syslog-ISO 四种格式自动识别；解析不了的行计数跳过，不静默吞
- **无时间戳行不神秘消失**——tail 输出时归入最后已知时间位置
- **全部只读**——不改日志、不删文件、零网络请求
- **gzip 原生支持**——`.gz` 直接喂

## 自测

```bash
python3 scripts/lw.test.py   # 13 项：三种时间格式 / gzip / 风暴检出 / 平稳不误报 / 边界
```

## 何时不用

- 全文检索聚合 → loki / elasticsearch
- 实时 watch → `tail -f`（这是考古工具不是监控工具）
- 日志完全无时间戳 → 解析器无用武之地

## License

MIT
