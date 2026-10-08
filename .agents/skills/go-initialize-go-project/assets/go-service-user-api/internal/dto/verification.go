package dto

// SendVerificationCodeRequest 发送验证码请求
//
// 用 target + target_type 而不是分别开 email / phone 两个字段：
// 加一种接收方式（比如以后接 WhatsApp）只需要扩 target_type 的取值，
// 请求体形状不变。
type SendVerificationCodeRequest struct {
	// Target 接收目标：邮箱地址或手机号
	Target string `json:"target" binding:"required,max=128"`
	// TargetType 目标类型：email / phone
	TargetType string `json:"target_type" binding:"required,oneof=email phone"`
	// Scene 使用场景：register（留空默认）/ reset_password。
	//
	// 取值刻意不用 oneof 写死：合法场景由服务端的场景注册表定义
	// （service.VerificationScenes），写死在 tag 里就有了第二个定义处，
	// 漏改时请求会在绑定阶段被拒成 400，看不到那句可读的场景错误。
	// 这里只做长度约束。
	Scene string `json:"scene" binding:"omitempty,max=32"`
}

// SendVerificationCodeResponse 发送验证码响应
type SendVerificationCodeResponse struct {
	// Target 脱敏后的接收目标，不回显完整邮箱/手机号
	Target string `json:"target"`
	// TargetType 目标类型
	TargetType string `json:"target_type"`
	// Scene 实际生效的场景
	Scene string `json:"scene"`
	// ExpiresIn 验证码有效期（秒）
	ExpiresIn int `json:"expires_in"`
	// ResendAfter 距离下次可重发的秒数
	ResendAfter int `json:"resend_after"`
	// Mock 是否处于模拟模式
	Mock bool `json:"mock"`
	// Code 验证码明文，**仅 mock 模式返回**。
	// 非 mock 模式下该字段被 omitempty 整个省略，不会出现在响应里。
	Code string `json:"code,omitempty"`
}
