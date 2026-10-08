# 用户 API 条件资产

账号与认证能力的**条件资产**：只有当初始化表单的 `user_api` 选择 `enabled` 时，
才把这棵目录覆盖到 `go-service` 基线之上。

## 目录性质

这是 `conditional` 所有权资产，不是中性脚手架的一部分。`go-service/` 基线在关闭
用户 API 时**不包含**本目录的任何文件，也不包含任何指向它们的引用，因此关闭路径
天然零残留，不需要"复制后再删除"。

## 覆盖清单

把本目录按原路径覆盖到目标项目根（与 `go-service/` 的目录结构对齐）：

```text
internal/dto/{account.go,auth.go,verification.go}
internal/pkg/hash/{password.go,password_test.go}
internal/pkg/token/{token.go,token_test.go}
internal/pkg/verifycode/{verifycode.go,verifycode_test.go}
internal/pkg/notify/{notify.go,notify_test.go}
internal/model/{account.go,org.go,verification_code.go}
internal/repository/{account.go,org.go,verification_code.go}
internal/service/{account.go,auth.go,org.go,verification.go,verification_scene.go}
internal/api/v1/account.go
internal/middleware/{auth.go,auth_test.go}
```

## 必须同步的注入点

覆盖后还要改五处，否则编译、运行或文档不完整：

1. `internal/model/models.go` 的 `AllModels()` 追加实体，使自动迁移建表：

   ```go
   func AllModels() []any {
       return []any{
           &Account{},
           &Org{},
           &VerificationCode{},
       }
   }
   ```

   漏登记 `VerificationCode` 的后果很隐蔽：表不会被创建，发码接口在第一次
   落库时才报错，而启动日志里没有任何提示。

2. `internal/api/v1/module.go` 的 `Modules()` 追加账号模块，使路由生效：

   ```go
   return []Module{
       newSystemModule(deps),
       newAccountModule(deps),
   }
   ```

3. `go.mod` 增加 JWT 依赖（执行 `go mod tidy` 自动解析）：

   ```text
   github.com/golang-jwt/jwt/v5
   ```

   `internal/config/config.go` 的 JWT 结构与校验、`configs/*.yaml` 的 `jwt` 段已在
   基线中无条件存在，无需改动。`jwt.secret` 在非 dev 环境必填且长度不得少于 16 字符，
   由 `APP_JWT_SECRET` 环境变量注入。

4. `configs/config.yaml` 的 `verification.enabled` 改为 `true`，启用验证码：

   ```yaml
   verification:
     enabled: true
   ```

   基线的 `internal/config/config.go` 已无条件声明 `Verification` 结构与全部默认值，
   `configs/config.yaml` 也已带 `verification` 段（`enabled: false`），因此**只改这一个
   布尔值**即可。其余参数（位数、有效期、重发间隔、尝试次数、每日上限、发送通道）
   沿用基线默认值：`code_length=6`、`ttl=5m`、`resend_interval=60s`、`max_attempts=5`、
   `daily_limit=10`、`provider` 留空。

   开发档 `configs/config-dev.yaml` 已带 `verification.mock: true`，因此 dev 环境发码
   不需要真实通道，验证码直接随响应返回。生产档必须显式把 `mock` 设为 `false`：
   `config.Validate` 在 `enabled=true` 且 `app.env=prod` 时会对 `mock=true` 直接报错
   拒绝启动。`provider` 只接受留空 / `smtp` / `http`，拼错会在启动期被拦下。

5. 重新生成 Swagger 文档包，让 `/api/v1/auth/*` 出现在接口文档里：

   ```bash
   go run github.com/swaggo/swag/cmd/swag@<go.mod 里的版本> init -g cmd/server/main.go -o docs --parseDependency --parseInternal
   ```

   版本后缀取 `go.mod` 里 `github.com/swaggo/swag` 的实际版本，**不能省**：不带后缀时
   `go run` 按当前模块解析 `cmd/swag`，而它自身依赖的命令行解析库与 YAML 库不在本模块里，
   会报 `missing go.sum entry`；补齐又会把代码生成器的 CLI 依赖写进产品 `go.mod`。
   带后缀时在独立模块上下文构建，`go.mod`/`go.sum` 保持不变。

   基线 `go-service/` 自带的 `docs/` 只覆盖 `/healthz` 与 `/api/v1/system/health-check`；
   本资产的 `internal/api/v1/account.go` 带来 8 条 `@Router` 注解，不重新生成的话
   `/swagger/index.html` 就看不到任何认证接口 —— 这是条件资产落地后最常见的遗漏。
   同时把 `cmd/server/main.go` 的 `@title` 改成「<中文项目展示名称> API」、
   `@description` 改成按实际能力集描述，再执行生成；**先改注解、再生成**，顺序不能反。
   初始化结构契约检查器会双向比对注解与文档，漏掉这一步会在基线提交前失败关闭。

