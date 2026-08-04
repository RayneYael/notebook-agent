# Implementation Plan

## 1. Baseline and Regression Tests

- [x] 记录当前 `.venv` 的 yt-dlp/curl-cffi 状态和回归视频数据库状态。
- [x] 为 `_select_track()` 增加英文原视频 + `zh-Hans` 翻译轨的失败回归用例。
- [x] 增加官方原语言优先、自动原语言兜底、缺元数据语言和无字幕用例。
- [x] 单独运行 `tests/test_youtube.py`，确认新回归在旧实现上失败且既有测试仍可定位。

Review gate：测试夹具必须表达轨道元数据，不通过 monkeypatch 直接伪造最终返回值。

## 2. Implement Deterministic Track Ranking

- [x] 在 `app/connectors/youtube.py` 增加最小的语言归一化/排名辅助逻辑。
- [x] 保持 `_select_track()` 返回契约、`fetch_text()` 下载逻辑和错误类型不变。
- [x] 运行 `tests/test_youtube.py`，确认所有字幕选择和既有 YouTube 回归通过。

Rollback point：排序改动只限 connector；若接口扩散到 ingest 层，先停止并重新评审设计。

## 3. Update and Verify yt-dlp Environment

- [x] 将 `pyproject.toml` 依赖改为带 `default,curl-cffi` extras 的受控版本范围。
- [x] 从项目声明同步 `.venv`，更新旧的 2025.11.12。
- [x] 记录 yt-dlp 版本，验证 `curl_cffi` 导入及 impersonation target 列表。
- [x] 运行 `pip check`，确保依赖环境无冲突。

Review gate：不能用 `--no-update` 或隐藏 warning 代替环境修复。

## 4. Automated Validation

- [x] 运行 YouTube 定向测试。
- [x] 运行完整 pytest 套件。
- [x] 检查变更范围，确保未修改 embedding、ASR、通用重试或数据库 schema。

## 5. Real Ingestion

- [x] 使用已配置的智谱 key、PostgreSQL 和对象存储重新摄入 `qz9tKlF431k`。
- [x] 记录 yt-dlp 实际选择/请求的语言轨；英文回归视频不得请求 `zh-Hans`。
- [x] 回归视频在正确的英文轨下成功，因此不需要备用视频。
- [x] 确认 CLI 最终返回 `state=ready`，但不以此替代数据库查询。

## 6. Database Acceptance

- [x] 执行 `design.md` 中的聚合查询。
- [x] 核对 ready/null fail_reason、字幕来源、原始对象 key、内容 hash、segment 数量、非空文本、合法时间戳和 1536 维向量。
- [x] 确认 `(user_id, platform, platform_id)` 唯一且失败条目已原地恢复。
- [x] 在任务记录中写入真实视频 ID、轨道、item ID、segment 数量及查询结果。

Completion gate：只有自动化测试通过且数据库查询所有布尔验收项均为 true，任务才能完成。

## 7. Finish

- [x] 按 Trellis quality-check 流程复核实现与任务范围。
- [x] 判断字幕轨选择规则应沉淀到项目 spec，并已更新 `backend/youtube-connector.md`。
- [x] 更新父任务进度和本子任务验收证据。
- [ ] 提交本任务的代码与 Trellis 记录，然后完成/归档子任务。
