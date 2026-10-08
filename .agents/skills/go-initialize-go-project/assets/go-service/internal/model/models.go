package model

// AllModels 返回全部需要参与自动迁移的实体。
//
// 中性初始化不包含任何业务实体；产品获批后在此追加实体，
// 并把对应表结构迁移交给启动时的自动迁移流程。
func AllModels() []any {
	return []any{}
}
