package model

// 账号状态
const (
	AccountStatusDisabled int8 = 0 // 禁用
	AccountStatusEnabled  int8 = 1 // 正常
)

// Account 账号表
//
// 为什么叫 Account 而不是 User：
//
//	实体划分是「账号 / 组织」而不是「用户 / 角色」。
//	一个账号在注册时自动拥有一个默认组织（见 Org），后续还可以加入其它账号的组织，
//	「账号」比「用户」更能表达这种跨组织的身份。
//
// 唯一约束说明：username / email 均为唯一索引，软删除后仍占用索引，
// 这是有意为之 —— 避免用户名被他人抢注造成的历史数据歧义。
//
// 本表不含任何权限字段。权限属于「账号在某个组织里的成员关系」，
// 等 org_user 表引入时再落到那里，不放在账号上。
//
// 也不含 avatar 这类「个人资料」字段：当前没有任何接口能写它，
// 留着就是一列永远为空的死字段。等真的做资料编辑（PATCH /auth/profile）时再加。
// Phone 是例外 —— 它不是资料字段，而是身份标识：验证码可以直接发到手机上，
// 以后做手机号登录 / 换绑也要靠它，所以注册时就允许带上。
//
// Phone 用 *string 而不是 string：手机号是可选填的，用空字符串会因为
// uniqueIndex 让第二个不填手机号的账号注册失败（多个 "" 互相冲突）。
// 指针写入的是 NULL，而 MySQL 与 SQLite 的唯一索引都允许多个 NULL 并存。
type Account struct {
	Base
	Username     string     `gorm:"size:64;uniqueIndex;not null;comment:用户名" json:"username"`
	Email        string     `gorm:"size:128;uniqueIndex;not null;comment:邮箱" json:"email"`
	Phone        *string    `gorm:"size:32;uniqueIndex;comment:手机号（E.164，可空）" json:"phone"`
	Password     string     `gorm:"size:128;not null;comment:密码哈希" json:"-"`
	Nickname     string     `gorm:"size:64;comment:昵称，用于生成默认组织名" json:"nickname"`
	Status       int8       `gorm:"not null;default:1;index;comment:状态 0禁用 1正常" json:"status"`
	TokenVersion int64      `gorm:"not null;default:0;comment:令牌版本，自增即吊销全部已签发令牌" json:"-"`
	LastLoginAt  *Timestamp `gorm:"comment:最后登录时间（unix 秒，未登录过为 NULL）" json:"last_login_at"`
	LastLoginIP  string     `gorm:"size:64;comment:最后登录IP" json:"last_login_ip"`
}

// TableName 显式指定表名，不依赖 GORM 的复数化规则
func (Account) TableName() string { return "accounts" }

// IsEnabled 账号是否可用
func (a *Account) IsEnabled() bool { return a.Status == AccountStatusEnabled }
