# 修复 Agent 检索工具调用上限

## Goal

让普通知识库问答在有界的检索轮次内收敛：证据足够时返回带真实 citation 的答案，证据不足时返回
稳定的无证据结果，而不是因为模型持续扩展检索而向用户暴露“检索步骤已达到上限”。

## Background

- 2026-08-07 的真实脱敏轨迹 `request_id=bef82b304c66469ca87ce0bbfec6cc5b` 显示，一个普通概念
  问题在 4 个工具轮次内执行了 10 次检索类工具，下一批 2 次并行调用使 PydanticAI 的预计计数变为
  12，超过 `AGENT_TOOL_CALLS_LIMIT=10` 后返回 `failed/limit`。
- `app/agent/runtime.py:32-46` 允许模型改写查询、重复搜索并按需展开相邻片段/元数据，但没有明确的
  收敛顺序或正常检索轮次上限。
- `app/agent/runtime.py:331-342` 只把 PydanticAI 的原始 request/tool/token 限额作为最后一道保护；
  它不会在正常预算耗尽时撤下检索工具或强制模型基于已有证据作答。
- PydanticAI 2.15.0 的 `UsageLimits.check_before_tool_call()` 按一整个待执行批次的 projected usage
  检查上限。因此日志中的 `used_value=12` 是下一批加入后的预计值，不代表后端已经执行了 12 次。
- 原始 Agent 设计已经要求“工具调用设置最大轮数和超时，防止无结果时循环搜索”
  （`.trellis/tasks/08-04-video-text-kb/design.md`），当前代码只实现了超时和原始调用数上限，缺少正常
  轮次终止机制。

## Requirements

### R1 — 正常检索必须确定性收敛并支持多来源问题

- 每个模型响应最多执行一个工具调用，避免单个响应并行扇出多个 `search_segments` /
  `get_neighbors` / `get_item` / `open_at`。
- 普通知识检索最多开放 5 个检索工具轮次；其中普通 `search_segments` 最多 2 次，邻居/元数据/定位
  扩展合计最多 3 次。该预算只统计上述 4 个只读检索工具，不消耗或改变视频保存/确认动作的语义。
- 每次 `search_segments` 默认可返回 6 个候选；模型必须把这些结果视为待比较的候选证据，而不是对
  每个结果机械调用 `get_neighbors`。
- 当答案可能分散在多个视频或章节时，模型必须根据工具返回的 excerpt、标题、来源和上下文判断
  相关度，按 `item_id`/标题去重和分组；只对最有希望且上下文不足的代表片段展开邻居。
- 用户要求查找、比较或汇总多个来源时，最终回答应按相关度提供列表，为每个视频/章节分别给出
  简短总结和真实 `[S…]` citation；不得把同一来源的多个相邻片段伪装成多个独立结果。
- 多来源回答采用按相关度排序的 Top 5 视频：顶层按 `item_id` 聚合，同一视频只出现一次，但聚合项
  必须保留该视频内所有具有不同含义的相关章节/时间位置。只去除重复 segment，或合并时间相邻且
  内容重叠的证据窗口；不得因为 item 去重丢弃相距较远的相关章节。
- 当前 Citation 不包含章节标题。首版在每个视频项下展示真实可点击时间位置，不根据正文猜测或
  编造章节名；未来若需要正式章节标题，应单独扩展 ingestion/service contract。
- 有真实 citation 后，模型应优先回答；只有证据上下文确实不足时才使用下一轮读取或改写搜索。
- 正常 5 轮预算或对应的分阶段预算用完后，下一次模型请求必须看不到检索工具，并收到稳定指令：只能基于已有工具结果
  作答；证据不足则明确返回“知识库中未找到足够证据”，不得继续尝试检索或依赖模型记忆。
- `AGENT_TOOL_CALLS_LIMIT` 继续作为异常/配置错误的最后保护，不通过单纯提高默认值掩盖循环。

### R2 — citation 修复仍保持失败关闭

- 若 output validator 拒绝了缺失或伪造的 citation，下一步只开放 `search_segments`，强制执行一次
  新搜索；不得用 `get_neighbors`、`get_item` 或机械替换编号绕过修复合约。
- 当正常 5 轮预算已经耗尽时，允许且只允许 1 个额外的 citation 修复搜索轮次；搜索完成后再次
  撤下检索工具，要求模型生成最终答案。
- 修复后的 citation 必须属于新搜索返回的真实片段。修复仍失败时保持现有
  `failed/answer_unavailable`，无效草稿、伪造 ID 和工具 payload 不进入回答或 conversation store。

### R3 — 用户结果与安全边界保持清晰

- 有足够证据时保持 `ok`、真实 citation、标题和链接行为不变。
- 检索成功但证据为空时保持 `not_found/no_evidence` 和“知识库中未找到足够证据”，不得误报内部
  usage limit 或系统故障。
