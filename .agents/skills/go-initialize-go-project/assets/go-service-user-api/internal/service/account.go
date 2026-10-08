package service

import (
	"context"

	"project_id/internal/apperr"
	"project_id/internal/model"
	"project_id/internal/pkg/hash"
	"project_id/internal/repository"
)

// AccountService 账号自服务业务。
//
// 只保留「账号操作自己」的能力，且每个方法的目标账号都由调用方从请求上下文取，
// 不接收外部传入的账号 ID —— 这样就不存在越权改他人账号的可能。
//
// 管理端的账号 CRUD（列表 / 创建 / 更新 / 删除他人）**有意不提供**：
// 它需要独立的权限模型（谁能管谁、管哪个组织），而权限属于
// 「账号在组织里的成员关系」，等 org_user 表落地后再补。
// 注册走 AuthService.Register，账号与默认组织在同一个事务里落库。
type AccountService struct {
	accounts *repository.AccountRepository
	orgs     *repository.OrgRepository
}

// NewAccountService 创建账号业务实例
func NewAccountService(accounts *repository.AccountRepository, orgs *repository.OrgRepository) *AccountService {
	return &AccountService{accounts: accounts, orgs: orgs}
}

// DefaultOrg 查询账号的默认组织
//
// 注册时一定会创建默认组织，但历史数据或人工干预可能缺失，因此组织不存在
// 不算错误，返回 (nil, nil)，由调用方决定如何呈现。
func (s *AccountService) DefaultOrg(ctx context.Context, id model.ID) (*model.Org, error) {
	org, err := s.orgs.FindDefaultByOwner(ctx, id)
	if err != nil {
		return nil, apperr.ErrInternal
	}
	return org, nil
}

// ChangePassword 修改密码，成功后吊销该账号已签发的全部令牌
func (s *AccountService) ChangePassword(ctx context.Context, id model.ID, oldPassword, newPassword string) error {
	account, err := s.accounts.GetByID(ctx, id)
	if err != nil {
		return apperr.ErrInternal
	}
	if account == nil {
		return apperr.ErrAccountNotFound
	}
	if !hash.VerifyPassword(account.Password, oldPassword) {
		return apperr.ErrAccountPasswordMismatch
	}
	hashed, err := hash.Password(newPassword)
	if err != nil {
		return apperr.ErrInternal
	}
	if err := s.accounts.UpdateFields(ctx, id, map[string]any{"password": hashed}); err != nil {
		return apperr.ErrInternal
	}
	// 改密后旧令牌必须立刻失效，否则密码泄露后改密形同虚设
	if err := s.accounts.BumpTokenVersion(ctx, id); err != nil {
		return apperr.ErrInternal
	}
	return nil
}

// LoadForAuth 供鉴权中间件加载账号（校验状态）
func (s *AccountService) LoadForAuth(ctx context.Context, id model.ID) (*model.Account, error) {
	account, err := s.accounts.GetByID(ctx, id)
	if err != nil {
		return nil, apperr.ErrInternal
	}
	if account == nil {
		return nil, apperr.ErrAccountNotFound
	}
	if !account.IsEnabled() {
		return nil, apperr.ErrAccountDisabled
	}
	return account, nil
}
