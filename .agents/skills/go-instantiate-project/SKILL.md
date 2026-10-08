---
name: go-instantiate-project
description: 只收集 Harness 创建终端下游所需的固定初始化信息，拒绝产品业务需求；表单确认后先门禁 Git，完成中性 Go 脚手架后再建立独立仓库与 local 身份。
---

# 实例化项目

创建一个继承 Harness 长期规则、但不继承 Harness 项目身份、按日期保存的项目记忆、批准结论、验证声明或 Git 历史的下游仓库。

## 工作流程

1. 读取源项目的 `AGENTS.md`、`README.md`、`Version.md`、`docs/AGENT_POLICY.md`、`docs/ENGINEERING_RULES.md`、`docs/RELEASE.md`、`docs/GO_WEB_TEMPLATE.md`、两份许可证，以及 `$go-rename-project-identity`/`$go-initialize-go-project`/`$go-manage-git-lifecycle` 的当前规则。收到任何创建新下游项目的请求时，还必须先完整读取并执行 [`references/initialization-form.md`](references/initialization-form.md)。实例化排除日期项目记忆，因此不默认加载 Harness 的历史 Product Status、Work Plan、Verification、ADR 或 Changelog 正文。
2. 在任何写入或环境安装前完成初始化表单。首轮一次询问全部尚未解析的基础字段：中文项目展示名称、英文项目展示名称、跨平台安全的 ASCII `snake_case` 项目标识、项目路径、负责人、是否启用用户 API（默认启用）、是否启用 GraphQL 查询层（默认关闭，仅在用户 API 启用时可选）；必须使用清晰编号，不能拆成逐字段多轮，也不能用一次模糊问询代替。**接口组合、交付平台与 Agent 策略模式在本阶段已关闭**，不得作为可选项展示或询问：接口固定为 HTTP API、交付平台固定为 Linux，策略固定为「推荐预设」展开的 `user_owned_tasks: disabled`、`superpowers: disabled`、`parallel_worktree_subagents: disabled`、`acceptance_smoke: enabled`、`e2e_hint: disabled`，来源记为「模板固定值」；用户主动要求修改时说明当前模板阶段不开放，不解析为表单字段。完整汇总必须列出中英文名称、各自来源。中英文名称至少一个由用户直接提供；只提供其中一个时，Agent 自动翻译并补齐另一个，不增加独立问询，把译名及其来源放入最终汇总等待确认；两个都由用户提供时不得自行改译。用户已明确提供的合法字段直接复用；首轮回复中缺失或非法的基础字段集中列出约束后补齐，不重问合法字段。基础字段全部解析后，两个开放的条件字段 `user_api` 与 `graphql` 已在首轮一并询问，直接进入完整汇总；`graphql=enabled` 要求 `user_api=enabled`（`me` 查询依赖账号与组织实体），组合非法时集中列出约束后补齐；所有字段收齐后展示完整汇总并在用户确认前禁止写入。Harness 源字段值不是下游确认，不得静默采用预设或遗留 `pending`。记录真实确认来源和最终收齐日期。产品目的、核心输入/输出、业务规则、成功标准、风险、副作用、产品专属接口路径/文案/数据、远程地址、凭据和发布需求不属于 Harness 源初始化输入；即使用户同时提供，也不得接收、分析、记录到源仓库、复制到脚手架或提前实现，只能明确说明这些需求要在初始化完成并切换到唯一终端下游根目录后，通过 `$go-define-product` 重新提出。
3. 当 Python 3 可用时，在源项目根目录运行 Harness 验证命令；否则记录为 `Not run`（可选 Python 不可用）。本阶段只验证 Harness 源，不执行 Git 可用性、版本、身份、提交模板或仓库配置检查，也不安装、升级或初始化 Git。完整表单汇总确认后，由 `$go-initialize-go-project` 在任何脚手架写入前调用环境门禁检查 Git，缺失时按受管路线安装并复探；仓库初始化、作者身份与模板仍统一推迟到全部脚手架和一次性裁剪完成、下一步将实际创建基线提交时即时执行。
4. 收齐项目标识和项目路径后，运行只读 `scripts/resolve_project_target.py`。相对输入以当前 Harness 根目录为基准；规范化输入路径的最后一个名称与 `<project-id>` 区分大小写地精确相等时，最终项目根目录就是输入路径，否则固定为 `<项目路径>/<project-id>`。不得用大小写、连字符/下划线转换、前后缀或相似度把不同名称视为相同。helper 输出的 `targetRoot` 必须显示在完整表单汇总中，并在用户确认后成为唯一项目根目录。拒绝以 Harness 根目录自身、Harness 根目录的任何祖先目录，以及通过符号链接解析到任何禁止位置的路径作为最终项目根目录。除这些限制外，目标可以位于 Harness 根目录内部或外部。
5. 写入前清点解析后的最终项目根目录。只有最终项目根目录必须不存在或为空，包括不存在任何隐藏条目；当用户输入的是父目录时，该父目录可以存在且非空。必须保留用户文件，并在最终目标为符号链接、非目录、非空或发生任何冲突时停止。绝不为了让现有仓库看起来像模板而删除、合并写入或覆盖它。
6. 在创建或填充目标目录之前，对受维护的源文件列表生成快照；随后只复制该固定文件列表，不得再次递归遍历源目录，以免将 Harness 复制到其内部目标时发生递归。排除目标目录自身、其他下游项目、源 `.git`、构建输出、缓存、临时文件、`dist/`、本地工具状态、生成的证据，以及仅属于 Harness 的根目录 `Version.md`；初始化后的 Go 下游服务从根 `go.mod` 与 `README.md` 获取版本与身份事实。还必须完整排除 `docs/adr/`、`docs/changelog/`、`docs/product_spec/`、`docs/work_plan/`、`docs/VERIFICATION.md`、`docs/verification/` 和 `.agents/skills/go-curate-harness-memory/`：实例化期间不得复制其索引、日期文件、历史验证正文或该 Skill 本身，也不得创建空白替代目录或文件。`go-curate-harness-memory` 只治理 Harness 自身的历史条目，下游没有可迁移的历史，不得保留或独立重建。保留 `.gitignore`、长期规范性文档、项目 Skills、这些 Skills 有意保留的资产（包括 `.agents/skills/go-initialize-go-project/assets/go-service/` 资产目录），以及根目录的两份许可证文件 `LICENSE.zh-CN.md` 和 `LICENSE.en.md`。`$go-manage-git-lifecycle` 是所有终端下游都必须保留的身份中立工程能力；其完整 Skill 目录、helper 和回归测试必须进入固定快照并经过后续裁剪，不得按接口或平台删除。Git common-dir 生命周期清单不是 tracked 资产，`.harness/release-context.json` 也只能在未来一次真实发布准备中产生，二者都不得进入中性初始化快照。设计标准属于身份中立的工程规则；产品实现偏离记录在下游 ADR，不直接修改受管目录。初次传输时必须逐字节复制两份许可证文件；身份重置期间不得替换、削弱、概述或删除其中的法律条款。
7. 先以预览模式调用 `$go-rename-project-identity`，随后在整个受维护的目标树中应用复核后的映射。向脚本同时传入已确认的中英文展示名称，把 Harness 的两种展示名称、snake_case 标识、kebab-case 前缀、Go module 路径前缀、示例 Go 包导入路径、项目自有配置和保留 Skills 替换为目标身份；`LICENSE.zh-CN.md` 的 `适用项目名称` 精确使用中文名称，`LICENSE.en.md` 的 `Applicable Project Name` 精确使用英文名称；同理，按 locale 拆分的双语资源文件（如 `internal/i18n/locales/zh-CN.yaml` 及其 `en-US` 对应文件）中，凡以字面文本写入项目展示名称的位置，`zh-CN` 文件使用中文名称、`en-US` 文件使用英文名称；运行时以单一应用名变量注入并跟随请求语言切换的位置不在本条替换范围内。许可证编辑仅限精确的项目名称词元；所有其他法律文本必须与复制后的源文件保持字节等价。继续之前必须解决每一个适用的身份残留，并保留 `$go-rename-project-identity` 供未来已批准的产品改名使用。
8. 五项策略与确认元数据全部收齐后才一次原子写入 `docs/AGENT_POLICY.md`；必须使用 `schema_version: 3`、`decision_mode: reuse_then_infer_then_ask`、真实的 `confirmed_by`/`confirmed_at`，且不得新增预设字段或存在 `pending`。把产品状态、接口选择、发布记录、技术债和 Harness 溯源重置为真实的下游起始状态，并确认验证历史和人工复核字段没有迁移。不得仅为实例化创建产品规格、工作计划、ADR、变更记录或 `docs/VERIFICATION.md`。
9. 在继承的规范性文档中保留基线约束，但不得把 Harness 的决策日期或批准结论表述为下游负责人作出的决定。把下游 `AGENTS.md` 重写为不超过 20,000 UTF-8 字节和 120 行的轻量路由器，并完整保留 `user_owned_tasks` 默认关闭及手动开关、结果边界、每项目单一写入型 active Task、Task0 仅协调、创建前零写入门禁，以及用户可见 Task 的 `Task {序号} | {当前进度} | {单一结果}`、四种进度和有界复读规则。序号按同一 `hostId`/`projectId` 的 `list_threads` 当前结果与 `list_archived_threads` 逐页归档 Task 最大有效序号加 1，空历史从 1、缺号不回填，不识别任何历史标题格式。创建必须精确绑定保存项目/`projectId`，Git 使用独立 Worktree、非 Git 使用 Local；只有真实 `threadId` 才继续，并核对标题、项目、cwd、状态、干净工作区与起始提交。`clientThreadId` 只表示 setup，禁止代做或重复创建。内部 plan、Subagent、Worktree、brief、report、review 不使用标题合同也不占用序号；内部 Subagent 不使用标题合同。`parallel_worktree_subagents` 仍只控制 `codex/unit-*` 内部并行。必须保留左侧 Task 描述模板、`$go-manage-git-lifecycle`、Git common-dir 生命周期清单和 `.harness/release-context.json` 的事实来源入口。
   用户可见 Task 标题是非阻断 UI 闭环，不能取代描述模板、真实身份或初始派发门禁。
