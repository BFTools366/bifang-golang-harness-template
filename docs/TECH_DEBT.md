# 技术债

本文件记录已知但不在当前任务解决的问题、影响范围和复核条件。条目只在问题真实存在时保留；问题消除后必须恢复真实状态，不新增修复流水账。

| 编号 | 项目 | 影响 | 处理条件 | 状态 |
|---|---|---|---|---|
| LIM-001 | 校验器仅覆盖模板自身资产 | 真实下游代码由其工具链验证，Harness 校验器不感知 | 下游需要统一门禁时增加可插拔检查接口 | Open |
| LIM-002 | 行数门禁按物理行计数 | 单行超长代码或高度压缩写法可能绕过阈值含义 | 出现真实规避案例时补充复杂度度量 | Open |
| LIM-003 | Go 中文注释门禁只做语法层扫描 | 无法证明注释有业务意义 | 保持人工/Agent 语义复核，不自动化质量评分 | Mitigated |
| LIM-004 | 环境门禁仅覆盖 Git 与 Go | 下游若引入 Node 或 Python 工具链无受管恢复路径 | 真实下游需要时按同一模式扩展 | Open |
| LIM-005 | 交叉编译未覆盖 cgo 依赖 | 引入 cgo 后需目标平台工具链，交叉编译可能失败 | 首次引入 cgo 时补充构建矩阵与文档 | Open |
| LIM-006 | 雪花 ID 依赖时钟单调性 | 时钟回拨时可能产生重复 ID | 依赖 `idgen` 的回拨保护；跨机器部署需独立 worker ID 分配 | Mitigated |
| LIM-007 | 配置仅支持文件 + 环境变量 | 无配置中心、无热更新 | 出现多实例一致性需求时评估 | Open |
| LIM-008 | 泛型仓储未覆盖联表与复杂聚合 | 复杂查询仍需在仓储内手写 SQL，边界容易模糊 | 出现第二处重复复杂查询时抽取查询对象 | Open |
| LIM-009 | 发布上下文复核依赖 helper 自律 | 未通过 helper 的手工 Git 操作不受门禁约束 | 出现真实绕过案例时增加提交钩子 | Open |
| LIM-010 | Skills 语义审查依赖人工 | 无法机械证明 Skill 与事实源一致 | 保持发布时的语义审查清单 | Mitigated |
| LIM-011 | 无内置 CI 配置 | 每次验证依赖本地执行 | 发布给其他用户或多人协作时增加 | Open |
| LIM-012 | 初始化 E2E 覆盖本机宿主 | 其他平台未验证 | 需要跨平台发布时按平台补充 | Open |
| LIM-013 | 统一响应体字段为固定 5 形状 | 特殊接口（文件下载、SSE）需显式例外 | 出现真实需求时按 ADR 记录例外 | Mitigated |
| LIM-014 | 错误码即 i18n 键，缺少编译期校验 | 新增错误码遗漏翻译时只能运行时发现 | 出现真实缺失案例时增加键一致性检查 | Open |
| LIM-015 | 无鉴权与限流基线 | 中性脚手架不内置认证，所有对外路由默认开放 | 下游上线前必须自行补充；不属于模板范围 | Mitigated |
| LIM-016 | 迁移工具未纳入模板 | 数据库 schema 变更依赖下游自选工具 | 真实下游需要时按 `docs/GO_WEB_TEMPLATE.md` 边界补充 | Open |
| LIM-017 | 行数统计脚本为 Python 实现 | 需要 Python 3 环境 | 接受；作为 `scripts/` 维护脚本的既定前提 | Mitigated |
| LIM-018 | `release/` 目录天然不进入版本控制 | 候选被清理后证据不可追溯 | 发布成功后由 Verification 记录长期事实 | Mitigated |
| LIM-019 | 无性能与压力基线 | 吞吐、延迟无量化承诺 | 出现真实性能需求时建立基准 | Open |
| LIM-020 | `go.sum` 与兼容下界职责分离 | 可能误把锁文件当最低兼容事实 | 保持 `docs/ENGINEERING_RULES.md` §2.1 的规则说明 | Mitigated |
| LIM-021 | Swagger 文档版本号为静态注解 | `cmd/server/main.go` 的 `@version` 与 `docs/docs.go` 的 `version` 不随版本门禁更新，而二进制真实版本由 `-ldflags` 注入，两者可能不一致 | 属模板既定边界：下游按需自行调整该注解或改为运行时覆盖；出现真实需要时再评估自动同步 | Mitigated |
| LIM-022 | `test_harness_upgrade.py` 存在偶发失败 | 同一代码两次执行出现一次 `failures=1`、一次全过；失败用例名未捕获，根因未知 | 该套件需一次带输出捕获的重复执行定位 flaky 用例；复现前不接受其单次结果作为门禁证据 | Open |
| LIM-023 | `test_development_environment_gates_windows.py` 5 个用例失败 | 26 个用例中 5 个失败：Go 归档升级用例未设 `AFH_ALLOW_FILE_URLS`；`file://` 分发索引 URL 无法按文件复制（`Copy-Item` 目录→文件）；3 个持久 PATH 身份用例的夹具未预置 `AFH_TEST_USER_PATH_FILE`，且其中一个所用工具均在阈值之上导致断言分支不触发 | 需要一次对 Windows 门禁脚本与用例契约的逐项对齐；修复前该套件结果不可作为门禁证据 | Open |
| LIM-024 | `test_git_lifecycle.py` 在含 git hook 的用例上挂起 | 37 个用例中第 17 个（`test_publish_additional_remote_rejection_preserves_primary_and_retry_succeeds`，安装 `pre-receive` shell hook 后期望 push 被拒）在本机停滞超过 8 分钟；前 16 个全部通过。`run_tests.py` 无单套件超时，一个挂起会阻塞整轮回归 | 需要单套件超时或对 hook 执行环境做隔离诊断；复现时用 `-v` 直接跑该文件定位 | Open |
| LIM-025 | Windows 门禁的 Go 最低版本内部不一致 | `development-environment-gates.ps1` 用 `$MinimumGoMinor = 24` 做比较，同一文件下一行 `$GoRequirement = ">=1.25.0"`，`$go-initialize-go-project` 也写 1.25.0；Go 1.24.x 会通过门禁却与报告口径和 `go.mod` 的 `go 1.25.0` 不符 | 已消除双口径：下界由 `.ps1`/`.sh` 的单一常量驱动，当前统一为 1.26.0（上调原因见 LIM-027），并同步两个适配器 Skill、提交示例与对应断言 | Closed |
| LIM-026 | sh 侧环境门禁测试此前从未真实执行 | `test_development_environment_gates.py` 缺少 `unittest.main()` 入口，`scripts/run_tests.py` 以 `python <文件名>` 调用时静默返回 0；该文件 34 个用例在 Windows 上按设计跳过 31 个，其余 3 个静态契约用例（Git Bash 标准用户根、`mktemp` 命名等）同样未执行，历史回归统计不包含本套件 | 已补入口；此后计入回归统计 | Closed |
| LIM-027 | GraphQL 条件资产把 gqlgen 版本与模板 Go 下界硬耦合 | gqlgen v0.17.95 声明 `go 1.26`，模板下界因此从 1.25.0 上调到 1.26.0。启用 GraphQL 的下游在 `GOTOOLCHAIN=local` 下会因 gqlgen 要求更高工具链而 `go mod tidy` 失败；关闭 GraphQL 的下游同样被这个全局下界抬高，没有按能力分档 | 模板只有一个全局 Go 下界，无法按条件资产分档。升级 gqlgen 前必须先查其 `go` 指令；需要更高下界时按同一流程上调 `$MinimumGoMinor`/`MIN_GO_MINOR`、`go-service` 资产 `go.mod` 与全部声明，并重跑初始化 E2E 两条路径 | Open |
| LIM-028 | 行数门禁在 Harness 源与下游各有一份独立实现 | `scripts/harness_validation/line_limits.py`（源校验用）与 `.agents/skills/go-implement-change/scripts/check_file_line_limits.py`（随资产下发）逻辑重复。2026-10-08 发现前者漏排 gqlgen 生成的 `internal/graphql/generated.go`，源校验因此失败；更早之前仓库尚未初始化 Git，检查器退回文件系统枚举并跳过 `.agents/`，该失败被长期隐藏 | 已改为路径后缀匹配并同步两份实现，同时覆盖下游项目根与模板内嵌资产两处位置。根治需要让源校验器直接复用下发给下游的那一份；出现下一次分叉时处理 | Mitigated |

## 状态词汇

| 状态 | 含义 |
|---|---|
| `Open` | 问题已知且未处理，可能在真实使用中暴露 |
| `Mitigated` | 已有明确缓解手段或边界说明，残余风险可接受 |
| `Closed` | 问题已消除，条目保留用于追溯 |

## 维护规则

- 新增条目时分配下一个未使用的 `LIM-NNN` 编号，不复用已关闭编号。
- 条目必须包含可判断的复核条件，禁止“以后再说”一类无法验证的表述。
- `TODO`/`FIXME`/`HACK` 在当前任务无法解决时必须在此登记对应条目。
- 问题消除后状态改为 `Closed`，或直接删除条目（历史由 Git 承担）。
