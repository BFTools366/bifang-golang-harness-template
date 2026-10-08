package model

// Org 组织表
//
// 领域模型：
//
//   - 每个账号在注册时自动创建一个「默认组织」，owner_id 指向该账号
//     （见 service.AuthService.Register，账号与组织在同一个事务里落库）。
//
//   - 查某账号的默认组织：WHERE owner_id = ? AND is_default = 1。
//
//   - 账号加入**别人**的组织是后续扩展。届时新增关联表：
//
//     org_user(org_id, account_id, joined_time, ...)
//
//     本表结构不需要改动，成员关系全部落在关联表里。
//
// 为什么现在不建 org_user：
//
//	没有多组织成员关系时，多一张表只会带来空关联和额外查询。
//	等真的需要「一个账号属于多个组织」时再引入，避免为想象中的需求付出复杂度。
//
// 为什么 is_default 单独占一列：
//
//	引入 org_user 之后，一个账号会属于多个组织（自己的 + 别人邀请的）。
//	「哪个是它的个人组织」必须显式表达，否则每次都要靠 owner_id = account_id 反推，
//	而「账号自己创建的」和「账号日常在用的」并不总是同一个。
type Org struct {
	Base
	Name      string `gorm:"size:64;not null;index;comment:组织名" json:"name"`
	OwnerID   ID     `gorm:"not null;index;comment:拥有者账号 ID，对应 accounts.id" json:"owner_id"`
	IsDefault bool   `gorm:"not null;default:false;comment:是否为拥有者的默认组织" json:"is_default"`
}

// TableName 显式指定表名，不依赖 GORM 的复数化规则
func (Org) TableName() string { return "orgs" }
