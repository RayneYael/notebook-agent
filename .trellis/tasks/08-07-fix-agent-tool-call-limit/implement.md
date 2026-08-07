# 第二轮实施计划：检索与回答两阶段收敛

## 1. Planning and baseline

- [x] 保留第一版 5/2/3 tool visibility、Top-5 grouping、日志和测试实现作为当前 baseline。
- [x] 解析两条真实 trace，确认第一条为 projected tool-call batch failure，第二条为
  `output_tokens=2066/2000`，并写入两份 research。
- [x] 核对 PydanticAI 2.15.0：tool prepare 是 per-step、默认 batch 并行、sequential mode 不会丢弃
  batch calls、output token 是整个 run 累计值。
- [x] 审计 hybrid search merge，确认 segment-level top-k 没有 `item_id` 多样化。
- [x] 用户确认 composer 最终失败时返回确定性 evidence-only fallback。
- [ ] 实施前重新读取 task artifacts、backend specs 和两个 research，记录当前全套测试 baseline。

## 2. Provider-independent retrieval gate

- [x] 在 `AgentDeps` 增加 `last_retrieval_run_step` 和原子 `reserve_retrieval(run_step, kind)`，一次锁内检查
  same-step、5/2/3 budgets 并只为真实 backend execution 增加计数。
- [x] 将四个 retrieval tools 改为统一 typed `ok/skipped` envelope；skipped batch calls 不调用
  embedding/service，不写入 Citation cache，也不被解释为 zero-hit。
- [x] 在 Agent run 外使用 PydanticAI sequential execution mode；保留 `parallel_tool_calls=false` 作为提示。
- [x] 更新 diagnostics，允许 `agent_phase=retrieval|answer` 和 `tool_outcome=skipped`，保持生产 allow-list。
- [x] 删除 citation fresh-search repair 状态和对应 instructions/validator；保留预算耗尽后的 tool omission。
- [x] 验证 action/pending-confirmation tools 不消耗检索预算，mixed batch 的 terminal action outcome 仍优先。

## 3. Diversified search candidates

- [x] 将公开 search limit 默认改为 10，内部 BM25/vector candidate pool 固定有界为最多 50。
- [x] 在 `KnowledgeServices.search_segments()` 中先按 segment 去重，再按 `item_id` 排组选 Top 5，先输出
  每个 item 最强片段，再用剩余 slots 补充已选 item 的其他不同片段。
- [x] 保持 tenant filter、ready state、embedding failure 与 retrieval failure 合约不变。
- [x] 保留 Citation retrieval order/score，仅将 score 用于内部排序和开发诊断，不进入公开 equality/payload。
- [x] 增加 service unit tests：单 item crowding、六个 items、duplicate hybrid hit、同 item 远距离 segments、
  limit clamp、zero hit 和异常。
- [x] 增加 PostgreSQL integration：真实向量查询下 tenant A 的多视频候选不会 hydrate tenant B。

## 4. Tool-free structured composer

- [x] 新增内部 `AnswerSection` / `AnswerDraft` schema 和无工具 composer Agent；retrieval Agent 的 text output
  仅作为 stop signal 并被丢弃。
- [x] 从 Citation cache 构造 bounded composer evidence；composer 使用独立 `RunUsage`、request limit 2 和
  独立的 `AGENT_OUTPUT_TOKEN_LIMIT`。
- [x] composer validator 检查所有 segment ID 属于 allow-list、每个 section 至少一个 ID、跨 sections
  最多 5 个 item；失败只进行一次 answer-only retry。
- [x] 应用按 section 渲染 `[S…]`，并继续按视频顶层分组来源、保留同视频不同时间位置、不生成章节名。
- [x] retrieval usage limit 且已有 citations 时进入 composer；无 citations 时使用 stage-accurate失败/无证据。
- [x] composer retry、timeout、provider error 或 output-token limit 后丢弃草稿，返回 `status=ok` 的确定性
  evidence fallback。
- [x] fallback 最多 5 个视频，使用真实 title/time URL/bounded excerpt，不生成事实总结或 error code。

## 5. Persistence, errors, and configuration

- [x] 为知识成功答案与 fallback 构造 canonical user/final-answer ModelMessages；不保存 tool payload、
  retrieval stop text、invalid draft 或 retry prompt。
- [x] 保持 conversation turn sources、duplicate reply、thread ownership 和 context token budget 行为不变。
- [x] 按 retrieval/answer phase 分别映射 request/tool/output limit；删除 output-token 对“检索步骤上限”的
  错误文案。有证据的 composer failure 不产生 failed answer。
