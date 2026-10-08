package v1

import (
	"project_id/internal/dto"
	"project_id/internal/middleware"
	"project_id/internal/model"
	"project_id/internal/pkg/contextx"
	"project_id/internal/pkg/notify"
	"project_id/internal/pkg/request"
	"project_id/internal/pkg/response"
	"project_id/internal/pkg/token"
	"project_id/internal/repository"
	"project_id/internal/service"

	"github.com/gin-gonic/gin"
)

// accountModule 账号域：发送验证码 / 注册 / 登录 / 刷新令牌 / 登出 / 当前账号 / 改密 / 重置密码。
//
// repository 与 service 都在 newAccountModule 里创建，不导出给外部 ——
// 本域怎么装配属于本域自己的事，其他模块与 bootstrap 都不需要知道。
type accountModule struct {
	auth         *service.AuthService
	accounts     *service.AccountService
	verification *service.VerificationService
}

// newAccountModule 装配账号域
//
// 令牌管理器由本域按配置自行创建，不从 Dependencies 取 —— 这样共享核心的
// Dependencies 就不必认识用户模块的令牌类型，用户 API 关闭时核心零残留。
// 验证码的发送通道同理：由本域按 config.Verification.Provider 构造。
func newAccountModule(deps Dependencies) *accountModule {
	accountRepo := repository.NewAccountRepository(deps.DB)
	orgRepo := repository.NewOrgRepository(deps.DB)
	codeRepo := repository.NewVerificationCodeRepository(deps.DB)
	tokens := token.NewManager(
		deps.Config.JWT.Secret,
		deps.Config.JWT.Issuer,
		deps.Config.JWT.AccessTTL,
		deps.Config.JWT.RefreshTTL,
	)
	verification := service.NewVerificationService(
		codeRepo,
		accountRepo,
		deps.Config.Verification,
		notify.New(deps.Config.Verification.Provider),
	)
	return &accountModule{
		auth:         service.NewAuthService(accountRepo, orgRepo, verification, tokens),
		accounts:     service.NewAccountService(accountRepo, orgRepo),
		verification: verification,
	}
}

// Register 挂载账号路由
//
// 前缀、鉴权分组都在这里，一眼能看全本域暴露了什么。
func (m *accountModule) Register(engine *gin.Engine) {
	auth := engine.Group("/api/v1/auth")

	// 匿名可访问
	auth.POST("/verification-code", m.sendVerificationCode)
	auth.POST("/register", m.register)
	auth.POST("/login", m.login)
	auth.POST("/refresh", m.refresh)
	// 忘记密码：匿名入口，凭证是发到邮箱/手机号的验证码
	auth.POST("/password/reset", m.resetPassword)

	// 需要鉴权，且全部只操作「当前登录账号自己」，不接收目标账号 ID
	authed := auth.Group("").Use(middleware.Auth(m.auth))
	authed.POST("/logout", m.logout)
	authed.GET("/profile", m.profile)
	authed.PUT("/password", m.changePassword)
}

// sendVerificationCode 发送验证码
//
//	@Tags			Auth
//	@Summary		发送验证码
//	@Description	向指定邮箱或手机号发送验证码。scene 决定用途：register（注册，留空默认）或 reset_password（重置密码，要求该目标已注册）。mock 模式下不真实发送，验证码直接随响应返回（字段 code）；非 mock 模式下 code 字段不出现。同一目标同一场景 60 秒内只能发一次，24 小时内最多 10 次
//	@Accept			json
//	@Produce		json
//	@Param			body	body		dto.SendVerificationCodeRequest	true	"发送参数"
//	@Success		200		{object}	response.Body{data=dto.SendVerificationCodeResponse}	"发送成功"
//	@Failure		400		{object}	response.ErrorBody	"参数校验失败、目标格式不正确或场景不支持"
//	@Failure		404		{object}	response.ErrorBody	"reset_password 场景下该目标尚未注册"
//	@Failure		429		{object}	response.ErrorBody	"发送过于频繁或超出每日上限"
//	@Failure		503		{object}	response.ErrorBody	"验证码功能未启用或发送通道未配置"
//	@Router			/api/v1/auth/verification-code [post]
func (m *accountModule) sendVerificationCode(c *gin.Context) {
	var req dto.SendVerificationCodeRequest
	request.Bind(c, &req)

	result, err := m.verification.Send(c.Request.Context(), &req, c.ClientIP())
	if err != nil {
		panic(err)
	}
	response.OK(c, "verification.code", result)
}

// register 账号注册
//
//	@Tags			Auth
//	@Summary		账号注册
//	@Description	创建新账号，用户名与邮箱全局唯一；注册成功同时初始化该账号的默认组织（不自动登录）。开启验证码后需先调用发送验证码接口，并把验证码放进 code 字段
//	@Accept			json
//	@Produce		json
//	@Param			body	body		dto.RegisterRequest	true	"注册参数"
//	@Success		200		{object}	response.Body{data=dto.Account}	"注册成功"
//	@Failure		400		{object}	response.ErrorBody			"参数校验失败或验证码不正确"
//	@Failure		409		{object}	response.ErrorBody			"用户名、邮箱或手机号已占用"
//	@Router			/api/v1/auth/register [post]
func (m *accountModule) register(c *gin.Context) {
	var req dto.RegisterRequest
	request.Bind(c, &req)

	account, err := m.auth.Register(c.Request.Context(), &req)
	if err != nil {
		panic(err)
	}
	response.OK(c, "account", dto.NewAccount(account))
}

