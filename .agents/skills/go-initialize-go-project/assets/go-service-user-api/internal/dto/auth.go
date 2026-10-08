package dto

import (
	"project_id/internal/pkg/token"
)

// RegisterRequest 注册请求
//
// Code 的必填性取决于 verification.enabled，不能写死在 binding tag 上：
// 关掉验证码功能时请求体里就没有这个字段，写 required 会让所有注册请求 400。
// 所以这里只做格式约束，必填性在 service 层按配置判断。
type RegisterRequest struct {
	Username string `json:"username" binding:"required,username"`
	Email    string `json:"email" binding:"required,email,max=128"`
	// Phone 手机号，可选填。填了就用它做唯一性校验，也能作为验证码的接收目标
	Phone    string `json:"phone" binding:"omitempty,e164"`
	Password string `json:"password" binding:"required,password"`
	Nickname string `json:"nickname" binding:"omitempty,max=64"`
	// Code 验证码
	Code string `json:"code" binding:"omitempty,numeric,max=16"`
	// CodeType 验证码校验的目标类型：email / phone，留空默认 email。
	// 决定用 Email 还是 Phone 去匹配验证码记录
	CodeType string `json:"code_type" binding:"omitempty,oneof=email phone"`
}

// LoginRequest 登录请求，account 支持用户名或邮箱
type LoginRequest struct {
	Account  string `json:"account" binding:"required,max=128"`
	Password string `json:"password" binding:"required,max=64"`
}

// RefreshTokenRequest 刷新令牌请求
type RefreshTokenRequest struct {
	RefreshToken string `json:"refresh_token" binding:"required"`
}

// ChangePasswordRequest 修改密码请求
type ChangePasswordRequest struct {
	OldPassword string `json:"old_password" binding:"required,max=64"`
	NewPassword string `json:"new_password" binding:"required,password"`
}

// ResetPasswordRequest 重置密码请求（忘记密码，匿名调用）
//
// 与 ChangePasswordRequest 的区别：改密靠「登录态 + 原密码」证明身份，
// 重置是匿名入口，唯一凭证就是验证码。
//
// Code 的必填性同样不写进 binding tag：功能关闭时这个接口应当直接返回
// 503「验证码未启用」，而不是先被绑定阶段判成 400，那样会掩盖真正的原因。
type ResetPasswordRequest struct {
	// Target 接收验证码的邮箱或手机号，必须已绑定账号
	Target string `json:"target" binding:"required,max=128"`
	// TargetType 目标类型：email / phone
	TargetType string `json:"target_type" binding:"required,oneof=email phone"`
	// Code 收到的验证码（场景固定为 reset_password）
	Code string `json:"code" binding:"omitempty,numeric,max=16"`
	// NewPassword 新密码
	NewPassword string `json:"new_password" binding:"required,password"`
}

// AuthResponse 登录/刷新成功响应
type AuthResponse struct {
	Token   *token.Pair `json:"token"`
	Account *Account    `json:"account"`
}

// ClientMeta 客户端元信息，用于记录登录来源
type ClientMeta struct {
	IP        string
	UserAgent string
}
