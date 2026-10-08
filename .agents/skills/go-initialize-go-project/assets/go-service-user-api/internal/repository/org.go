package repository

import (
	"context"

	"project_id/internal/model"

	"gorm.io/gorm"
)

// OrgRepository 组织仓储，在泛型 CRUD 基础上追加组织域专属查询。
type OrgRepository struct {
	*Repository[model.Org]
	db *gorm.DB
}

// NewOrgRepository 创建组织仓储
func NewOrgRepository(db *gorm.DB) *OrgRepository {
	return &OrgRepository{
		Repository: New[model.Org](db),
		db:         db,
	}
}

// FindDefaultByOwner 查询账号的默认组织，未找到返回 (nil, nil)
func (r *OrgRepository) FindDefaultByOwner(ctx context.Context, ownerID model.ID) (*model.Org, error) {
	return r.Get(ctx, WhereEq("owner_id", ownerID), WhereEq("is_default", true))
}

// ListByOwner 查询账号拥有的全部组织
func (r *OrgRepository) ListByOwner(ctx context.Context, ownerID model.ID) ([]model.Org, error) {
	return r.List(ctx, WhereEq("owner_id", ownerID))
}
