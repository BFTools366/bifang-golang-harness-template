// Package graphql 是 GraphQL 查询层：执行入口、根解析器、错误映射与上下文桥接。
//
// 定位：与 REST 并存的**只读查询层**。schema 只暴露 Query，不提供 Mutation。
//
// 本包不实现 v1.Module —— 挂路由的活儿在 internal/api/v1/graphql.go 里做，
// 这样 GraphQL 层不需要认识 gin，api 层也不需要认识 gqlgen 的执行细节。
//
// 分层归属：本包属于**适配器**，与 internal/api 同级，依赖方向是
// internal/graphql → internal/service → internal/repository → internal/model。
// core 侧（service / repository / model / apperr）不得反向依赖本包。
package graphql

import (
	"project_id/internal/config"
	"project_id/internal/service"
)

// Resolver 是 GraphQL 根解析器。
//
// 只持有本层需要的 service 与配置。装配在 api/v1 的 graphql 模块里完成 ——
// 与其他业务模块的规矩一致：谁用谁装配，业务对象不进 bootstrap.Container。
//
// 本文件**不参与代码生成**：gqlgen 只在它不存在时才创建空壳，
// 所以这里可以自由增删字段，重新生成不会覆盖。
type Resolver struct {
	// Config 是运行配置，health 查询从它读应用名称与版本。
	Config *config.Config
	// Accounts 是账号自服务业务，me 查询用它加载账号与默认组织。
	Accounts *service.AccountService
}
