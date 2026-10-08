package graphql

import (
	gqlmodel "project_id/internal/graphql/model"
	"project_id/internal/graphql/scalar"
	"project_id/internal/model"
)

// 实体 → GraphQL 投影。
//
// 为什么不复用 dto.NewAccount：GraphQL 的字段名、可空性与标量类型
// 和 REST 的 JSON 契约是**两套独立契约**。共用意味着改 GraphQL 的可空性
// 会顺带改掉 REST 的响应形状，反之亦然。
//
// 更重要的是这里是一份**白名单**：数据库实体新增字段（比如以后加
// avatar、手机号）不会自动出现在 GraphQL 里，必须显式加一行。
// 「新增列就自动对外暴露」是实体直接当响应体的典型事故来源。
//
// 时间字段走 gqlTimestamp：模型层的 model.Timestamp 与 GraphQL 的
// scalar.Timestamp 底层都是 int64 unix 秒，转换不产生任何语义变化，
// 但必须显式过一次，避免有人在 GraphQL 层把时间重新变成 time.Time ——
// 那会让「同一份数据在 REST 与 GraphQL 两条链路上格式不同」的问题回来。

// convertAccount 账号实体 → GraphQL 投影
func convertAccount(a *model.Account) *gqlmodel.Account {
	if a == nil {
		return nil
	}
	return &gqlmodel.Account{
		ID:            a.ID.String(), // 雪花 ID 以字符串下发，避免前端 Number 精度丢失
		Username:      a.Username,
		Email:         a.Email,
		Nickname:      a.Nickname,
		Status:        int(a.Status),
		LastLoginIP:   a.LastLoginIP,
		LastLoginTime: gqlTimestampPtr(a.LastLoginAt),
		CreatedTime:   gqlTimestamp(a.CreatedTime),
		UpdatedTime:   gqlTimestamp(a.UpdatedTime),
	}
}

// convertOrg 组织实体 → GraphQL 投影
func convertOrg(o *model.Org) *gqlmodel.Org {
	if o == nil {
		return nil
	}
	return &gqlmodel.Org{
		ID:          o.ID.String(),
		Name:        o.Name,
		IsDefault:   o.IsDefault,
		CreatedTime: gqlTimestamp(o.CreatedTime),
		UpdatedTime: gqlTimestamp(o.UpdatedTime),
	}
}

// gqlTimestamp 模型层的 unix 秒 → GraphQL 标量。
//
// 两个类型底层都是 int64，转换本身不产生任何语义变化；写成函数是为了让
// 「模型层不 import graphql、graphql 层不 import 标准库时间」这条边界
// 有一个显式落点 —— 时间一旦在 GraphQL 层重新变成 time.Time，
// 就又会出现「同一份数据两条链路格式不同」的问题。
func gqlTimestamp(t model.Timestamp) scalar.Timestamp { return scalar.Timestamp(t) }

// gqlTimestampPtr 可空版本，nil 透传为 GraphQL 的 null
func gqlTimestampPtr(t *model.Timestamp) *scalar.Timestamp {
	if t == nil {
		return nil
	}
	converted := gqlTimestamp(*t)
	return &converted
}