## 暴露的接口

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| POST | `/api/v1/auth/verification-code` | 否 | 发送验证码；mock 模式直接回显 |
| POST | `/api/v1/auth/register` | 否 | 注册；同事务创建账号与默认组织 |
| POST | `/api/v1/auth/login` | 否 | 用户名或邮箱登录，返回双令牌 |
| POST | `/api/v1/auth/refresh` | 否 | 用刷新令牌换新令牌对 |
| POST | `/api/v1/auth/password/reset` | 否 | 用验证码重置密码（忘记密码） |
| POST | `/api/v1/auth/logout` | 是 | 递增令牌版本，吊销该账号全部令牌 |
| GET | `/api/v1/auth/profile` | 是 | 当前账号及其默认组织 |
| PUT | `/api/v1/auth/password` | 是 | 改密并吊销全部令牌 |

鉴权只认 `Authorization: Bearer <token>`，不接受自定义头名、裸令牌或 `?token=` 查询参数。

## 验证码机制

验证码是**注册**与**重置密码**共用的凭证，落在数据库表 `verification_codes`，
不依赖 Redis 等外部中间件。链路：

```text
POST /api/v1/auth/verification-code   →  生成 → 投递（或 mock 回显）→ 落库
POST /api/v1/auth/register            →  校验 → 事务内消费 → 建账号
POST /api/v1/auth/password/reset      →  校验 → 事务内消费 → 改密 + 吊销令牌
```

**场景注册表**（`internal/service/verification_scene.go`）：场景 = 验证码的用途，
与接收目标（邮箱 / 手机号）正交。当前两个场景：

| 场景 | 落库值 | 要求目标已注册 | 用途 |
|---|---|---|---|
| `register` | `register` | 否 | 注册新账号；`scene` 留空时的默认值 |
| `reset_password` | `reset_password` | 是 | 忘记密码时重置密码 |

场景差异集中在注册表里声明，**不要**散落到 `dto` 的 binding tag 或 `Send`/`Verify`
的分支里：合法场景只有注册表一个定义处，未知场景返回可读的
`verification.scene.unsupported`，而不是在参数绑定阶段被拒成 400。
新增场景 = 注册表加一行 + `model` 加一个常量 + 实现对应业务流程。

**校验与消费分离**：`Verify` 只校验并返回记录主键，`Consume` 由调用方在业务事务里
执行。这样查重失败、建账号失败、改密失败都不会把用户刚收到的码吃掉，用户能拿着
同一个码重试；并发抢同一个码时靠 `WHERE status = 待用` 的 `RowsAffected` 判定归属。

**安全边界**（写死在实现里，不要为了"方便调试"放宽）：

- 验证码用 `crypto/rand` 生成，**不存明文**，只存 `sha256(target:code)`
- 比对走 `subtle.ConstantTimeCompare`，避免耗时侧信道
- 有效期、一次性消费、失败次数上限、重发间隔、每日上限五道防线同时生效
- 重发时旧码同事务作废，不会同时存在多个可用码
- `mock` 模式在生产环境被启动校验直接拒绝

哈希**不是**主要防线：6 位数字只有 10^6 种取值，拿到哈希后离线爆破是瞬间的事，
它的作用只是让数据库导出、慢查询日志、备份文件拿不到可直接使用的明文。

**发送通道**：`internal/pkg/notify` 只定义 `Sender` 接口，当前所有 provider 都落到
`Unconfigured`。非 mock 模式下调用发送会返回 `ErrChannelUnavailable`，接口层翻译成
503 —— 这是有意为之的显式失败，比静默丢弃、让用户永远收不到码要好排查得多。
接入真实通道时实现 `Sender` 并在 `notify.New` 里注册，service 与 api 层不用改。

**已知取舍**：`reset_password` 场景在发送阶段会暴露「该邮箱/手机号是否已注册」
（返回 404 `verification.target.not.registered`）。不暴露的话，用户拿到的是一个
永远用不上的码、且没有任何反馈。要消除这个枚举面，需改成「无论是否存在都返回
成功」，代价是用户对未注册的目标完全得不到提示 —— 取舍由产品决定。

## 与基线共享核心的适配约定

本目录的代码已按基线约定改写，**不要**回退成源项目写法：

- **错误码用基线的命名**：`ErrTokenMalformed`、`ErrCredentialsInvalid`、
  `ErrAccountUsernameTaken`、`ErrAccountPasswordMismatch`、`ErrTokenWrongType`、
  `ErrTokenSignFailed`、`ErrPhoneTaken` 等，不使用源项目的 `ErrAuthToken*` /
  `ErrUsernameExists` 前缀。验证码一组沿用 `ErrVerification*`，对应的 i18n 词条
  在基线里已无条件声明。
