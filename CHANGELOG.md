# Changelog

版本号唯一事实源。

## 1.0.0 - 2026-09-22

- 初版：四命令（tail 时间轴 / spike 突增 / correlate trace关联 / grep 增强）
- 时间解析四种格式自动识别（ISO8601 / nginx / syslog / syslog-ISO），坏行计数跳过
- 自测 13 项全绿（三种时间格式 / gzip / 风暴检出 / 平稳不误报 / 边界）
- 开发过程抓出并修复 2 个真 bug：①无时间戳行进 stats 后 max(None,float) 崩溃 ②grep"集中时段"按月统计（fmt_ts[:2] 取的是月份非小时）