10. 一致设置版本事实。仅当继承的基线适用且用户没有批准其他初始版本时使用 `0.1.0`。反馈渠道、发布渠道和产物格式尚未决定时，必须明确保持为未知。
11. 在目标目录中搜索残留的 Harness 中英文身份、历史批准日期、已完成验证声明、源机器绝对路径，以及 `example-tool` 等示例标识。解决每一个适用命中，或者记录其有意保留的原因。中文许可证中的项目名称必须等于已确认的中文名称，英文许可证中的项目名称必须等于已确认的英文名称；README 的身份摘要也必须同时列出这两个名称。`Software`、`Licensor`、`Licensee` 和 `Downstream Project` 的通用定义以及所有非身份法律条款都属于有意保留内容，除非具备资格的法律顾问批准替换商业许可证，否则必须保持不变。
12. 不得在经过选择性复制的目标目录中运行模板级 Harness 验证器。验证目标目录清单、排除项、改写后的身份、保留链接和策略模式定义，随后把固定的 Linux 交付平台与固定 HTTP API 接口交给 `$go-initialize-go-project`；验证并复用全部五项已记录策略，不得再次询问交付平台、预设、策略或接口。初始化器必须把 `delivery-platform: linux`、`interfaces: ["http-api"]` 与初始化表单确认的 `user-api`、`graphql` 取值持久写入根 `go.mod` 同级的中性工程事实文件 `.harness/go-service-profile.json`，供后续构建只读使用，不得遗留空值或根据新会话重新猜测。Go 服务不设 GUI 能力问询，不得为任何下游引入托盘、通知、自启、深链接或快捷键相关字段。
13. 必须要求 `$go-initialize-go-project` 在完整表单确认后、脚手架写入前保存 `$go-check-development-environment` 返回的 `gate.git.status/version/change`；并确保 Git 门禁与 Go 工具链门禁（`go version`、`GOROOT`、`GOPATH`/`GOMODCACHE`）在脚手架写入前完成。初始化 E2E 由 `$go-test-initialization-e2e` 在脚手架检查完成后执行：验证 `go build ./...`、`go vet ./...`、`go test ./...`、配置加载与 `GET /healthz` 契约、统一响应体形状、中间件顺序、i18n 词条覆盖、`.harness/go-service-profile.json` 事实一致性（含 `user-api` 与 `graphql` 条件取值及其组合合法性）、条件资产在场/缺席与 `internal/api/v1/module.go` 注册状态一致、中英文身份无残留，以及 Linux 开发态与构建后启动命令已写入汇总。全部检查和一次性裁剪完成、下一步确实将创建唯一基线提交时，才复探 Git、建立并验证独立仓库边界，使用 `$go-configure-git-commits` 先报告身份；已有有效身份原样保留，缺失字段由 Agent 提供的单一 ASCII 英文设备 username 派生同名 `user.name` 与 Gmail 并只写 repo-local，随后检查身份、安装和检查仓库本地提交模板。已有无效身份、无法安全翻译/归一化设备名、identity/template 检查失败都阻断；无 `pending`、Git 干净且无远端时创建恰好一个本地基线提交。不得提前初始化仓库或设置身份/模板，不得修改全局 Git 配置，也不得修改 system Git 配置。

