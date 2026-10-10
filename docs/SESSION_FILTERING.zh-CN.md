# 内部会话来源过滤

Codex 会为 Guardian review、压缩、审阅和子代理等内部工作保存会话。它们的标题只是展示文字，不能作为主会话资格依据。旧代码只排除了 SQLite `thread_source = 'subagent'`，因此 `guardian_review` 或结构化来源可能进入主会话列表；旧 detector 账本中的 `kind=main` 也可能在快照合并时重新加入这些记录。这是代码路径中的缺口，并不表示已确认本机曾为 Guardian 发起自动探测。

本修复在 [nerfed](../plugin/skills/is-gpt-nerfed/scripts/nerfed) 中统一判断来源：

- 识别旧 `subagent`、`guardian_review`，以及 `subAgentReview`、`subAgentCompact`、`subAgentThreadSpawn`、`subAgentOther` 等大小写、下划线形式。
- 接受 `source` 的对象和 JSON 字符串形式，例如 `{"subagent":{"other":"guardian"}}`；读取数据库可选来源字段，并用 rollout 首条 `session_meta` 补充判断。
- 来源缺失、未知、无法解析或 metadata 不可读时，保留原有主会话回退。标题恰好为 `Guardian review` 的普通主会话仍显示，`parent_thread_id` 也不会单独导致用户 fork 被排除。

数据库查询以只读连接和同一读事务检查 schema、读取排序结果，再用游标分批筛选，达到所需主会话数量后停止。过滤发生在 25/40 条主会话上限之前，避免大量较新的内部会话挤占名额。没有 `source`、`parent_thread_id` 或 `preview` 的旧 schema 仍保留原有 model、reasoning effort 等字段。

入口行为：

| 入口 | 内部会话处理 |
| --- | --- |
| 数据库近期主会话、默认模型回退、交互目标选择 | 根据来源排除后取条数上限 |
| Hook SessionStart、Stop 调度 | 重新关联来源，将错误的旧 `kind=main` 纠正为 `subagent`；内部 Stop 不触发会话 worker 或 fresh worker |
| Snapshot 账本合并 | 再检查数据库、账本及 rollout 来源，防止旧 main 记录复活 |
| tick、直接 spawn、worker、显式 fork/self/排队探测 | 已知内部来源在生成新探测记录或推理前被拒绝；worker 清理运行标记并纠正分类 |
| audit | 默认排除已知内部来源；显式 `--include-subagents` 包括 Guardian 等全部已知内部会话 |

修正分类不删除 Codex 数据库、rollout、detector 会话账本或既有探测索引。历史探测仍可在探测历史中查阅；拒绝一个内部目标不会写入虚假的 `INVALID` 探测结果。指纹 bank、挑战文本、scorer 和探测模型力度均不在本修复范围内。

## 隔离验证

```powershell
python -X utf8 -m unittest discover -s tests -p test_session_filtering.py -v
```

[回归测试](../tests/test_session_filtering.py) 为每个测试创建临时 `CODEX_HOME` / `NERFED_HOME` 和 SQLite/rollout fixture。只允许使用 `tests/fake_codex.py`，不会运行真实模型推理。

覆盖 15 项测试：来源变体和未知来源回退；DB 列表与旧 schema；151 条较新内部会话之后仍能取满 40 条主会话且只建立一次读取连接；旧 main 账本重分类与快照过滤；数据库、rollout、既有索引和探测历史保留；hook、tick、直接 spawn、worker、显式 fork/self 及 sandbox 排队拒绝；最近 hook 目标回退；同名主会话和用户 fork 使用 fake Codex 成功探测；audit 默认与显式包含语义。

目标测试结果：15 项全部通过。全套兼容性测试和 Windows 发行构建由整合验收统一记录。

整合验收另对本机真实数据库做了一次只读兼容检查：相同的 48 小时条件下，旧查询返回 40 条，其中 34 条为 `guardian_review`；新 `db_recent_threads_detailed` 返回 7 条，统一分类器识别出的内部条目为 0。该次新查询耗时 16.35 ms，隔离状态目录没有 `errors.log`。数据库以 `mode=ro` 打开，detector 状态全部指向临时目录，没有新推理或用户状态写入。这是该数据快照的一次兼容验收，不是普遍性能指标。
