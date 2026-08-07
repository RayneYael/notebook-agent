# 实施计划

## 1. Pre-development

- [x] 读取 backend spec index、provider diagnostics、error handling、quality guideline，以及本任务
  `prd.md`、`design.md`、`research/root-cause.md`。
- [x] 再次检查 `app/agent/runtime.py` 与 `tests/test_agent_runtime.py` 当前 diff，标记日志任务已有 hunk，
  只做可审计的最小增量。
- [x] 运行现有 Agent 定向测试，记录实施前基线；若已有失败，区分用户工作区基线与本任务回归。

## 2. Implement deterministic convergence

- [x] 在 runtime 定义正常总轮次、普通搜索和扩展工具的分阶段常量，并在 `AgentDeps` 记录对应尝试状态。
- [x] 为 `search_segments` 和 detail retrieval tools 增加 per-step prepare，落实正常预算、citation
  repair search-only gate 和预算耗尽后的 tool omission。
- [x] 每个检索工具在实际边界更新预算状态；动作工具不计入检索预算。
- [x] 扩展动态 instructions，明确“证据足够立即回答 / 多来源候选按相关度比较和 item 去重 / 只选择性
  展开代表片段 / 工具撤下后基于已有证据或返回无证据”。
- [x] 让现有 model-settings callback 在保持脱敏 model-attempt 诊断的同时返回
  `parallel_tool_calls=false`。
- [x] 将默认 `AGENT_REQUEST_LIMIT` 与示例/部署文档从 6 调整为 8，保留 tool-call hard limit 10。
- [x] 保持 UsageLimits、tenant-scoped services、citation validator、action outcome 和消息持久化路径不变。

## 3. Regression tests

- [x] 添加循环型 `FunctionModel`：仍有 retrieval tool 就继续调用，工具撤下后返回有效 citation；断言
  正常调用 ≤5、普通搜索 ≤2、扩展调用 ≤3、最终不是 limit。
- [x] 添加连续零命中循环场景，断言 `not_found/no_evidence`。
- [x] 添加预算耗尽后的 citation mismatch → search-only repair → 有效 final 场景；断言最多 8 个模型
  请求且新搜索条件满足。
- [x] 添加多视频/章节场景：搜索返回多个 item 的候选，模型选择性展开至少两个来源，最终按 item 去重
  列表并为每项保留真实 citation。
- [x] 覆盖同一 item 的重复 segment、相邻重叠片段和两个相距较远章节：前两类可合并，后者必须在同一
  Top 5 视频项下保留两个时间位置；不得生成不存在的章节标题。
- [x] 添加/扩展 settings 观测，断言每个模型请求 `parallel_tool_calls is False`。
- [x] 保留显式 request/tool hard-limit fail-closed 测试，不让回归测试通过“删除安全限额”获得成功。

## 4. Validation

- [x] `.venv/bin/pytest -q tests/test_agent_runtime.py`
- [x] `.venv/bin/pytest -q tests/test_agent_actions.py tests/test_action_persistence.py`
- [x] `.venv/bin/pytest -q`
- [x] 检查新增诊断事件仍不包含 prompt/query/tool payload/evidence/exception message。
- [x] 复核所有受影响 backend spec 的 Quality Check；如当前 spec 没有新增可复用约定，记录无需更新的
  判断，不为单个实现细节扩写规范。

## 5. Rollback points

- prepare/tool visibility 导致动作或 citation repair 回归：只回退本任务的 visibility/state hunk，保留
  当前日志任务变更和全局 UsageLimits。
- provider 不接受 `parallel_tool_calls=false`：保留动态收敛设计，先在 model adapter 层确认兼容形式，
  不通过提高 raw tool-call limit 绕过。
- 最终提交前按 hunk 核对 runtime/tests；由于同文件存在他人/其他任务改动，不得把未识别改动静默
  纳入本任务 commit。
