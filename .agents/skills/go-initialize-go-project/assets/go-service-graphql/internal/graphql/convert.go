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
// 时间字段走 scalar.FromUnix：基线的 model.Base 把 CreatedTime / UpdatedTime
// 存为 int64 unix 秒，不是 time.Time，需要在这里完成转换。

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
		LastLoginTime: scalar.FromTimePtr(a.LastLoginAt),
		CreatedTime:   scalar.FromUnix(a.CreatedTime),
		UpdatedTime:   scalar.FromUnix(a.UpdatedTime),
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
		CreatedTime: scalar.FromUnix(o.CreatedTime),
		UpdatedTime: scalar.FromUnix(o.UpdatedTime),
	}
}