- **账号 ID 走 `contextx.SetAccountID` / `AccountID`**：鉴权中间件只把 `int64` 主键
  写进 request context，不放账号实体。`profile` 处理器按主键调
  `AccountService.LoadForAuth` 重新加载，因此共享核心的 `contextx` 不需要认识
  `model.Account` 类型。
- **时间字段统一用 `model.Timestamp`（`int64` 命名类型，unix 秒）**：基线
  `model.Base` 的 `CreatedTime` / `UpdatedTime` 就是该类型，本资产的
  `Account.LastLoginAt`、`VerificationCode.ExpiredAt` / `UsedAt` 以及 `dto`
  响应结构全部与之对齐，**不要**退回 `time.Time`。命名类型在 JSON 里仍编码成
  数字，前端 `new Date(sec * 1000)` 即可；比较与加减用 `Before` / `After` /
  `Sub` / `Add`，不要来回转 `time.Time`。需要写当前时刻一律用 `model.Now()`。
- **用 map 更新时更要显式传 `Timestamp`**：GORM 不对 map 里的值做类型转换，
  `TouchLogin` 若把 `time.Time` 塞进 `last_login_at`，sqlite 会存成文本、
  MySQL 隐式转换，库里的值既不是秒也不是时间。
- **`apperr.APIError` 是指针类型**：`errors.As` 的断言目标必须写 `*apperr.APIError`。
- **`WithExtra` 是命名参数**：签名是 `WithExtra(key string, value any)`，附加的是结构化
  详情而非文案占位符；词条本身是静态文案，不含 `%s`。动态值（脱敏目标、剩余秒数、
  场景名）放 `Extra`，不放词条。
- **令牌管理器由本域按配置创建**：`newAccountModule` 内用 `deps.Config.JWT` 调
  `token.NewManager`，不从 `Dependencies` 取。验证码的发送通道同理，由本域按
  `deps.Config.Verification.Provider` 调 `notify.New`。这样基线的 `Dependencies`
  不必认识用户模块类型，关闭用户 API 时共享核心零改动。
- **`Entity` 接口不含 `SetID`**：基线 `model.Entity` 只要求 `TableName()` 与
  `GetID()`，因为 `Base.SetID` 是指针接收者，写进接口会让所有值类型实体无法满足约束。
- **`service` 不 import `gorm.io/gorm`**：事务边界走 `Repository.Transaction(ctx, fn)`，
  回调参数是 `*repository.Repository[T]`；跨仓储的嵌套操作通过 `s.orgs.WithDB(tx.DB())`
  复用同一事务。验证码的消费也走这条路径 —— `VerificationService.Consume` 接收事务
  仓储、内部用 `s.codes.WithDB(tx.DB())` 派生，因此 service 层不出现 `*gorm.DB` 类型。
  `service` 直接接触 `*gorm.DB` 会被 core-first 门禁判为 ORM 耦合违规 ——
  只有 `model` 与 `repository` 在 `ORM_EXEMPT_LAYERS` 内。
- **派生仓储要覆写 `WithDB`**：`AccountRepository` 与 `VerificationCodeRepository`
  都覆写了 `WithDB` 以保留本类型特有方法。泛型基类的 `WithDB` 只返回
  `*Repository[T]`，在事务里拿它就没法调用 `UpdatePassword` 这类账号域方法。
- **`Repository.Get` / `GetByID` 查不到时返回 `(nil, nil)`**：调用方按「先判空、
  再给出业务错误」组织逻辑（登录失败给 401、目标未注册给 404），不要把它当成错误。
- **改密与吊销令牌必须同一条 UPDATE**：走 `AccountRepository.UpdatePassword`，
  分开写会留下「密码已换、旧令牌仍然有效」的窗口。
- **测试函数必须有紧邻中文注释**：`Test*` 开头的声明会被中文注释门禁检查，
  注释需写在声明紧邻的上一行。

## 领域说明

实体命名是 `Account` 而非 `User`：划分是「账号 / 组织」而不是「用户 / 角色」。
注册时同事务创建一个 `is_default = true` 的默认组织，`orgs.owner_id` 指向该账号。
账号加入他人组织是后续扩展，届时新增 `org_user` 关联表，`orgs` 与 `accounts`
结构都不需要改动。权限字段有意不放在账号上——权限属于账号在组织里的成员关系。

`accounts.phone` 是**可选**的 `*string` 列而不是 `string`：手机号可以不填，用空字符串
会因为唯一索引让第二个不填手机号的账号注册失败（多个 `""` 互相冲突）；指针写入 NULL，
而 MySQL 与 SQLite 的唯一索引都允许多个 NULL 并存。它也不是"资料字段"而是身份标识 ——
验证码可以直接发到手机上，以后做手机号登录 / 换绑也要靠它。
