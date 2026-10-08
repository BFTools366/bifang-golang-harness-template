---
name: go-rename-project-identity
description: 在受维护的配置、源代码路径、文档、项目 Skills 和根目录两份许可证中重命名已初始化或刚实例化项目的中英文展示名称和产品前缀。用于下游实例化、已批准的产品改名，或需要在整个仓库中清除残留模板或示例身份时。
---

# 重命名项目身份

在规范化后的项目根目录中应用一套可审计的身份映射。只替换身份词元；绝不重写许可证权利、历史验证结果、第三方声明、生成产物或无关正文。生成产物中唯一允许替换的是 `docs/` 下 Swagger 文档与 `cmd/server/main.go` 的 `@title` 注解里的身份词元，理由与范围见工作流程第 5 步。

## 必需输入

- 规范化后的项目根目录；
- 旧中文/英文展示名称和新中文/英文展示名称；两种语言都必须是已确认的非空值；
- 旧 ASCII `snake_case` 项目标识和新 ASCII `snake_case` 项目标识；
- 旧小写 kebab-case 前缀和新小写 kebab-case 前缀；
- 真实配置所需的其他精确前缀映射，例如 Go module 路径、示例导入路径或环境变量前缀。

## 工作流程

1. 读取 `AGENTS.md`、当前产品身份事实来源、`docs/ENGINEERING_RULES.md`、`docs/GO_WEB_TEMPLATE.md`、当前产品状态、存在时的当前工作计划、存在时日期最新的 ADR、根目录两份许可证，以及精确搜索旧名称后报告的文件。
2. 确认模式、批准和版本分类。`$go-instantiate-project` 期间是中性“实例化身份重置”，用户提供的目标身份即构成替换所复制 Harness 身份的批准；该模式不进入 `$go-manage-version`，不得运行 `plan`/`apply` 或改变初始版本。除此之外均是“现有产品改名”：它会改变公开身份、路径、配置或许可证，必须先通过 `$go-define-product` 确认范围；确认后直接实施，不自动创建 Work Plan、候选或完整验收步骤。现有产品改名固定使用 `$go-manage-version` 的 `feature` 分类和本次改名唯一、可重试复用的稳定 `change_id`；复用产品范围确认已经记录的同一 ID，并在任何改名写入前执行 `plan --kind feature --change-id <stable-id>` 取得 `required_version`。不得由执行者按改动大小、发布周期或个人判断改判为 `maintenance`、`bug-fix` 或豁免版本门禁。
3. 解析并验证规范化后的项目根目录，并检查 Git 顶层目录、分支、提交状态、远端和 `git status --short`。必须保留现有修改；当重叠编辑无法协调时停止执行。
4. 首先运行自带脚本，但不得添加 `--apply`。提供全部三种标准身份形式以及每个已知的额外精确映射。复核 JSON 计划，尤其是路径冲突、跳过的二进制文件、排除路径、许可证编辑、Skill 编辑和路径改名。

   ```text
   python3 .agents/skills/go-rename-project-identity/scripts/rename_project_identity.py \
     --root <project-root> \
     --old-display-name-zh <old-zh-name> --new-display-name-zh <new-zh-name> \
     --old-display-name-en <old-en-name> --new-display-name-en <new-en-name> \
     --old-id <old_snake_case> --new-id <new_snake_case> \
     --old-kebab <old-kebab> --new-kebab <new-kebab>
   ```

   Go 身份映射固定包含以下精确词元，逐项复核后再应用：

   - Go module 路径：`<old-id>` → `<new-id>`（同时覆盖 `go.mod` 的 `module` 行与全部 `internal/...` 导入前缀）；
   - 二进制名：`<old-id>` 或 `<old-kebab>` → 对应新值（覆盖 `Makefile`、`make.bat`、`Dockerfile`、构建产物命名）；
   - 示例身份：`example-service`、`example-tool` 等模板占位标识 → 目标身份；
   - 中英文展示名称：`LICENSE.zh-CN.md` 的 `适用项目名称` 精确使用中文名称，`LICENSE.en.md` 的 `Applicable Project Name` 精确使用英文名称；
   - 按 locale 拆分的双语资源：`internal/pkg/i18n/locales/zh-CN.yaml` 只使用中文名称，`en-US.yaml` 只使用英文名称。

