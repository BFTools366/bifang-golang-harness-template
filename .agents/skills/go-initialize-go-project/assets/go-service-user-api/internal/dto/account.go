// Package dto 定义 HTTP 层的请求/响应结构，与数据库实体解耦。
package dto

import (
	"project_id/internal/model"
)

// Account 账号信息响应
//
// 三个时间字段都是 model.Timestamp（unix 秒）：
// 命名 int64 类型在 encoding/json 里编码成**数字**，前端直接拿去做
// new Date(sec * 1000) 即可，不需要解析字符串、也不受时区格式影响。
// 未登录过的账号 last_login_at 为 null。
type Account struct {
	ID          model.ID         `json:"id"`
	Username    string           `json:"username"`
	Email       string           `json:"email"`
	Phone       *string          `json:"phone"`
	Nickname    string           `json:"nickname"`
	Status      int8             `json:"status"`
	LastLoginAt *model.Timestamp `json:"last_login_at"`
	LastLoginIP string           `json:"last_login_ip"`
	CreatedTime model.Timestamp  `json:"created_time"`
	UpdatedTime model.Timestamp  `json:"updated_time"`
}

// NewAccount 实体转响应对象
func NewAccount(a *model.Account) *Account {
	if a == nil {
		return nil
	}
	return &Account{
		ID:          a.ID,
		Username:    a.Username,
		Email:       a.Email,
		Phone:       a.Phone,
		Nickname:    a.Nickname,
		Status:      a.Status,
		LastLoginAt: a.LastLoginAt,
		LastLoginIP: a.LastLoginIP,
		CreatedTime: a.CreatedTime,
		UpdatedTime: a.UpdatedTime,
	}
}

// Org 组织信息响应
type Org struct {
	ID          model.ID        `json:"id"`
	Name        string          `json:"name"`
	OwnerID     model.ID        `json:"owner_id"`
	IsDefault   bool            `json:"is_default"`
	CreatedTime model.Timestamp `json:"created_time"`
	UpdatedTime model.Timestamp `json:"updated_time"`
}

// NewOrg 实体转响应对象，实体为 nil 时返回 nil
func NewOrg(o *model.Org) *Org {
	if o == nil {
		return nil
	}
	return &Org{
		ID:          o.ID,
		Name:        o.Name,
		OwnerID:     o.OwnerID,
		IsDefault:   o.IsDefault,
		CreatedTime: o.CreatedTime,
		UpdatedTime: o.UpdatedTime,
	}
}

// AccountDetail 账号详情响应，附带该账号的默认组织
//
// 账号与组织是一对多的（后续还会加入别人的组织），所以组织作为独立字段返回，
// 而不是拍平进 Account。
//
// 注意这里没有「目标账号 ID」入参 —— 该结构只用于「我自己」的详情，
// 不用于按 ID 查询任意账号（那属于管理端接口）。
type AccountDetail struct {
	Account *Account `json:"account"`
	Org     *Org     `json:"org"`
}
