package repository

import (
	"context"

	"project_id/internal/model"

	"gorm.io/gorm"
)

// VerificationCodeRepository 验证码仓储。
//
// 表是「同目标多条历史记录」的结构，所以这里的方法围绕
// 「取最新一条」「按时间窗口计数」「批量作废」三种诉求，而不是简单的 CRUD。
type VerificationCodeRepository struct {
	*Repository[model.VerificationCode]
	db *gorm.DB
}

// NewVerificationCodeRepository 创建验证码仓储
func NewVerificationCodeRepository(db *gorm.DB) *VerificationCodeRepository {
	return &VerificationCodeRepository{
		Repository: New[model.VerificationCode](db),
		db:         db,
	}
}

// WithDB 基于给定连接派生新仓储（事务场景使用）。
//
// 必须覆写：泛型基类的 WithDB 返回 *Repository[T]，
// 拿到它就没法再调用本类型特有的方法了。
func (r *VerificationCodeRepository) WithDB(db *gorm.DB) *VerificationCodeRepository {
	return &VerificationCodeRepository{
		Repository: r.Repository.WithDB(db),
		db:         db,
	}
}

// latest 取某目标在某场景下最新的一条记录，pendingOnly 为 true 时只取待使用状态。
//
// 排序用 created_time 而不是 id：主键是雪花 ID，正常情况下的确趋势递增
// （41 位时间戳在高位，node+step 占满低 22 位，恰好等于时间戳位移，
// 所以跨实例也单调），但那是**前提**不是语义 —— 手工指定主键的数据导入
// 会破坏它，多实例间毫秒级时钟偏移也会让两条记录的顺序交叉。
// created_time 直接就是「谁后建的」，不依赖任何前提。
//
// 代价可以忽略：查询已被 (target_type, target, scene) 复合索引收窄到几行，
// 对这几行做排序不需要额外索引。id 作为同毫秒并列时的确定性 tiebreaker。
//
// 不用泛型基类的 Get：它走 First()，而 First() 会再追加一个主键排序，
// 拼出 ORDER BY created_time DESC, id DESC, id 这种依赖 GORM 内部行为的语句。
// 这里显式 Limit(1) + Find，排序完全由自己控制。
func (r *VerificationCodeRepository) latest(ctx context.Context, targetType, target, scene string, pendingOnly bool) (*model.VerificationCode, error) {
	db := r.db.WithContext(ctx).
		Where("target_type = ? AND target = ? AND scene = ?", targetType, target, scene)
	if pendingOnly {
		db = db.Where("status = ?", model.VerificationCodeStatusPending)
	}

	var items []model.VerificationCode
	if err := db.Order("created_time DESC, id DESC").Limit(1).Find(&items).Error; err != nil {
		return nil, err
	}
	if len(items) == 0 {
		return nil, nil
	}
	return &items[0], nil
}

// LatestPending 取某目标在某场景下最新的一条「待使用」记录，未找到返回 (nil, nil)
func (r *VerificationCodeRepository) LatestPending(ctx context.Context, targetType, target, scene string) (*model.VerificationCode, error) {
	return r.latest(ctx, targetType, target, scene, true)
}

// Latest 取某目标在某场景下最新的一条记录，不限定状态。
//
// 用于重发间隔判断：刚发过的记录可能已被消费或作废，
// 但「刚刚发过」这个事实仍然要拦住下一次发送。
func (r *VerificationCodeRepository) Latest(ctx context.Context, targetType, target, scene string) (*model.VerificationCode, error) {
	return r.latest(ctx, targetType, target, scene, false)
}

// CountSince 统计某目标在某场景下自 since 起创建了多少条记录，用于每日发送上限。
//
// since 是 unix 秒：created_time 列本身就是秒，两边同为整数才能走索引比较，
// 传 time.Time 会被驱动各自转换，语义不可控。
func (r *VerificationCodeRepository) CountSince(ctx context.Context, targetType, target, scene string, since model.Timestamp) (int64, error) {
	return r.Count(ctx,
		WhereEq("target_type", targetType),
		WhereEq("target", target),
		WhereEq("scene", scene),
		func(db *gorm.DB) *gorm.DB { return db.Where("created_time >= ?", since) },
	)
}

// RevokePending 把某目标在某场景下所有「待使用」记录批量置为作废。
//
// 重发时必须调用：新码生效的同时旧码立刻失效，否则同时存在多个可用验证码，
// 等于把爆破难度从 10^6 降到 n/10^6。
func (r *VerificationCodeRepository) RevokePending(ctx context.Context, targetType, target, scene string) error {
	var entity model.VerificationCode
	return r.db.WithContext(ctx).
		Model(&entity).
		Where("target_type = ? AND target = ? AND scene = ? AND status = ?",
			targetType, target, scene, model.VerificationCodeStatusPending).
		Update("status", model.VerificationCodeStatusRevoked).
		Error
}

// Revoke 按主键作废单条记录
func (r *VerificationCodeRepository) Revoke(ctx context.Context, id model.ID) error {
	return r.UpdateFields(ctx, id, map[string]any{
		"status": model.VerificationCodeStatusRevoked,
	})
}

// Consume 按主键把记录标记为已使用，返回是否真的抢到了这次消费。
//
// WHERE 带上 status = 待用：并发的两次校验里只有一次能把行改掉，
// 靠 RowsAffected 判断归属，保证「一次性」在并发下也成立。
//
// now 是 unix 秒，与 used_at 列同类型，理由同 CountSince。
func (r *VerificationCodeRepository) Consume(ctx context.Context, id model.ID, now model.Timestamp) (bool, error) {
	var entity model.VerificationCode
	result := r.db.WithContext(ctx).
		Model(&entity).
		Where("id = ? AND status = ?", id, model.VerificationCodeStatusPending).
		Updates(map[string]any{
			"status":  model.VerificationCodeStatusUsed,
			"used_at": now,
		})
	return result.RowsAffected > 0, result.Error
}

// IncrAttempts 累加校验失败次数。
//
// 用 UpdateColumn 走原子自增，避免「读出来 +1 再写回去」在并发下丢计数；
// 代价是 updated_time 不会跟着变，对本表无所谓。
func (r *VerificationCodeRepository) IncrAttempts(ctx context.Context, id model.ID) error {
	var entity model.VerificationCode
	return r.db.WithContext(ctx).
		Model(&entity).
		Where("id = ?", id).
		UpdateColumn("attempts", gorm.Expr("attempts + 1")).
		Error
}
