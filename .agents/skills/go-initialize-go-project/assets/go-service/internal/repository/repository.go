// Package repository 提供基于 GORM 的泛型数据访问仓储。
package repository

import (
	"context"
	"errors"
	"regexp"
	"strings"
	"sync"

	"gorm.io/gorm"

	"project_id/internal/model"
	"project_id/internal/pkg/query"
)

// Scope 是对查询追加约束的函数。
type Scope = func(*gorm.DB) *gorm.DB

// columnSet 惰性缓存实体可排序列名集合。
type columnSet struct {
	// once 保证列名集合只解析一次。
	once sync.Once
	// cols 是解析后的可排序列名集合。
	cols map[string]struct{}
}

// Repository 是对单个实体提供读写能力的泛型仓储。
type Repository[T model.Entity] struct {
	// db 是底层数据库会话。
	db *gorm.DB
	// set 是惰性缓存的可排序列名集合。
	set *columnSet
}

// New 为实体类型创建仓储。
func New[T model.Entity](db *gorm.DB) *Repository[T] {
	return &Repository[T]{db: db, set: &columnSet{}}
}

// DB 返回仓储持有的数据库会话。
func (r *Repository[T]) DB() *gorm.DB {
	return r.db
}

// WithDB 用给定会话派生新仓储，便于在事务中复用同一套访问方法。
func (r *Repository[T]) WithDB(db *gorm.DB) *Repository[T] {
	return &Repository[T]{db: db, set: r.set}
}

// session 返回绑定当前实体表的查询会话。
func (r *Repository[T]) session(ctx context.Context) *gorm.DB {
	var entity T
	return r.db.WithContext(ctx).Model(&entity)
}

// orderableColumns 返回实体允许作为排序依据的列名集合。
func (r *Repository[T]) orderableColumns() map[string]struct{} {
	r.set.once.Do(func() {
		columns := make(map[string]struct{})
		var entity T
		statement := &gorm.Statement{DB: r.db}
		if err := statement.Parse(&entity); err == nil {
			for _, field := range statement.Schema.Fields {
				columns[field.DBName] = struct{}{}
				columns[field.Name] = struct{}{}
			}
		}
		for _, fallback := range []string{"id", "created_time", "updated_time"} {
			columns[fallback] = struct{}{}
		}
		r.set.cols = columns
	})
	return r.set.cols
}

// Create 插入单个实体。
func (r *Repository[T]) Create(ctx context.Context, entity *T) error {
	return r.session(ctx).Create(entity).Error
}

// CreateBatch 批量插入实体。
func (r *Repository[T]) CreateBatch(ctx context.Context, entities []T) error {
	if len(entities) == 0 {
		return nil
	}
	return r.session(ctx).Create(&entities).Error
}

// Update 保存实体的全部字段。
func (r *Repository[T]) Update(ctx context.Context, entity *T) error {
	return r.session(ctx).Save(entity).Error
}

// UpdateFields 按主键更新指定字段。
func (r *Repository[T]) UpdateFields(ctx context.Context, id model.ID, fields map[string]any) error {
	if len(fields) == 0 {
		return nil
	}
	return r.session(ctx).Where("id = ?", id).Updates(fields).Error
}

// UpdateBy 按条件更新指定字段，返回受影响行数。
func (r *Repository[T]) UpdateBy(ctx context.Context, fields map[string]any, scopes ...Scope) (int64, error) {
	if len(fields) == 0 {
		return 0, nil
	}
	result := r.applyScopes(r.session(ctx), scopes).Updates(fields)
	return result.RowsAffected, result.Error
}

// Delete 按主键软删除实体。
func (r *Repository[T]) Delete(ctx context.Context, id model.ID) error {
	return r.session(ctx).Where("id = ?", id).Delete(new(T)).Error
}

// DeleteBatch 按主键批量软删除实体。
func (r *Repository[T]) DeleteBatch(ctx context.Context, ids []model.ID) error {
	if len(ids) == 0 {
		return nil
	}
	return r.session(ctx).Where("id IN ?", ids).Delete(new(T)).Error
}

// DeleteBy 按条件软删除实体，返回受影响行数。
func (r *Repository[T]) DeleteBy(ctx context.Context, scopes ...Scope) (int64, error) {
	result := r.applyScopes(r.session(ctx), scopes).Delete(new(T))
	return result.RowsAffected, result.Error
}

// Transaction 在事务中执行回调，回调返回错误时回滚。
func (r *Repository[T]) Transaction(ctx context.Context, fn func(tx *Repository[T]) error) error {
	return r.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		return fn(r.WithDB(tx))
	})
}

// TransactionDB 在事务中执行带原始会话的回调，便于跨仓储协作。
func (r *Repository[T]) TransactionDB(ctx context.Context, fn func(tx *gorm.DB) error) error {
	return r.db.WithContext(ctx).Transaction(fn)
}