5. 必须拒绝路径冲突、路径越界、符号链接、包含身份但无法解码的受维护文本、含义不明确的部分前缀，以及会修改第三方内容或生成内容的映射。唯一例外是 `docs/` 下由 `swag init` 生成、并以字面文本承载项目展示名称的文档文件（`docs/docs.go`、`docs/swagger.json`、`docs/swagger.yaml`）与 `cmd/server/main.go` 的 `@title` 注解：这些位置的身份词元必须随改名一并更新，否则 Swagger 文档标题会停留在旧身份，第 7 步的残留扫描也无法通过。排除目录包括 `.git`、构建、缓存和输出目录、依赖存储和根目录 `release/`；不得为了强行得到干净结果而削弱这些排除规则。
6. 使用 `--apply` 重新运行已复核的命令。脚本必须先替换文本，再按路径深度从深到浅重命名文件和目录。对于已批准的现有项目标识变更，仅当规范化后的根目录基本名称等于旧标识时才能添加 `--rename-root`；如果同级目标已经存在，脚本必须拒绝执行。新实例化目标已经使用新的基本名称，绝不得使用该选项。脚本以中文映射精确更新 `LICENSE.zh-CN.md`、以英文映射精确更新 `LICENSE.en.md`，并同步受维护的双语资源；任何法律措辞变更都需要单独批准和双语法律复核。
7. 在整个受维护目录树中搜索每一个旧词元和常见示例身份。Go 项目必须额外确认 `go.mod` 的 `module` 行、`.harness/go-service-profile.json`、`Makefile`/`make.bat`、`Dockerfile` 中的构建名、`README.md` 身份摘要和 `.gitignore` 均无旧身份。解决每一个适用残留。有意保留的通用示例不得继续使用真实的旧项目身份；必须把它们改写为明确的占位符，而不得通过允许列表静默保留残留。
8. 运行本次身份变化必需的解析、残留搜索和非空单元/回归测试。Go 项目在 module 路径或目录名变化后必须运行 `go build ./...`、`go vet ./...` 与 `go test ./...`，并让 Go 工具链重新解析 `go.sum`；不得手工编辑 `go.sum`。对于 Harness 变更，运行 `python3 scripts/validate_harness.py`。不自动追加格式、lint、独立构建或完整验收。现有产品改名只有在这些检查通过后，才使用第 2 步完全相同的 `feature` 分类和稳定 `change_id` 执行 `apply`；失败、未完成或测试未通过时不得提前提升版本。实例化身份重置始终不执行版本门禁。
9. 实例化身份重置完成后返回 `$go-instantiate-project`/`$go-initialize-go-project` 继续中性收尾。现有产品改名完成必要测试与残留扫描后直接收口；普通编译/构建保持开发流程。只有用户明确请求正式发布候选时才先进入 `$go-prepare-release`，由发布上下文封存当前范围后调用对应构建 Skill；构建只另外确认 E2E 并全量运行单元测试。只有用户要求完整验收或发布时才调用 `$go-verify-delivery`。
10. 同步当前产品身份和受影响的 module 路径、`README.md` 身份摘要、构建与容器命名、`.harness/go-service-profile.json` 及保留 Skills。现有产品改名属于长期决定并更新 Product Spec/ADR，用户可感知改名写入 Changelog；这些记录复用第 2 步的稳定 `change_id` 和 `required_version`。Product Status、Work Plan 和 Verification 仍只在各自独立事件触发时更新。不得篡改历史证据中的旧名称。
11. 检查最终差异，并报告变更内容、已重命名路径、排除项、剩余旧名称命中、已执行检查、未验证平台和回滚说明。未经单独授权，不得提交、创建标签、推送、发布或修改外部系统。

## 不变量

- `LICENSE.zh-CN.md` 必须使用当前中文项目名称，`LICENSE.en.md` 必须使用当前英文项目名称；两者同时保留等价法律条款和中文文本优先规则。
- Go module 路径、项目自有配置、二进制名、Skills、当前文档、发布前缀和受维护源代码路径中不得残留过期的产品前缀。
- 不得批量编辑 `.git`、依赖、生成输出、缓存、供应商化第三方内容和 `release/`；生成输出中只有 `docs/` 下 Swagger 文档与 `@title` 注解的身份词元属于允许范围。
- 不得覆盖任何目标路径，也不得跟随任何符号链接。
- 任一语言的展示名称变更不得静默改变另一语言名称、ASCII 项目标识、Go module 路径、法律实体、产品范围或发布授权；版本只能按本 Skill 的模式分流和固定门禁改变，不能作为文本身份映射的一部分被替换。
- 现有产品改名必须完成产品范围确认、必要 ADR/Changelog、精确残留扫描和本次所需测试；不得把未显式执行的构建或验收写成已完成。

## 完成要求

报告实例化重置/现有产品改名模式、中英文精确映射、Go module 路径与二进制名映射、试运行和应用摘要、许可证与 Skill 覆盖范围、已重命名路径、残留搜索结果、`go build`/`go vet`/`go test` 实际结果、保留的现有用户修改，以及仍为 `Unverified` 的身份形式。现有产品改名另报告 `feature` 分类、稳定 `change_id`、`required_version`、`plan`/`apply` 结果和是否实际提升；实例化身份重置明确报告版本门禁 `Not applicable`。未显式请求时，完整验收报告 `Not run`。
