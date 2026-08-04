# 修复 YouTube 字幕轨选择与 yt-dlp 运行环境

## Goal

让 YouTube 摄入优先使用视频原始语言字幕，并把项目声明与实际虚拟环境中的 yt-dlp/impersonation 依赖同步到可用版本；最终以真实视频完成摄入且数据库记录、字幕分段和 embedding 全部合格作为完成标准。

## Background

- 回归视频 `qz9tKlF431k` 的元数据语言是 `en`，当前数据库条目也是 `lang=en`。
- 当前 `YouTubeConnector._select_track()` 在每类字幕中固定先找 `zh*`、再找 `en*`，因此对该英文视频选择了自动翻译轨 `zh-Hans`，随后下载字幕时收到 HTTP 429。
- 当前虚拟环境安装的是 `yt-dlp 2025.11.12`，而 `pyproject.toml` 已声明 `yt-dlp>=2026.7,<2026.9`；运行时还缺少 `curl-cffi`，所以 yt-dlp 报告没有可用 impersonation target。
- 这次错误发生在字幕下载阶段，尚未进入智谱 embedding；它不是 embedding 批大小或模型配置问题。
- `ffmpeg` 缺失会产生警告，但纯字幕路径使用 `--skip-download`，不依赖音视频转码，因此不属于本子任务的阻塞项。

## Requirements

### R1. 原始语言字幕选择

- 同时检查 `subtitles`（官方字幕）与 `automatic_captions`（自动字幕），以视频元数据 `language` 作为原始语言目标。
- 原始语言候选必须优先于翻译轨；同为原始语言时，官方字幕优先于自动字幕。
- 语言匹配需兼容完整语言码、基础语言码和 `-orig` 标记，例如 `en-US`、`en`、`en-orig`。
- 元数据语言缺失或没有匹配轨时，按确定性规则降级：显式 `*-orig` → 英文 → 中文 → 其他；同级仍优先官方字幕。
- 英文视频存在英文原始轨时不得再选择 `zh-Hans` 等自动翻译轨。
- `TextResult.source` 和 `TextResult.lang` 必须反映真正下载的字幕来源与基础语言。
- 保留当前“无任何字幕才返回 `NeedsASR`”的行为。

### R2. yt-dlp 运行环境

- 在 `pyproject.toml` 中为现有受控版本范围加入官方推荐的 default 与 `curl-cffi` extras，不改成无限上界。
- 实施时同步 `.venv`，使实际安装版本满足项目声明，不再使用 2025.11.12。
- 验证 `curl_cffi` 可导入，并且 yt-dlp 能列出至少一个 impersonation target。
- 保留当前无 cookie 持久化约束；只有新版本兼容性确实要求时才调整已验证的 YouTube player client 参数。

### R3. 自动化测试

- 增加字幕轨选择单元测试，覆盖英文原视频含 `en`/`en-orig` 和 `zh-Hans` 翻译轨的回归场景。
- 覆盖官方原语言优先、自动原语言兜底、元数据语言缺失及无字幕返回 `NeedsASR` 的关键分支。
- 现有 YouTube 429 分类、json3 解析、URL 匹配和 player client 测试不得回退。
- 完成修改后运行完整测试套件。

### R4. 真实摄入与数据库验收

- 首选重新摄入回归视频 `https://www.youtube.com/watch?v=qz9tKlF431k`；已存在的失败条目应能被重新处理，不创建重复内容条目。
- 如果该视频在正确请求原语言轨后仍被 YouTube 单视频限流，必须保留该失败证据，并用另一条带原始语言字幕的真实 YouTube 视频完成端到端数据库验收；不得用 mock 替代真实验收。
- 验收查询必须同时检查内容条目、分段、时间戳和向量维度，不以 CLI 仅打印 `state=ready` 作为完成依据。

## Constraints

- 不存储或提交 YouTube cookie、浏览器会话、代理凭据或用户密钥。
- 不降低空字幕保护：HTTP 200 + 空内容仍必须失败，不能写成 ready。
- 不改变智谱 Embedding-3、每批 64 条和 1536 维 schema。
- 不为了通过测试清理或覆盖用户已有数据库内容。

## Acceptance Criteria

- [x] 回归单测证明：元数据语言为英文且存在英文原始轨时，选择 `en`/`en-orig`，不会选择 `zh-Hans`。
- [x] 字幕选择的官方/自动来源优先级、缺语言降级和无字幕分支均有自动化覆盖。
- [x] `.venv` 中 yt-dlp 版本满足 `pyproject.toml` 的范围，`curl_cffi` 可导入，且至少存在一个可用 impersonation target。
- [x] 完整 pytest 套件通过。
- [x] 至少一个真实 YouTube 视频摄入后，`content_item.state='ready'`、`fail_reason IS NULL`、`text_source IN ('official_cc','auto_caption')`、`raw_object_key` 与 `content_hash` 均非空。
- [x] 真实条目有至少一个 `segment`；所有分段文本非空，`start_sec`/`end_sec` 合法，embedding 非空且 `vector_dims(embedding)=1536`。
- [x] 若验收条目是 `qz9tKlF431k`，其最终 `content_item.lang='en'`，且数据库中不存在同用户、同平台、同视频的重复条目。
- [x] 最终交付记录真实视频 ID、字幕轨、内容条目 ID、segment 数量和数据库验收查询结果。

## Out of Scope

- 安装 ffmpeg、下载音频或实现 ASR。
- 代理、cookie、PO token、验证码或 YouTube IP 解封方案。
- 改造 Celery/CLI 的通用 429 重试策略。
- 修改 embedding provider、切分策略或检索 Agent。

## Notes

- 本任务是父任务 `08-04-video-text-kb` 的 P0 可靠性子任务。
- 真正的 YouTube 429 仍按外部服务故障处理；修复目标是避免因为错误选择翻译轨而制造不必要的 429 请求。

## Completion Evidence (2026-08-05)

- 环境：`yt-dlp 2026.07.04`、`curl-cffi 0.15.0`；`--list-impersonate-targets` 列出 curl-cffi targets，`pip check` 通过。
- 自动化：`pytest -q` → `30 passed`。
- 真实摄入：`qz9tKlF431k` → `item=1 state=ready`；yt-dlp 元数据复查的选中轨为 `('auto_caption', 'en-orig')`。本次命令临时设置了 certifi 的 `SSL_CERT_FILE`，以处理本机 Python 对智谱 HTTPS 的 CA 校验。
- 数据库：`id=1`、`lang=en`、`text_source=auto_caption`、`segment_count=291`、`duplicate_count=1`；`has_raw`、`has_hash`、`text_ok`、`timing_ok` 和 `embedding_ok` 全为 `true`，`fail_reason=null`。
