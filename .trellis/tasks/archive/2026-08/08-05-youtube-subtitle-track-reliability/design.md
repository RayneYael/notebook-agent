# Technical Design

## Scope and Boundaries

本任务只改动 YouTube 字幕轨决策、yt-dlp 依赖声明及相应测试。摄入编排、对象存储、切分、智谱 embedding 和数据库 schema 保持不变。

预计代码边界：

- `app/connectors/youtube.py`：轨道候选归一化与选择。
- `tests/test_youtube.py`：选择规则回归测试。
- `pyproject.toml`：yt-dlp extras 与受控版本范围。
- `.venv`：实施阶段同步依赖，不纳入版本控制。

## Subtitle Selection Contract

### Inputs

- `data["language"]`：yt-dlp 返回的视频原始语言，可为空，可能是 `en` 或 `en-US`。
- `data["subtitles"]`：官方字幕，键为语言码。
- `data["automatic_captions"]`：自动字幕及自动翻译轨，键为语言码。

### Normalization

- 比较时统一小写并把 `_` 视为 `-`。
- 基础语言取第一个 `-` 之前的部分，但保留完整码用于精确匹配。
- 输出仍使用 yt-dlp 提供的原始语言键，避免请求一个并不存在的归一化键。

### Ranking

将两个字幕来源展平成候选，并使用稳定排序。排序维度依次为：

1. **语言组**
   - 与元数据原始语言完整或基础语言匹配；
   - 显式 `*-orig`；
   - 英文；
   - 中文；
   - 其他。
2. **来源**：`official_cc` 优先于 `auto_caption`。
3. **匹配精度**：精确完整码/`<lang>-orig` 优先于仅基础语言相同。
4. **原始顺序**：作为最终确定性 tie-breaker。

因此，任何原始语言轨都排在翻译轨之前；若官方与自动都提供原始语言，则官方轨获选。元数据语言为空时，显式 `*-orig` 提供最可靠的原语言信号。

### Output

- 有候选：返回 `(source, exact_track_key)`。
- 无候选：返回 `None`，上层继续映射为 `NeedsASR`。
- 下载完成后，`TextResult.lang` 使用所选轨的基础语言。

## Dependency Update

把依赖声明从普通 `yt-dlp` 改为：

```toml
"yt-dlp[default,curl-cffi]>=2026.7,<2026.9"
```

实施时从该项目声明同步虚拟环境，然后通过以下三类证据确认环境一致：

- `python -m yt_dlp --version` 落在声明范围内；
- `python -c "import curl_cffi"` 成功；
- `python -m yt_dlp --list-impersonate-targets` 至少输出一个目标。

不在代码中压制版本、ffmpeg 或 impersonation 警告；缺依赖应由环境验收暴露。

## Data Flow

```text
fetch_meta
  → metadata language + official/automatic track maps
  → deterministic original-language ranking
  → request exactly one json3 track
  → existing empty-response guard
  → object store
  → chunk + Zhipu embedding
  → content_item ready + segments
  → database acceptance query
```

## Compatibility and Failure Handling

- `_select_track()` 仍返回现有的 `(source, lang)` 形状，避免扩散接口改动。
- `fetch_text()` 的官方/自动下载 flags、单文件保护、json3 解析和空字幕保护保持原状。
- HTTP 429 继续抛出 `TransientFetchError`；本任务不改变通用重试语义。
- 如果升级后 `android_vr` client 不再兼容，先以真实 metadata/subtitle smoke test 证明，再做最小调整并补测试，不能仅凭警告替换。

## Database Acceptance Query

真实摄入后使用一条聚合查询验证：

```sql
SELECT
  ci.id,
  ci.platform_id,
  ci.state,
  ci.lang,
  ci.text_source,
  ci.fail_reason,
  ci.raw_object_key IS NOT NULL AS has_raw,
  ci.content_hash IS NOT NULL AS has_hash,
  COUNT(s.id) AS segment_count,
  BOOL_AND(length(btrim(s.text)) > 0) AS text_ok,
  BOOL_AND(s.start_sec IS NOT NULL AND s.end_sec > s.start_sec) AS timing_ok,
  BOOL_AND(s.embedding IS NOT NULL AND vector_dims(s.embedding) = 1536) AS embedding_ok
FROM content_item ci
JOIN segment s ON s.item_id = ci.id
WHERE ci.platform = 'youtube' AND ci.platform_id = :video_id
GROUP BY ci.id;
```

另查 `(user_id, platform, platform_id)` 的数量为 1，确认失败条目重跑没有制造重复数据。

## Rollout and Rollback

- 先加失败测试，再实现排序，以测试锁定行为。
- 依赖声明和环境同步独立验证；代码回归与环境问题可以分开定位。
- 若新选择器异常，只回退排序实现与对应测试；不删除已经成功摄入的数据库/对象存储数据。
- 若新 yt-dlp 版本出现外部兼容问题，保留 extras，但在允许范围内回退到最近已验证版本，并记录真实 smoke test 证据。