初始化收尾还必须由 `$go-manage-version init --project-root .` 创建并核对受保护的 `.harness/version-state.json`，并在裁剪中完整保留该版本 Skill、标准库 helper 和测试；不得把 Harness 时间版本写入下游状态。

初始化只复制并完整保留 `$go-manage-git-lifecycle` 的 `SKILL.md`、`agents/openai.yaml`、`scripts/git_lifecycle.py`、`scripts/git_publication_report.py`、`scripts/git_lifecycle_test_support.py`、`scripts/git_publication_test_cases.py` 和 `scripts/test_git_lifecycle.py`，不运行 `start`、`publish` 或 `release`。Git common-dir 生命周期清单只能在初始化完成后的首次真实开发中由该 Skill 创建；`.harness/release-context.json` 只能在未来一次真实发布准备中创建，中性初始化不得预创建二者。

## 重置不变量

- 绝不得把 Harness 中的 `Approved` 产品状态、人工复核人身份、验证结论、源码提交、校验和、发布日期或平台结果带入新的下游项目。
- 绝不得迁移或预创建 `docs/adr/`、`docs/changelog/`、`docs/product_spec/`、`docs/work_plan/`、`docs/VERIFICATION.md` 或 `docs/verification/`；这些内容只在各自事件触发条件满足时由负责的开发 Skill 创建。
- 绝不得声称示例资产产生的 Windows、macOS 或 Linux 证据属于下游产品。
- 绝不得复制源 `.git` 目录或伪造历史。必须始终在解析后的目标根目录创建新的独立仓库。
- 绝不得代替用户选择项目路径输入。只能按已确认表单中的确定性规则解析最终项目根目录：末级名称与项目标识精确相等时直接使用，否则追加项目标识；解析结果必须在首次写入前展示并确认。
- 绝不得把 Harness 根目录或其任何祖先目录作为最终目标，不得覆盖非空最终目录，也不得跟随符号链接进入禁止位置。父目录输入可以非空；安全门禁始终应用于解析后的最终项目根目录。
- 完成移交后，必须把解析后的目标目录同时视为唯一项目根目录和 Git 顶层目录。不得继承父级 Git 边界，也不得在其他位置创建第二份项目树。
- 初始化请求仅授权在脚手架验证和裁剪成功后创建恰好一个本地基线提交。该请求不授权创建远端、推送、标签、发布、签名密钥、全局 Git 配置变更或托管仓库。
- 初始化不运行 `$go-manage-git-lifecycle start|publish|release`，不创建或推送开发分支和 tag，不创建 common-dir 生命周期清单，也不预创建 `.harness/release-context.json`；无 remote 的独立 `main` 基线仍是唯一初始结果。
- Git 可用性与版本只允许在完整表单确认后、脚手架写入前的初始化环境门禁检查；缺失时受管安装并复探。独立边界、作者身份和提交模板仍只允许紧邻真实基线提交检查或设置；复制、身份改写、脚手架编写和测试均不得以未来会提交为由提前初始化仓库或写 Git 配置。
- 必须保留共享核心、已选接口、中文业务注释、文档、测试、验证、例外和人工复核规则，除非下游负责人批准并记录例外。
- 必须执行 `docs/AGENT_POLICY.md` 中全部五项策略值。后续工作必须复用这些值，并且仅在策略缺失/非法、用户明确要求手动切换、需求冲突或无法判断适用性时询问。
- 生成的仓库是终端项目：不得保留 `$go-instantiate-project`、`$go-initialize-go-project` 或任何其他活动的项目派生入口。
- 接口固定为 HTTP API 时，唯一基线提交必须晚于一次成功的 Go 初始化 E2E，并至少覆盖该接口：真实进程监听、中间件顺序、统一响应体与 `GET /healthz` 通过。Go 服务没有 GUI 能力、资源文件或打包系统注册需要补充验证。该本机检查不迁移为发布或完整验收结论，发布候选仍由 `$go-test-final-artifact-e2e` 补验。
- 生成的仓库必须包含 `LICENSE.zh-CN.md` 和 `LICENSE.en.md`；与源 Harness 相比，只有其中精确的双语 `Applicable Project Name` 可以不同，所有其他法律条款都必须保持不变。初始化裁剪不得删除或进一步修改任一文件。
- 裁剪后，`AGENTS.md` 必须继续保留轻量渐进读取结构、非空的 Skills/约束地图、`$go-upgrade-harness`、`$go-manage-version`、`$go-manage-git-lifecycle`、`.harness/version-state.json`、common-dir 生命周期清单和发布上下文的事实来源入口以及持久策略决策入口；不得把已由事实源或 Skill 承载的实现细节复制进去。

## 完成要求

报告初始化表单的最终字段、用户输入的项目路径、解析后的唯一目标根目录、源根目录、复制和排除的文件、身份与历史重置、写入前 `gate.git.status/version/change`、Go 工具链版本与 `GOROOT`/`GOPATH` 探测结果、最终 Git 版本与独立边界、有效作者身份及每个字段的 scope/origin/source/derivation、是否只写 repo-local、提交模板本地配置与检查结果、模板固定策略取值（接口 HTTP API 与五项策略，来源均为「模板固定值」）、Swagger 自动展示结果（后台服务进程状态、`healthz` 返回码、`/swagger/index.html` 是否已在默认浏览器打开）、可选的 Harness 溯源锁或未来必须执行的初始基线审计、基线提交、干净状态、是否拒绝过超范围产品输入（不得复述或保存其具体内容）、源 Harness 验证结果以及下一个 Skill。中性 Go 脚手架可以先于产品批准建立，但不是已验收产品。
