# yt-dlp Runtime Findings (2026-08-05)

## Local Evidence

- `.venv` 安装版本：`yt-dlp 2025.11.12`。
- 项目声明范围：`yt-dlp>=2026.7,<2026.9`。
- `curl-cffi` 未安装，因此 yt-dlp 报告没有 impersonation target。
- `ffmpeg` 未安装，但本任务的字幕路径使用 `--skip-download`；它是后续音频/ASR 需求，不是本次字幕下载的必要条件。
- 回归视频 `qz9tKlF431k` 元数据与数据库语言均为英文，失败请求却是 `zh-Hans`，与当前代码的中文优先规则一致。

## Official Guidance

- yt-dlp 官方安装文档要求 pip 安装时重新运行 pip 命令完成更新，并提供 `yt-dlp[default]` 安装方式：<https://github.com/yt-dlp/yt-dlp/wiki/Installation>
- 官方 README 说明 stable 版本可能因站点变化而过时，并列出 nightly 作为经常使用者的推荐通道；本项目仍采用受控稳定版本范围与每周真实摄入回归，而不是无界追踪 nightly：<https://github.com/yt-dlp/yt-dlp/blob/master/README.md#update>
- 官方 README 将 `curl_cffi` 列为推荐的 impersonation 依赖，并提供 `yt-dlp[default,curl-cffi]` extra：<https://github.com/yt-dlp/yt-dlp/blob/master/README.md#dependencies>
- 官方 FAQ 说明 429 通常代表请求 IP 被限流，可能需要等待、cookie 或相同 IP；本任务不试图绕过真实的外部限流：<https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp>

## Decision

保留项目原有的有上界版本策略，只补齐官方 extras 并同步实际环境。字幕轨错误通过确定性的原始语言排序修复；真实 429 继续作为外部瞬时故障，不与轨道选择混为一谈。
