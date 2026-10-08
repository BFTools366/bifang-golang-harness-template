package repository

import (
	"context"

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

// WithDB 基于给定连接派生新仓储（事务场景使用）。
//
// 必须覆写：泛型基类的 WithDB 返回 *Repository[T]，拿到它就没法再调用
// 本类型特有的方法（如 UpdatePassword），事务里就只能退回基类 CRUD。
func (r *AccountRepository) WithDB(db *gorm.DB) *AccountRepository {
	return &AccountRepository{
		Repository: r.Repository.WithDB(db),
		db:         db,
	}
}

// UpdatePassword 更新密码哈希，并在同一条语句里递增令牌版本。
//
// 两件事必须落在同一条 UPDATE：分开写会留下「密码已换、旧令牌仍然有效」的
// 窗口，而这正是改密与重置密码最不该有的窗口。单条语句天然原子，
// 因此不需要额外包一层显式事务。
func (r *AccountRepository) UpdatePassword(ctx context.Context, id model.ID, hashed string) error {
	return r.UpdateFields(ctx, id, map[string]any{
		"password":      hashed,
		"token_version": gorm.Expr("token_version + 1"),
	})
}

// FindByUsernameOrEmail 按用户名或邮箱查询（登录用），未找到返回 (nil, nil)
func (r *AccountRepository) FindByUsernameOrEmail(ctx context.Context, keyword string) (*model.Account, error) {
	return r.Get(ctx, func(db *gorm.DB) *gorm.DB {
		return db.Where("username = ? OR email = ?", keyword, keyword)
	})
}

// FindByTarget 按验证码接收目标（邮箱或手机号）定位账号，未找到返回 (nil, nil)。
//
// targetType 取 model.VerificationTarget* 的取值。未知类型返回 (nil, nil)
// 而不是报错：调用方在归一化阶段已经把非法类型挡掉了，这里只是兜底，
// 报错反而会让「没找到」和「参数不对」两种语义混在一个返回值里。
func (r *AccountRepository) FindByTarget(ctx context.Context, targetType, value string) (*model.Account, error) {
	switch targetType {
	case model.VerificationTargetEmail:
		return r.Get(ctx, WhereEq("email", value))
	case model.VerificationTargetPhone:
		return r.Get(ctx, WhereEq("phone", value))
	default:
		return nil, nil
	}
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

// ExistsPhone 判断手机号是否已被占用，excludeID 用于更新场景排除自身。
//
// 手机号是可选列，未填写时写入 NULL；唯一索引允许多个 NULL 并存，
// 因此「不填手机号」的账号之间不会互相冲突。
func (r *AccountRepository) ExistsPhone(ctx context.Context, phone string, excludeID ...model.ID) (bool, error) {
	scopes := []Scope{WhereEq("phone", phone)}
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

// TouchLogin 记录最近登录信息。
//
// 时间走 model.Now()（unix 秒）而不是 time.Now()：这里用 map 更新，
// GORM 不会对 map 里的值做类型转换，直接把 time.Time 塞进 bigint 列会
// 被驱动按各自的规则处理（sqlite 存成文本、MySQL 隐式转换），
// 于是库里的值既不是秒也不是时间，只能靠显式传 Timestamp 避免。
func (r *AccountRepository) TouchLogin(ctx context.Context, id model.ID, ip string) error {
	return r.UpdateFields(ctx, id, map[string]any{
		"last_login_at": model.Now(),
		"last_login_ip": ip,
	})
}