- embedding、retrieval、timeout、request limit 和 output-token limit 的现有失败分类不改变。
- 若最后一道 tool-call hard limit 仍异常触发，不得返回或持久化不可信草稿；诊断继续记录安全的
  `limit_kind/limit_value/used_value`，不得记录问题、查询、证据或异常原文。
- tenant 隔离、工具参数白名单、单条入站消息只回复一次、动作工具及 pending confirmation 行为不变。

### R4 — 回归验证必须覆盖真实循环形态

- 使用 `FunctionModel` 构造一个只要仍能看到检索工具就继续调用的模型，证明运行时会撤下工具并在
  hard limit 前结束，而不是依赖测试模型“自觉”停止。
- 使用多个 `item_id` 和多个章节片段构造候选，证明 Agent 可以在一个 run 内完成两次候选搜索、
  选择性展开多个来源，并返回按来源分组、去重且每项带 citation 的列表。
- 覆盖普通有证据、连续零命中、citation 修复、修复失败和硬 request limit 场景。
- 验证每个模型请求的 `parallel_tool_calls` 为 false，且正常检索后端调用不超过 5 次、普通搜索不
  超过 2 次、上下文/元数据扩展不超过 3 次。
- 运行 Agent 定向测试及完整测试套件，不调用真实模型、embedding provider 或数据库外部服务。

## Acceptance Criteria

- [ ] AC1：循环型 fake model 对有证据问题最多执行 5 次只读检索工具，随后在检索工具已撤下的模型
  请求中返回有效 `[S…]` 答案；结果不是 `limit`。
- [ ] AC2：循环型 fake model 面对连续零命中时同样在 5 轮内停止，最终为
  `not_found/no_evidence`，用户不会看到“检索步骤已达到上限”。
- [ ] AC3：每个模型请求均设置 `parallel_tool_calls=false`；测试证明一次模型响应不会复制真实日志中
  2～3 个并行检索调用的扇出。
- [ ] AC4：正常预算耗尽后出现 citation mismatch 时，只重新开放 1 次 `search_segments`；新搜索后
  的真实 citation 可通过校验，且总模型请求不超过调整后的默认 `AGENT_REQUEST_LIMIT=8`。
- [ ] AC5：额外修复后仍缺失/伪造 citation 时返回一次 `failed/answer_unavailable`，无效草稿和编号
  不进入 `AgentAnswer.new_messages`、conversation store 或日志。
- [ ] AC6：现有 request limit、embedding failure、retrieval failure、动作工具、tenant isolation、
  conversation persistence 和诊断隐私测试继续通过。
- [ ] AC7：部署后用原问题“请为我解释强连通向量的含义”做一次人工 smoke；脱敏日志显示检索在正常
  预算内收敛，并得到带真实来源的答案或稳定的无证据结果，而不是 `tool_calls limit`。
- [ ] AC8：准备至少两个视频、多个章节都含相关证据的人工 smoke；回答按来源列出相关结果、解释各自
  相关性并引用真实片段，同一视频的相邻片段不会重复占据多个列表项。
- [ ] AC9：多来源回答最多列出 5 个按相关度排序的视频；同一 `item_id` 的两个相距较远且各自相关的
  章节不会被去重丢失，而是在同一个视频项下显示两个真实时间位置。

## Out of Scope

- 提高 `AGENT_TOOL_CALLS_LIMIT` 或放宽 timeout 作为主要修复。
- 更换模型、embedding provider、pgvector 查询、召回排序、reranker 或向量 schema。
- 记录问题正文、检索词、模型输出、tool arguments/result 或 citation ID 来调试。
- 修复/提交正在由 `08-07-initial-logging-setup` 开发的完整日志设施；本任务只兼容其当前改动。
- 保证知识库一定包含“强连通向量”或替用户纠正术语；无证据时仍必须失败关闭。

## Risks and Constraints

- `app/agent/runtime.py` 与 `tests/test_agent_runtime.py` 已有日志任务的未提交改动。实现必须在当前 diff
  上做最小增量，不能覆盖或回退那些改动；最终提交时也必须避免把无关工作静默并入本任务。
- 禁用并行工具调用会把 fan-out 改为有序检索；为容纳 5 个正常工具轮次、一次 draft、一次额外
  citation 修复搜索和一次最终答案，默认 `AGENT_REQUEST_LIMIT` 需要从 6 调整为 8。简单问题可以
  提前停止，不会被强制消费满 5 轮；复杂多来源问题获得额外覆盖的代价是最坏情况增加模型延迟和成本。

## Open Questions

无阻塞问题。用户确认首版返回按相关度排序的 Top 5 视频；同一视频的不同相关章节在聚合项下以
多个真实时间位置保留，不做全量穷举，也不在缺少元数据时生成章节标题。