- [x] `.env.example` 和部署文档说明同一 `AGENT_OUTPUT_TOKEN_LIMIT` 对两个独立 stage 分别计数，而不是
  简单提高默认值。
- [x] 更新 backend executable spec：server batch gate、candidate diversification、composer/fallback、
  canonical history 和 failure matrix。

## 6. Regression tests

- [x] `FunctionModel` 第一次返回 2 个 searches、第二次返回 2 个 neighbors + 1 个 get_item；断言每 step
  只有第一个 backend call 执行，其余 skipped，计数不会竞态。
- [x] fake responses 填入非零 `RequestUsage.output_tokens`，复现 retrieval 2066/2000，并断言 composer
  获得新预算。
- [x] 覆盖 composer valid、unknown/missing ID 一次修复、超过 Top 5、二次无效 fallback、timeout、
  provider failure 和 output-token fallback。
- [x] 断言 citation repair 不再新增 search/embedding，invalid drafts/new retry messages 不持久化。
- [x] 覆盖 zero hit、embedding/retrieval failure、hard request/tool limit、no-search、empty/invalid composer。
- [x] 覆盖 action save/confirm/cancel/clarify、pending confirmation、mixed batch 和 terminal outcome。
- [x] 覆盖 canonical history、tenant isolation、conversation persistence、duplicate message、single reply 和
  diagnostics privacy。

## 7. Validation and smoke

- [x] `.venv/bin/pytest -q tests/test_knowledge_services.py tests/test_agent_runtime.py tests/test_diagnostics.py`
- [x] `.venv/bin/pytest -q tests/test_agent_actions.py tests/test_action_persistence.py tests/test_multiuser_integration.py`
- [ ] `.venv/bin/pytest -q`
- [x] `git diff --check`
- [x] `python3 ./.trellis/scripts/task.py validate 08-07-fix-agent-tool-call-limit`
- [ ] 部署后原问题 smoke：得到带 citation 的总结或 evidence fallback，不出现 usage-limit 文案。
- [ ] 部署后多视频/多章节 smoke：Top 5 视频、同视频多个真实时间点、无重复顶层 item、无编造章节。
- [ ] smoke 后恢复 `production + NOTEBOOK_AGENT_LOG_RETRIEVAL_CONTENT=false`。

## 7.1 Provider HTTP diagnostic follow-up

- [x] 在 `RequestDiagnostics.event()` 增加可选 `http_status`，仅投影非 bool 的 100–599 整数。
- [x] 在 retrieval 与 answer runtime 显式捕获/识别 `ModelHTTPError` 并传递 `exc.status_code`；保持现有
  无证据失败和有证据 fallback 行为，不记录 body/message。
- [x] 增加 diagnostics/runtime regressions：400/422/429/500/503、非法 status、私密 body sentinel、
  retrieval/answer phase 与 fallback 行为。
- [x] 更新 logging/provider/convergence executable specs，明确安全 status 与禁止字段。
- [x] 重跑定向测试、`git diff --check` 和 Trellis validate；完整测试与部署 smoke 仍按真实结果记录。

## 7.2 Development provider error detail follow-up

- [x] 将 provider HTTP 诊断分为 production/development 两种投影：生产保持 class/status，开发记录
  完整 exception message、provider model 和 response body。
- [x] 对非 JSON body 与非序列化值做开发日志兼容，不得让观测失败改变请求结果。
- [x] 增加生产脱敏和开发完整输出测试，并更新 logging/provider/convergence specs。
- [x] 启用本地 development 配置，重启网关并复现 HTTP 400，从 provider body 确认具体原因。

## 7.3 Thinking-mode composer compatibility

- [x] 将 composer 从 tool-based `output_type=AnswerDraft` 切换为 `PromptedOutput(AnswerDraft)`，保留
  Pydantic 解析、citation validator 和一次 output retry，不再发送 `tool_choice=required`。
- [x] 同步 FunctionModel/TestModel composer 测试桩为 JSON `TextPart`，并断言 composer 没有 output tools。
- [ ] 由本地操作者重启网关并执行真实 provider smoke；本次按要求不由 Codex 运行测试。

## 8. Rollback points

- batch gate 导致 tool protocol 回归：保留 sequential/atomic backend reservation，单独回退 envelope 文案。
- diversified search 延迟或排序异常：回退 over-fetch/grouping，保留两阶段 composer 与 server gate。
- composer provider 兼容异常：evidence fallback 作为安全路径，绝不恢复未经验证的单-run draft。
- persistence 回归：暂时令 knowledge `new_messages=[]`，保留最终 turn/sources；修复后再恢复 canonical history。
- 不回退 tenant predicates、UsageLimits、日志隐私、action terminal outcome 或单回复保障。
