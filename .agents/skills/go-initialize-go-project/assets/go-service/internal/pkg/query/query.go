// Package query 提供分页与排序列名校验的通用契约。
package query

import (
	"fmt"
	"regexp"
	"strings"
)

const (
	// DefaultCurrent 是未指定时使用的默认页码。
	DefaultCurrent = 1
	// DefaultSize 是未指定时使用的默认每页条数。
	DefaultSize = 10
	// MaxSize 是每页条数的上界。
	MaxSize = 200
	// MaxCurrent 是页码的上界。
	MaxCurrent = 1_000_000
)

// safeColumn 只允许字母、数字、下划线与点分隔的限定列名，避免排序注入。
var safeColumn = regexp.MustCompile(`^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*$`)

// Page 描述一次分页请求。
type Page struct {
	// Current 是当前页码，从 1 开始。
	Current int `form:"current" json:"current"`
	// Size 是每页条数。
	Size int `form:"size" json:"size"`
	// OrderBy 是排序字段名。
	OrderBy string `form:"order_by" json:"order_by"`
	// Desc 表示是否按降序排列。
	Desc bool `form:"desc" json:"desc"`
}

// Normalize 把越界的页码与每页条数收敛到合法范围内。
func (p *Page) Normalize() {
	if p.Current < 1 {
		p.Current = DefaultCurrent
	}
	if p.Current > MaxCurrent {
		p.Current = MaxCurrent
	}
	if p.Size < 1 {
		p.Size = DefaultSize
	}
	if p.Size > MaxSize {
		p.Size = MaxSize
	}
	p.OrderBy = strings.TrimSpace(p.OrderBy)
}

// ValidateOrderBy 校验排序列名是否在允许集合内，空值表示使用默认排序。
func (p *Page) ValidateOrderBy(columns []string) error {
	if p.OrderBy == "" {
		return nil
	}
	if !safeColumn.MatchString(p.OrderBy) {
		return fmt.Errorf("query: 排序列名不合法：%s", p.OrderBy)
	}
	for _, column := range columns {
		if column == p.OrderBy {
			return nil
		}
	}
	return fmt.Errorf("query: 排序列名不在允许集合内：%s", p.OrderBy)
}

// Offset 返回当前页的偏移量。
func (p *Page) Offset() int {
	page := p
	if page.Current < 1 {
		page = &Page{Current: DefaultCurrent, Size: p.Size}
	}
	size := page.Size
	if size < 1 {
		size = DefaultSize
	}
	return (page.Current - 1) * size
}

// OrderClause 返回可直接拼接的排序子句；未指定排序时返回默认子句。
func (p *Page) OrderClause(defaultColumn string) string {
	column := p.OrderBy
	if column == "" {
		column = defaultColumn
	}
	if column == "" || !safeColumn.MatchString(column) {
		return ""
	}
	if p.Desc {
		return column + " DESC"
	}
	return column + " ASC"
}
