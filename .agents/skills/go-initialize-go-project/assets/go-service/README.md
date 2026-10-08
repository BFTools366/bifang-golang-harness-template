# <project_id>

Example Service（示例服务）。

本仓库是中性 Go 后端服务脚手架：只提供进程生命周期、配置、日志、统一响应体、错误契约、多语言、泛型仓储与健康检查，不包含任何业务假设。

## 技术基线

- Go `>= 1.26.0`
- Gin 作为 HTTP 框架
- GORM 作为数据访问层，支持 sqlite / mysql / postgres
- Viper 负责分层配置，logrus + lumberjack 负责日志
- validator/v10 负责请求字段校验，go-playground 的 tag 名映射到 json 字段名
- 雪花算法负责主键，soft_delete 负责逻辑删除

## 目录结构

```text
cmd/server            进程入口
internal/bootstrap    组件装配与 HTTP 服务端
internal/api          HTTP 引擎与路由装配
internal/api/v1       v1 版本模块与路由
internal/middleware   请求追踪、语言协商、访问日志、错误恢复、跨域、限流
internal/apperr       统一错误类型与错误码
internal/config       分层配置加载与校验
internal/constant     跨层常量
internal/database     数据库连接、连接池与迁移
internal/model        实体基础结构与标识类型
internal/repository   泛型数据访问仓储
internal/service      用例编排层（中性脚手架为空）
internal/pkg/*        可复用基础包
configs               基线配置与环境配置
```

## 快速开始

```bash
go mod download
go build ./...
go test ./...
go run ./cmd/server -e dev
```

服务默认监听 `0.0.0.0:8080`。

```bash
curl http://127.0.0.1:8080/healthz
curl http://127.0.0.1:8080/api/v1/system/health-check
```

## 接口契约

接口固定为 HTTP API，交付平台固定为 Linux；两者持久记录在 `.harness/go-service-profile.json`。

统一响应体固定为五种形状：

| 场景 | 形状 |
|---|---|
| 单对象 | `{"model":"system","data":{...},"request_id":"..."}` |
| 数据集 | `{"model":"data.set","datas":[...],"total":N}` |
| 分页 | `{"model":"grid.result","page":{...},"result":{...}}` |
| 空结果 | `{"model":"empty"}` |
| 失败 | `{"model":"errors","errors":{"model":"data.set","datas":[{"model":"error","code":"...","message":"..."}],"total":1}}` |

中间件顺序是固定契约，不得调整：

```text
RequestID → Locale（条件 I18N.Enabled）→ Logger → ErrorHandler → CORS（条件）→ RateLimit（条件）
```

Logger 必须位于 ErrorHandler 外层，panic 被恢复后才能拿到真实状态码并落访问日志。

## 配置

配置按以下优先级生效，后者覆盖前者：

1. `configs/config.yaml` 基线配置
2. `configs/config-{env}.yaml` 环境配置（深合并）
3. `APP_*` 环境变量
4. 代码默认值

环境名解析顺序为 `-e/--env` > `APP_ENV` > `app.env` > `dev`。

## 状态

`productDefinitionRequired=true`：本脚手架尚未定义产品边界，产品目的、核心输入输出、业务规则与成功标准必须在切换到本目录后通过 `$go-define-product` 提出。
