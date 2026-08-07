# Agent 检索轮次收敛设计

## 1. Boundary

修复限定在 `KnowledgeAgent` 的工具可见性、每轮模型设置和相应回归测试。检索 service、embedding、
pgvector SQL、citation 数据结构、channel contract 和数据库 schema 不变。

## 2. Runtime state

在 `AgentDeps` 增加本次 run 内的检索尝试计数，和现有 `tool_calls` 日志计数分离：

```text
retrieval_calls       search/get_neighbors/get_item/open_at 尝试数
search_calls          已有字段；用于 citation fresh-search gate
tool_calls            所有工具边界的诊断序号（现有字段）
```

固定正常预算为 5 个检索工具轮次，其中普通搜索最多 2 次、上下文/元数据/定位扩展最多 3 次。
它是 Agent 合约常量，不新增环境变量；外部
`AGENT_TOOL_CALLS_LIMIT` 保持全局 safety net，避免产生两组含义相近但可能互相矛盾的部署配置。

## 3. Tool visibility state machine

四个只读检索工具共用 `prepare` 策略：

```text
normal retrieval (retrieval_calls < 5)
  search_segments visible while normal search_calls < 2
  detail tools visible when citations exist and expansion_calls < 3

citation repair pending and no fresh search yet
  search_segments visible
  get_neighbors/get_item/open_at hidden

normal total/stage budget exhausted and no repair search required
  all retrieval tools hidden

fresh repair search completed
  all retrieval tools hidden when normal budget is exhausted
```

“repair pending”沿用现有条件：`citation_repair_search_calls is not None` 且当前 `search_calls` 没有超过
首次 mismatch 时的快照。这样修复搜索成功后，validator 仍用现有逻辑证明结果来自更新的一代搜索。

正常搜索结果按 `item_id`/标题视为多来源候选集合。动态 instructions 要求模型先比较 excerpt 和标题，
再为上下文不足的代表片段使用扩展预算；最终选择最多 5 个相关视频。同一来源的多个 segment 在顶层
合并为一个来源项，但聚合时保留语义不同、时间相距较远的证据位置；只有相同 segment 或相邻重叠
窗口可以去重。由于 Citation 只有时间链接而没有章节标题，输出使用真实时间点，不生成章节名。
`Citation` 已包含 `item_id`、标题、excerpt 和可点击 URL，因此模型不需要为了每个候选机械调用
`get_item` 或 `open_at`。

保存/确认动作工具不经过检索 prepare 策略。pending confirmation 的动态 instructions 和 terminal
action outcome 行为保持不变。

## 4. Model request contract

当前 `model_settings` 回调在每个模型请求前记录 `model_attempt`。让该回调同时返回：

```python
{"parallel_tool_calls": False}
```

这保证正常 5 轮预算与最多 5 次真实工具执行一一对应，避免模型单个响应跨过应用层预算。该字段属于
PydanticAI 通用 `ModelSettings`，当前 OpenAI-compatible provider 支持。

动态 instructions 根据依赖状态补充收敛指令：

- 正常阶段：有足够证据立即回答；多来源问题先跨候选判断相关度、按来源去重，只选择性展开；改写
  搜索/扩展上下文必须占用有限下一轮。
- 工具撤下阶段：只能使用已返回 citation；不足则输出稳定无证据文案。
- citation repair：只调用重新开放的 `search_segments`，不要尝试其他工具。

业务正确性不依赖模型遵守文案；工具的动态撤下是确定性边界。

## 5. Budget interaction

默认最坏路径：

| Model request | Operation |
| ---: | --- |
| 1 | normal retrieval 1 |
| 2 | normal retrieval 2 |
| 3 | normal retrieval 3 |
| 4 | normal retrieval 4 |
| 5 | normal retrieval 5 |
| 6 | invalid draft, validator requests repair |
| 7 | one fresh `search_segments` repair |
| 8 | final repaired answer |

因此把默认 `AGENT_REQUEST_LIMIT` 从 6 调整为 8。正常答案最晚在第 6 个请求结束；citation 修复的
最坏路径占满 8 个请求。正常路径最多 5 个检索工具调用，修复路径最多 6 个，仍低于
`AGENT_TOOL_CALLS_LIMIT=10`。

若部署显式把 request limit 配得更小，现有 `UsageLimitExceeded` 继续安全失败；本任务不静默改写管理员
配置。若 provider 不支持 `parallel_tool_calls=false`，全局 tool-call hard limit 仍阻止无界执行，
测试和部署 smoke 应暴露兼容性问题。

## 6. Failure mapping

- 0 citations + 正常预算结束：沿用 run 后检查，返回 `not_found/no_evidence`。
- 有 citations + 合法 `[S…]`：返回 `ok`。
- citation repair 重试耗尽：沿用 `failed/answer_unavailable`。
- embedding/retrieval exception：保持当前稳定错误。
- 原始 request/tool/output-token hard limit：保持 fail closed 和安全诊断；正常回归不得走到 tool limit。

不在 hard-limit catch 中尝试拼接已有 evidence 或另启一个 answer-only 模型，因为异常路径没有已验证
的最终草稿。

## 7. Compatibility and rollback

- 不改变公开 API、配置文件、数据库或 tool schema。
- Top 5 聚合由 Agent 基于可信 Citation 完成，不新增未经验证的相关度分数或章节字段。
- `.env.example` 与部署文档中的 request-limit 默认示例同步为 8；显式部署配置保持管理员选择。
- 不改变工具返回 payload，历史消息可继续由 `ModelMessagesTypeAdapter` 解析。
- 回滚时可移除 prepare/dynamic convergence instructions 并恢复 `parallel_tool_calls` 默认值；全局
  UsageLimits 始终保留。
- 当前工作区的日志任务也修改了 runtime/tests；实现和回滚只能处理本任务新增 hunk，不得整文件还原。
