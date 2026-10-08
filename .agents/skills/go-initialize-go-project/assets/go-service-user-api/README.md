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
internal/dto/{account.go,auth.go}
internal/pkg/hash/{password.go,password_test.go}
internal/pkg/token/{token.go,token_test.go}
internal/model/{account.go,org.go}
internal/repository/{account.go,org.go}
internal/service/{account.go,auth.go,org.go}
internal/api/v1/account.go
internal/middleware/{auth.go,auth_test.go}
```

## 必须同步的注入点

覆盖后还要改四处，否则编译、运行或文档不完整：

1. `internal/model/models.go` 的 `AllModels()` 追加实体，使自动迁移建表：

   ```go
   func AllModels() []any {
       return []any{
           &Account{},
           &Org{},
       }
   }
   ```

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

`internal/config/config.go` 的 JWT 结构、校验与 `configs/*.yaml` 的 `jwt` 段已在
基线中无条件存在，无需改动。`jwt.secret` 在非 dev 环境必填且长度不得少于 16 字符，
由 `APP_JWT_SECRET` 环境变量注入。

4. 重新生成 Swagger 文档包，让 `/api/v1/auth/*` 出现在接口文档里：

   ```bash
   go run github.com/swaggo/swag/cmd/swag@v1.16.6 init -g cmd/server/main.go -o docs --parseDependency --parseInternal
   ```

   版本后缀取 `go.mod` 里 `github.com/swaggo/swag` 的实际版本，**不能省**：不带后缀时
   `go run` 按当前模块解析 `cmd/swag`，而它自身依赖的 `github.com/urfave/cli/v2` 与
   `sigs.k8s.io/yaml` 不在本模块里，会报 `missing go.sum entry`；补齐又会把代码生成器的
   CLI 依赖写进产品 `go.mod`。带后缀时在独立模块上下文构建，`go.mod`/`go.sum` 保持不变。

   基线 `go-service/` 自带的 `docs/` 只覆盖 `/healthz` 与 `/api/v1/system/health-check`；
   本资产的 `internal/api/v1/account.go` 带来 6 条 `@Router` 注解，不重新生成的话
   `/swagger/index.html` 就看不到任何认证接口 —— 这是条件资产落地后最常见的遗漏。
   同时把 `cmd/server/main.go` 的 `@title` 改成「<中文项目展示名称> API」、
   `@description` 改成按实际能力集描述，再执行生成；**先改注解、再生成**，顺序不能反。
   初始化结构契约检查器会双向比对注解与文档，漏掉这一步会在基线提交前失败关闭。

## 暴露的接口

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| POST | `/api/v1/auth/register` | 否 | 注册；同事务创建账号与默认组织 |
| POST | `/api/v1/auth/login` | 否 | 用户名或邮箱登录，返回双令牌 |
| POST | `/api/v1/auth/refresh` | 否 | 用刷新令牌换新令牌对 |
| POST | `/api/v1/auth/logout` | 是 | 递增令牌版本，吊销该账号全部令牌 |
| GET | `/api/v1/auth/profile` | 是 | 当前账号及其默认组织 |
| PUT | `/api/v1/auth/password` | 是 | 改密并吊销全部令牌 |

鉴权只认 `Authorization: Bearer <token>`，不接受自定义头名、裸令牌或 `?token=` 查询参数。

## 与基线共享核心的适配约定

本目录的代码已按基线约定改写，**不要**回退成源项目写法：

- **错误码用基线的命名**：`ErrTokenMalformed`、`ErrCredentialsInvalid`、
  `ErrAccountUsernameTaken`、`ErrAccountPasswordMismatch`、`ErrTokenWrongType`、
  `ErrTokenSignFailed` 等，不使用源项目的 `ErrAuthToken*` / `ErrUsernameExists` 前缀。
- **账号 ID 走 `contextx.SetAccountID` / `AccountID`**：鉴权中间件只把 `int64` 主键
  写进 request context，不放账号实体。`profile` 处理器按主键调
  `AccountService.LoadForAuth` 重新加载，因此共享核心的 `contextx` 不需要认识
  `model.Account` 类型。
- **时间字段是 `int64` unix 秒**：基线 `model.Base` 的 `CreatedTime` / `UpdatedTime`
  是 `int64`，不是 `time.Time`；`dto` 响应结构与之保持一致。
- **`apperr.APIError` 是指针类型**：`errors.As` 的断言目标必须写 `*apperr.APIError`。
- **`WithExtra` 是命名参数**：签名是 `WithExtra(key string, value any)`，附加的是结构化
  详情而非文案占位符；词条本身是静态文案，不含 `%s`。
- **令牌管理器由本域按配置创建**：`newAccountModule` 内用 `deps.Config.JWT` 调
  `token.NewManager`，不从 `Dependencies` 取。这样基线的 `Dependencies` 不必认识
  用户模块类型，关闭用户 API 时共享核心零改动。
- **`Entity` 接口不含 `SetID`**：基线 `model.Entity` 只要求 `TableName()` 与
  `GetID()`，因为 `Base.SetID` 是指针接收者，写进接口会让所有值类型实体无法满足约束。
- **`service` 不 import `gorm.io/gorm`**：事务边界走 `Repository.Transaction(ctx, fn)`，
  回调参数是 `*repository.Repository[T]`；跨仓储的嵌套操作通过 `s.orgs.WithDB(tx.DB())`
  复用同一事务。`service` 直接接触 `*gorm.DB` 会被 core-first 门禁判为 ORM 耦合违规——
  只有 `model` 与 `repository` 在 `ORM_EXEMPT_LAYERS` 内。
- **测试函数必须有紧邻中文注释**：`Test*` 开头的声明会被中文注释门禁检查，
  注释需写在声明紧邻的上一行。

## 领域说明

实体命名是 `Account` 而非 `User`：划分是「账号 / 组织」而不是「用户 / 角色」。
注册时同事务创建一个 `is_default = true` 的默认组织，`orgs.owner_id` 指向该账号。
账号加入他人组织是后续扩展，届时新增 `org_user` 关联表，`orgs` 与 `accounts`
结构都不需要改动。权限字段有意不放在账号上——权限属于账号在组织里的成员关系。
