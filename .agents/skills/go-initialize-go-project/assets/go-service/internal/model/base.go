// Package model 定义持久化实体的公共基础结构与标识类型。
package model

import (
	"database/sql/driver"
	"encoding/json"
	"fmt"
	"strconv"

	"gorm.io/gorm"
	"gorm.io/plugin/soft_delete"

	"project_id/internal/pkg/snowflake"
)

// ID 是使用雪花算法生成的主键类型。
type ID int64

// MarshalJSON 把标识输出为带引号的字符串，避免前端精度丢失。
func (id ID) MarshalJSON() ([]byte, error) {
	return json.Marshal(strconv.FormatInt(int64(id), 10))
}

// UnmarshalJSON 接受字符串或数字形式的标识。
func (id *ID) UnmarshalJSON(data []byte) error {
	if len(data) > 1 && data[0] == '"' {
		var text string
		if err := json.Unmarshal(data, &text); err != nil {
			return err
		}
		value, err := strconv.ParseInt(text, 10, 64)
		if err != nil {
			return fmt.Errorf("model: 无法解析标识 %q: %w", text, err)
		}
		*id = ID(value)
		return nil
	}
	var value int64
	if err := json.Unmarshal(data, &value); err != nil {
		return err
	}
	*id = ID(value)
	return nil
}

// String 返回标识的十进制文本形式。
func (id ID) String() string {
	return strconv.FormatInt(int64(id), 10)
}

// Value 实现 driver.Valuer。
func (id ID) Value() (driver.Value, error) {
	return int64(id), nil
}

// Scan 实现 sql.Scanner。
func (id *ID) Scan(value any) error {
	switch typed := value.(type) {
	case nil:
		*id = 0
		return nil
	case int64:
		*id = ID(typed)
		return nil
	case []byte:
		parsed, err := strconv.ParseInt(string(typed), 10, 64)
		if err != nil {
			return err
		}
		*id = ID(parsed)
		return nil
	case string:
		parsed, err := strconv.ParseInt(typed, 10, 64)
		if err != nil {
			return err
		}
		*id = ID(parsed)
		return nil
	default:
		return fmt.Errorf("model: 无法把 %T 转换为标识", value)
	}
}

// Entity 是全部持久化实体都必须满足的约束。
//
// 只要求值接收者方法：Repository[T] 的 T 是实体值类型（如 model.Account），
// 而 Base.SetID 是指针接收者，写进接口会让任何值类型都不满足约束。
// 主键写入由 BeforeCreate 与 GORM 自身完成，不需要接口暴露 setter。
type Entity interface {
	// TableName 返回实体对应的表名。
	TableName() string
	// GetID 返回实体主键。
	GetID() ID
}

// Base 是持久化实体的公共字段集合。
//
// 三个时间字段**统一以 unix 秒存储与下发**，类型分别是 Timestamp（自定义
// int64）与 soft_delete.DeletedAt（也是 int64 秒）。理由与精度取舍见
// timestamp.go 的 Timestamp 文档；一句话：避免 time.Time 在不同驱动下
// 精度不一致（MySQL datetime(3) 毫秒 / sqlite 纳秒）导致同一个接口
// 在 dev 与 prod 返回位数不同的小数秒。
//
// autoCreateTime / autoUpdateTime **故意不带参数**：字段类型是 int64 的
// 命名类型，GORM 判定 DataType = Int，无参即落到 UnixSecond
// （gorm/schema/field.go:300、:312），写入时执行 data.Unix()。
// 改成 autoCreateTime:nano 或 :milli 会立刻破坏「全项目用秒」的约定。
type Base struct {
	// ID 是雪花主键；autoIncrement 必须显式关闭。
	ID ID `gorm:"primaryKey;autoIncrement:false;column:id" json:"id"`
	// CreatedTime 是创建时间（unix 秒）。
	CreatedTime Timestamp `gorm:"autoCreateTime;column:created_time" json:"created_time"`
	// UpdatedTime 是更新时间（unix 秒）。
	UpdatedTime Timestamp `gorm:"autoUpdateTime;column:updated_time" json:"updated_time"`
	// DeletedTime 是软删除时间戳（unix 秒），0 表示未删除。
	DeletedTime soft_delete.DeletedAt `gorm:"column:deleted_time;softDelete:unix" json:"-"`
}

// GetID 返回实体主键。
func (b Base) GetID() ID { return b.ID }

// SetID 写入实体主键。
func (b *Base) SetID(id ID) { b.ID = id }

// BeforeCreate 在插入前为缺失主键的实体分配雪花标识。
func (b *Base) BeforeCreate(_ *gorm.DB) error {
	if b.ID != 0 {
		return nil
	}
	next, err := snowflake.Next()
	if err != nil {
		return err
	}
	b.ID = ID(next)
	return nil
}
