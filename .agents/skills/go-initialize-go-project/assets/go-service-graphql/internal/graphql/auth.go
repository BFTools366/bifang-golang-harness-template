package graphql

import (
	"context"

	"project_id/internal/apperr"
	"project_id/internal/constant"
	"project_id/internal/graphql/gqlctx"
	"project_id/internal/model"
)

// currentAccountID 取当前登录账号主键，未登录返回统一的鉴权错误。
//
// 为什么不在端点上做强制鉴权：GraphQL 只有一个端点，强制鉴权会让
// health 这类公开查询也必须带令牌。所以改成可选鉴权 + 需要登录的字段自己判，
// 错误码沿用 REST 时代的 auth.token.missing，客户端不需要换一套错误码表。
//
// 只取主键而不是账号实体：基线的鉴权中间件只写 int64 主键进上下文
// （contextx.SetAccountID），实体由调用方按主键重新加载。
func currentAccountID(ctx context.Context) (model.ID, error) {
	id := gqlctx.AccountID(ctx)
	if id == 0 {
		return 0, apperr.ErrTokenMissing.WithExtra("header", constant.HeaderAuthorization)
	}
	return model.ID(id), nil
}
