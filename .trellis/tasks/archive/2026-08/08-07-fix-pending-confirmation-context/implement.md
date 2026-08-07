# 实施计划

## 1. Fail-first reproduction

- [ ] fake model 复现：live pending + 当前消息“需要”时，模型未得到 pending server context，错误走
  search/no-evidence。
- [ ] PostgreSQL 固定证据：snapshot 前后 pending row 没有 consumed/cancelled/expiry 变化。

## 2. Read-only snapshot

- [ ] 增加最小 `PendingSaveSnapshot`/`inspect_save()`，验证 tenant/thread/kind/active/expiry/payload。
- [ ] missing、expired、malformed、cross-tenant/cross-thread 稳定返回 inactive，不产生数据库副作用。

## 3. Agent dynamic context

- [ ] AgentActionRuntime 每 run 缓存一次 pending count；service failure fail closed 且不泄露异常。
- [ ] 通过 deps-based dynamic instruction 注入可信 count，不改写 user question/history。
- [ ] instruction 覆盖肯定（含“需要”）、否定、含糊、明显无关四类；Agent 仍负责 tool choice。
- [ ] confirm 无 URL 参数，最终回复继续来自 canonical ActionOutcome，action draft 不持久化。

## 4. Automated validation

- [ ] unit：dynamic instruction 可见、confirm/cancel/clarify/unrelated 路由、每 run snapshot 一次。
- [ ] PostgreSQL：只读、expiry、tenant/thread isolation、重启式 service reconstruction。
- [ ] signed channel：bare URL → “需要” → queued；duplicate delivery exactly-once。
- [ ] regression：agent actions/runtime、pending、multiuser save E2E、knowledge citation guard。

建议命令：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -q -p no:cacheprovider \
  tests/test_agent_actions.py tests/test_pending_confirmation_postgres.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -q -p no:cacheprovider \
  tests/test_multiuser_integration.py -k signed_save_actions
PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -q -rs -p no:cacheprovider
git diff --check
python3 ./.trellis/scripts/task.py validate 08-07-fix-pending-confirmation-context
```

## 5. Runtime handoff

- [ ] 自动检查无 P1/P2 后，保持数据库/微信 identity/content，重启 gateway；仅在必要时重启
  worker/LangBot。
- [ ] 用户重新发送裸 URL，再回复“需要”，确认收到 queued/already-exists canonical summary。
- [ ] 人工微信验收由用户完成前，任务保持 `in_progress`。
