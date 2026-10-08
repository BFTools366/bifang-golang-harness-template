---
name: go-verify-delivery
description: 对发布候选、用户明确要求完整验收或当前构建启用 E2E 的最终真实产物进行验收；日常开发不得自动调用。
---

# 验证交付

验证完整真实候选，不把开发检查、模拟实现或目录存在误报为可用。

## 准入

1. 只接受发布/渠道要求、用户明确要求完整验收，或当前构建已明确选择 E2E `enabled` 的请求。读取 Product Spec、当前构建记录、`docs/AGENT_POLICY.md`、`docs/ENGINEERING_RULES.md`、相关 ADR、验证/发布规则和适用接口 Skill。
2. 要求存在与批准场景、40 字符源码提交、版本/构建标识和当前环境绑定的完整真实产物、校验和及 manifest。先运行发布上下文 `verify`，要求工作树 clean、当前具名分支是上下文默认主分支、本地主分支与 `expectedTag` 都指向当前 HEAD，且 tracked `.harness/release-context.json` 字节和 schema 有效；`gitPublication: remote` 才额外要求远端主分支/tag 一致，`local` 不得访问远端且候选只能来自当前宿主。manifest `sourceCommit` 必须等于该 HEAD，`releaseContextSha256` 与审查字段必须逐字段来自上下文；把 Git 发布位置及这些值锁定为准入快照。缺少上下文、HEAD/ref/tag 漂移或 manifest 自行改写选择都拒绝。随后运行版本检查，并要求候选/manifest/上下文版本相同；验收不得提升版本。该验证不检查分支祖先、合并类型或线性历史。
3. 当前存在用户要求的活动 Work Plan 时，相关 Todo 必须全部 `done`；没有 Work Plan 不阻断验收。

## 工作流程

1. 明确核心成功路径、最高风险失败路径、真实输入/输出和可观察结果，区分外部前置项与产品逻辑。
2. 核对当前构建已经运行项目全部非空单元测试。Go 证据必须覆盖 `go test ./... -race` 的全部包，且测试数量非零、无数据竞争；只有源码提交、`go.sum` 和候选构建身份完全匹配时才复用该证据；任何变化都必须返回构建 Skill 重建，不在验收中重复一套隐式构建流程。
3. 运行候选自身所必需的真实产物存在性、接口/渠道和最终字节检查。所有 Go 候选先核对 manifest 的 `GOOS`/`GOARCH`、制品文件名、`.sha256` 摘要与 `release/` 精确集合，并对可定位的候选二进制运行 `scripts/verify_go_artifacts.py <release-dir>` 复算每个制品的平台、摘要与可执行入口；不得沿用旧候选的布局证据或旧更新日志证据。只有真实执行 `--help` 与 `--version` 得到预期只读退出、且 `--version` 的人类可见输出恰好带一个小写 `v` 前缀时，才算制品级通过；任何重新编译都会产生新候选并使旧证据失效。
4. 解析运行时检查：产品/渠道/安全硬要求优先；冒烟读取 `acceptance_smoke`；E2E 只读取当前构建的明确选择，`e2e_hint` 仅用于当时询问的建议默认值，不能在此替代或反转选择。发布语义审查只读取 manifest 的当次 `reviewSelection`；不得在验收阶段补问、推断或把 `disabled` 静默翻转，任何硬要求与关闭选择冲突时拒绝候选并返回新构建。
5. 按每个 manifest 的 `reviewSelection` 核对发布语义审查，且机械安全门禁与最终人类签署不受该选择控制。
   - `enabled`：只接受 `reviewStatus: passed`、结构化 `reviewEvidence` 和 `reviewedSourceCommit`，且它们逐字段等于发布上下文。`sourceHead` 描述审查终点，manifest `sourceCommit` 描述合并后被主分支和 tag 指向的候选；不对两者施加祖先、线性或允许路径门禁。
   - `disabled`：只有不存在安全、隐私、不可逆操作、对外兼容契约或产品/渠道审查硬要求时才接受 `reviewStatus: Not run`、非空 `reviewReason`/`reviewRemainingRisk`，并要求 `reviewEvidence` 与 `reviewedSourceCommit` 缺席。
6. E2E 为 `enabled` 或硬要求时调用 `$go-test-final-artifact-e2e`；该流程必须对当前最终候选字节真实执行声明的场景，包含真实 HTTP 请求下的统一响应体 5 形状、稳定错误码、`Content-Language` 协商、`/healthz` 与 `/swagger/index.html` 可达性；不能用注入数组、源码夹具或仅调用内部函数代替。E2E 为 `disabled` 时记录 `Not run` 和剩余风险。需要凭据、生产数据、支付、发布或不可逆副作用时仍须独立授权。
7. 全部真实检查、E2E 和必需人工结论完成后，先确定整组唯一结论，但在写入验收状态前再次运行发布上下文 `verify`；要求当前 HEAD、`releaseContextSha256`、`gitPublication`、`releaseReview`、`candidateSelections` 与准入快照逐字段相等，且全部 manifest 的 `sourceCommit` 都等于 HEAD。然后重新计算全部最终制品、相邻摘要、manifest 声明、包内关键资源和 `release/` 精确集合。任一漂移都拒绝状态写入并返回重建/重验。

8. 只在以上尾检查通过后，于项目根同级、同一文件系统的唯一 staging 复制当前 `release/` 精确集合；在 staging 内原子写入全部 manifests 的同一整组 `milestoneAcceptance` 结论及结构化证据，再复算所有摘要、资源绑定和精确文件集。整组必须同为 `accepted`、`rejected` 或 `pending`，不得混合。复验成功后才目录级原子替换 `release/`；失败保留原集合。验收证据只写忽略的 `release/`，不得在 tracked 源码中补写项目记忆或占位记录。

   同一记录还必须包含 `reviewSelection`/`reviewStatus`、适用 `reviewEvidence` 或 `Not run` 原因/风险，以及制品级平台/摘要/入口复算结果的绑定。验收不得自行签名、打包或重新注入 `-ldflags`；一旦发生此类步骤，产物字节已改变，结果是新候选，必须重新走构建与验收。

## 拒绝与修复

1. 产物缺失、不完整、不可运行、偏离批准场景，或任一必需/已启用检查失败、超时、取消或未执行时拒绝候选，并把证据按第 8 步随整组 `rejected` manifest 原子写入 `release/`；不得直接写 tracked `docs/verification/`。
2. 已批准范围内的实现偏差返回 `$go-implement-change` 修复并增加回归；该流程自动创建新开发分支，随后重新执行发布生命周期，形成新的 clean、被本地版本 tag 指向且已完成模式适用 refs 的默认分支 HEAD，再生成完整候选。不得只重写 manifest。
3. 新产品边界转交 `$go-define-product`；破坏性操作或新的外部副作用必须请求批准。不得以 `Partially verified` 掩盖必需逻辑缺失。

## 结论

验收结论只能是以下三种之一：

- `Milestone accepted`：每个必需场景和已选门禁均通过；发布审查满足其 `passed`/`Not run` 契约；任何真正必需的人类签署已记录。
- `Awaiting human review`：自动证据通过，但必需人工结论尚未签署。
- `Milestone rejected`：一项必需条件失败，已记录修复回流路径。

`Awaiting human review` 保持整组 manifest `pending`；拒绝整组 `rejected`；只有接受才整组 `accepted`，并附 E2E、审查、冒烟和制品级摘要/平台/入口证据。三种结论都必须走第 7/8 步的二次发布上下文/最终字节复算与 staging 原子替换。验收不授权创建或移动 tag、push、渠道发布、重新签名、重新打包、上传或额外清理。
