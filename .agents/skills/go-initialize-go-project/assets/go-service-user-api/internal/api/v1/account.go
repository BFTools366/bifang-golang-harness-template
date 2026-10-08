package v1

import (
	"project_id/internal/dto"
	"project_id/internal/middleware"
	"project_id/internal/model"
	"project_id/internal/pkg/contextx"
	"project_id/internal/pkg/request"
	"project_id/internal/pkg/response"
	"project_id/internal/pkg/token"
	"project_id/internal/repository"
	"project_id/internal/service"

	"github.com/gin-gonic/gin"
)

// accountModule 账号域：注册 / 登录 / 刷新令牌 / 登出 / 当前账号 / 改密。
//
// repository 与 service 都在 newAccountModule 里创建，不导出给外部 ——
// 本域怎么装配属于本域自己的事，其他模块与 bootstrap 都不需要知道。
type accountModule struct {
	auth     *service.AuthService
	accounts *service.AccountService
}

// newAccountModule 装配账号域
//
// 令牌管理器由本域按配置自行创建，不从 Dependencies 取 —— 这样共享核心的
// Dependencies 就不必认识用户模块的令牌类型，用户 API 关闭时核心零残留。
func newAccountModule(deps Dependencies) *accountModule {
	accountRepo := repository.NewAccountRepository(deps.DB)
	orgRepo := repository.NewOrgRepository(deps.DB)
	tokens := token.NewManager(
		deps.Config.JWT.Secret,
		deps.Config.JWT.Issuer,
		deps.Config.JWT.AccessTTL,
		deps.Config.JWT.RefreshTTL,
	)
	return &accountModule{
		auth:     service.NewAuthService(accountRepo, orgRepo, tokens),
		accounts: service.NewAccountService(accountRepo, orgRepo),
	}
}

// Register 挂载账号路由
//
// 前缀、鉴权分组都在这里，一眼能看全本域暴露了什么。
func (m *accountModule) Register(engine *gin.Engine) {
	auth := engine.Group("/api/v1/auth")

	// 匿名可访问
	auth.POST("/register", m.register)
	auth.POST("/login", m.login)
	auth.POST("/refresh", m.refresh)

	// 需要鉴权，且全部只操作「当前登录账号自己」，不接收目标账号 ID
	authed := auth.Group("").Use(middleware.Auth(m.auth))
	authed.POST("/logout", m.logout)
	authed.GET("/profile", m.profile)
	authed.PUT("/password", m.changePassword)
}

// register 账号注册
//
//	@Tags			Auth
//	@Summary		账号注册
//	@Description	创建新账号，用户名与邮箱全局唯一；注册成功同时初始化该账号的默认组织（不自动登录）
//	@Accept			json
//	@Produce		json
//	@Param			body	body		dto.RegisterRequest	true	"注册参数"
//	@Success		200		{object}	response.Body{data=dto.Account}	"注册成功"
//	@Failure		400		{object}	response.ErrorBody			"参数校验失败"
//	@Failure		409		{object}	response.ErrorBody			"用户名或邮箱已占用"
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
