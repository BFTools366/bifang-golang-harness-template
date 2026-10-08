package repository

import (
	"context"
	"time"

	"project_id/internal/model"

	"gorm.io/gorm"
)

// AccountRepository 账号仓储，在泛型 CRUD 基础上追加账号域专属查询。
type AccountRepository struct {
	*Repository[model.Account]
	db *gorm.DB
}

// NewAccountRepository 创建账号仓储
func NewAccountRepository(db *gorm.DB) *AccountRepository {
	return &AccountRepository{
		Repository: New[model.Account](db),
		db:         db,
	}
}

// FindByUsernameOrEmail 按用户名或邮箱查询（登录用），未找到返回 (nil, nil)
func (r *AccountRepository) FindByUsernameOrEmail(ctx context.Context, keyword string) (*model.Account, error) {
	return r.Get(ctx, func(db *gorm.DB) *gorm.DB {
		return db.Where("username = ? OR email = ?", keyword, keyword)
	})
}

// ExistsUsername 判断用户名是否已被占用，excludeID 用于更新场景排除自身
func (r *AccountRepository) ExistsUsername(ctx context.Context, username string, excludeID ...model.ID) (bool, error) {
	scopes := []Scope{WhereEq("username", username)}
	if len(excludeID) > 0 && excludeID[0] > 0 {
		scopes = append(scopes, func(db *gorm.DB) *gorm.DB { return db.Where("id <> ?", excludeID[0]) })
	}
	return r.Exists(ctx, scopes...)
}

// ExistsEmail 判断邮箱是否已被占用，excludeID 用于更新场景排除自身
func (r *AccountRepository) ExistsEmail(ctx context.Context, email string, excludeID ...model.ID) (bool, error) {
	scopes := []Scope{WhereEq("email", email)}
	if len(excludeID) > 0 && excludeID[0] > 0 {
		scopes = append(scopes, func(db *gorm.DB) *gorm.DB { return db.Where("id <> ?", excludeID[0]) })
	}
	return r.Exists(ctx, scopes...)
}

// BumpTokenVersion 递增令牌版本，用于登出/改密后吊销该账号已签发的全部令牌
func (r *AccountRepository) BumpTokenVersion(ctx context.Context, id model.ID) error {
	return r.db.WithContext(ctx).
		Model(&model.Account{}).
		Where("id = ?", id).
		UpdateColumn("token_version", gorm.Expr("token_version + 1")).
		Error
}

// TouchLogin 记录最近登录信息
func (r *AccountRepository) TouchLogin(ctx context.Context, id model.ID, ip string) error {
	now := time.Now()
	return r.UpdateFields(ctx, id, map[string]any{
		"last_login_at": now,
		"last_login_ip": ip,
	})
}