// GetByID 按主键查询实体，不存在时返回 (nil, nil)。
//
// 「不存在」是正常的业务分支而不是错误：登录、刷新令牌、鉴权加载账号、
// 按接收目标定位账号都要把它翻译成各自的可读错误码（401 / 404），
// 若在这里把 gorm.ErrRecordNotFound 原样抛出，调用方漏写一次判断就会
// 把「账号不存在」误报成 500 内部错误。真正的查询失败仍然原样返回。
func (r *Repository[T]) GetByID(ctx context.Context, id model.ID) (*T, error) {
	var entity T
	if err := r.session(ctx).Where("id = ?", id).Take(&entity).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, nil
		}
		return nil, err
	}
	return &entity, nil
}

// Get 按条件查询单个实体，不存在时返回 (nil, nil)。
//
// 与 GetByID 同一约定：调用方按「先判空、再给出业务错误」组织逻辑，
// 因此「查不到」必须与「查询出错」区分开。
func (r *Repository[T]) Get(ctx context.Context, scopes ...Scope) (*T, error) {
	var entity T
	if err := r.applyScopes(r.session(ctx), scopes).Take(&entity).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, nil
		}
		return nil, err
	}
	return &entity, nil
}

// List 按条件查询实体列表。
func (r *Repository[T]) List(ctx context.Context, scopes ...Scope) ([]T, error) {
	entities := make([]T, 0)
	if err := r.applyScopes(r.session(ctx), scopes).Find(&entities).Error; err != nil {
		return nil, err
	}
	return entities, nil
}

// Page 按分页条件查询实体列表与总数。
func (r *Repository[T]) Page(ctx context.Context, page *query.Page, scopes ...Scope) ([]T, int64, error) {
	if page == nil {
		page = &query.Page{}
	}
	page.Normalize()
	if err := page.ValidateOrderBy(r.columnNames()); err != nil {
		return nil, 0, err
	}
	total, err := r.Count(ctx, scopes...)
	if err != nil {
		return nil, 0, err
	}
	entities := make([]T, 0)
	session := r.applyScopes(r.session(ctx), scopes)
	clause := page.OrderClause("id")
	if clause != "" {
		session = session.Order(clause)
	}
	if err := session.Offset(page.Offset()).Limit(page.Size).Find(&entities).Error; err != nil {
		return nil, 0, err
	}
	return entities, total, nil
}

// Count 统计满足条件的实体数量。
func (r *Repository[T]) Count(ctx context.Context, scopes ...Scope) (int64, error) {
	var total int64
	if err := r.applyScopes(r.session(ctx), scopes).Count(&total).Error; err != nil {
		return 0, err
	}
	return total, nil
}

// Exists 判断是否存在满足条件的实体。
func (r *Repository[T]) Exists(ctx context.Context, scopes ...Scope) (bool, error) {
	total, err := r.Count(ctx, scopes...)
	if err != nil {
		return false, err
	}
	return total > 0, nil
}

// columnNames 返回用于排序校验的列名切片。
func (r *Repository[T]) columnNames() []string {
	columns := r.orderableColumns()
	result := make([]string, 0, len(columns))
	for column := range columns {
		result = append(result, column)
	}
	return result
}

// applyScopes 依次应用查询约束。
func (r *Repository[T]) applyScopes(session *gorm.DB, scopes []Scope) *gorm.DB {
	for _, scope := range scopes {
		if scope == nil {
			continue
		}
		session = scope(session)
	}
	return session
}

// WhereID 追加主键等值条件。
func WhereID(id model.ID) Scope {
	return func(db *gorm.DB) *gorm.DB { return db.Where("id = ?", id) }
}

// WhereIDs 追加主键集合条件。
func WhereIDs(ids []model.ID) Scope {
	return func(db *gorm.DB) *gorm.DB { return db.Where("id IN ?", ids) }
}

// WhereEq 追加列等值条件；列名必须通过安全校验。
func WhereEq(column string, value any) Scope {
	return func(db *gorm.DB) *gorm.DB {
		if !IsSafeColumn(column) {
			return db
		}
		return db.Where(column+" = ?", value)
	}
}

// WhereLike 追加列模糊匹配条件；列名必须通过安全校验。
func WhereLike(column string, pattern string) Scope {
	return func(db *gorm.DB) *gorm.DB {
		if !IsSafeColumn(column) {
			return db
		}
		return db.Where(column+" LIKE ?", pattern)
	}
}

// OrderBy 追加排序子句；列名必须通过安全校验。
func OrderBy(column string, desc bool) Scope {
	return func(db *gorm.DB) *gorm.DB {
		if !IsSafeColumn(column) {
			return db
		}
		if desc {
			return db.Order(column + " DESC")
		}
		return db.Order(column + " ASC")
	}
}

// safeColumnPattern 只允许字母、数字、下划线与点分隔的限定列名。
var safeColumnPattern = regexp.MustCompile(`^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*$`)

// IsSafeColumn 判断列名是否可以安全拼接到查询语句中。
func IsSafeColumn(column string) bool {
	trimmed := strings.TrimSpace(column)
	if trimmed == "" {
		return false
	}
	return safeColumnPattern.MatchString(trimmed)
}