// login 账号登录
//
//	@Tags			Auth
//	@Summary		账号登录
//	@Description	account 支持用户名或邮箱；成功后返回 access_token / refresh_token
//	@Accept			json
//	@Produce		json
//	@Param			body	body		dto.LoginRequest	true	"登录参数"
//	@Success		200		{object}	response.Body{data=dto.AuthResponse}	"登录成功"
//	@Failure		400		{object}	response.ErrorBody					"参数校验失败"
//	@Failure		401		{object}	response.ErrorBody					"账号或密码错误"
//	@Failure		403		{object}	response.ErrorBody					"账号已被禁用"
//	@Router			/api/v1/auth/login [post]
func (m *accountModule) login(c *gin.Context) {
	var req dto.LoginRequest
	request.Bind(c, &req)

	result, err := m.auth.Login(c.Request.Context(), &req, dto.ClientMeta{
		IP:        c.ClientIP(),
		UserAgent: c.Request.UserAgent(),
	})
	if err != nil {
		panic(err)
	}
	response.OK(c, "auth.token", result)
}

// refresh 刷新令牌
//
//	@Tags			Auth
//	@Summary		刷新令牌
//	@Description	使用 refresh_token 换取新的令牌对
//	@Accept			json
//	@Produce		json
//	@Param			body	body		dto.RefreshTokenRequest	true	"刷新参数"
//	@Success		200		{object}	response.Body{data=dto.AuthResponse}	"刷新成功"
//	@Failure		401		{object}	response.ErrorBody					"刷新令牌无效或已失效"
//	@Router			/api/v1/auth/refresh [post]
func (m *accountModule) refresh(c *gin.Context) {
	var req dto.RefreshTokenRequest
	request.Bind(c, &req)

	result, err := m.auth.Refresh(c.Request.Context(), req.RefreshToken)
	if err != nil {
		panic(err)
	}
	response.OK(c, "auth.token", result)
}

// logout 退出登录
//
//	@Tags			Auth
//	@Summary		退出登录
//	@Description	递增令牌版本，吊销该账号已签发的全部令牌（含其他设备）
//	@Produce		json
//	@Security		Authorization
//	@Success		200	{object}	response.Body	"退出成功"
//	@Failure		401	{object}	response.ErrorBody	"未登录或令牌失效"
//	@Router			/api/v1/auth/logout [post]
func (m *accountModule) logout(c *gin.Context) {
	if err := m.auth.Logout(c.Request.Context(), model.ID(contextx.AccountID(c.Request.Context()))); err != nil {
		panic(err)
	}
	response.NoContent(c)
}

// profile 获取当前登录账号信息
//
//	@Tags			Auth
//	@Summary		当前账号信息
//	@Description	返回当前登录账号及其默认组织。账号由令牌解析得到，不接受目标账号 ID
//	@Produce		json
//	@Security		Authorization
//	@Success		200	{object}	response.Body{data=dto.AccountDetail}	"查询成功"
//	@Failure		401	{object}	response.ErrorBody					"未登录或令牌失效"
//	@Router			/api/v1/auth/profile [get]
func (m *accountModule) profile(c *gin.Context) {
	// 鉴权中间件只把账号 ID 写进上下文，账号实体在这里按主键加载。
	account, err := m.accounts.LoadForAuth(
		c.Request.Context(),
		model.ID(contextx.AccountID(c.Request.Context())),
	)
	if err != nil {
		panic(err)
	}
	org, err := m.accounts.DefaultOrg(c.Request.Context(), account.ID)
	if err != nil {
		panic(err)
	}
	response.OK(c, "account", dto.AccountDetail{
		Account: dto.NewAccount(account),
		Org:     dto.NewOrg(org),
	})
}

// changePassword 修改密码
//
//	@Tags			Auth
//	@Summary		修改密码
//	@Description	校验原密码后更新密码，并吊销该账号全部已签发令牌（需重新登录）
//	@Accept			json
//	@Produce		json
//	@Security		Authorization
//	@Param			body	body		dto.ChangePasswordRequest	true	"密码参数"
//	@Success		200		{object}	response.Body	"修改成功"
//	@Failure		400		{object}	response.ErrorBody	"原密码错误或新密码不符合要求"
//	@Failure		401		{object}	response.ErrorBody	"未登录或令牌失效"
//	@Router			/api/v1/auth/password [put]
func (m *accountModule) changePassword(c *gin.Context) {
	var req dto.ChangePasswordRequest
	request.Bind(c, &req)

	if err := m.accounts.ChangePassword(c.Request.Context(), model.ID(contextx.AccountID(c.Request.Context())), req.OldPassword, req.NewPassword); err != nil {
		panic(err)
	}
	response.NoContent(c)
}

// resetPassword 用验证码重置密码
//
//	@Tags			Auth
//	@Summary		重置密码（忘记密码）
//	@Description	匿名接口：用发送到邮箱/手机号的 reset_password 场景验证码重置密码。成功后该账号全部已签发令牌立即失效（含其他设备），需要重新登录
//	@Accept			json
//	@Produce		json
//	@Param			body	body		dto.ResetPasswordRequest	true	"重置参数"
//	@Success		200		{object}	response.Body	"重置成功"
//	@Failure		400		{object}	response.ErrorBody	"参数校验失败、验证码不正确/已过期或新密码不符合要求"
//	@Failure		404		{object}	response.ErrorBody	"该邮箱或手机号尚未注册"
//	@Failure		429		{object}	response.ErrorBody	"验证码错误次数过多"
//	@Failure		503		{object}	response.ErrorBody	"验证码功能未启用"
//	@Router			/api/v1/auth/password/reset [post]
func (m *accountModule) resetPassword(c *gin.Context) {
	var req dto.ResetPasswordRequest
	request.Bind(c, &req)

	if err := m.auth.ResetPassword(c.Request.Context(), &req); err != nil {
		panic(err)
	}
	response.NoContent(c)
}
