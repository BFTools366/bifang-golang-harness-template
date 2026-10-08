// Package snowflake 提供全局唯一的雪花 ID 生成器。
package snowflake

import (
	"errors"
	"hash/fnv"
	"os"
	"sync"

	"github.com/bwmarrin/snowflake"
)

const (
	// MaxNodeID 是雪花节点号的上界。
	MaxNodeID int64 = 1023
	// AutoNodeID 表示按主机名自动推导节点号。
	AutoNodeID int64 = -1
)

// ErrNotInitialized 表示生成器尚未初始化就调用了 Next。
var ErrNotInitialized = errors.New("snowflake: 生成器尚未初始化")

// mu 保护 gen 与 nodeID 的并发读写。
var (
	mu  sync.RWMutex
	gen *snowflake.Node
	// nodeID 保存当前实际生效的节点号。
	nodeID int64 = AutoNodeID
)

// Setup 用给定节点号初始化生成器；传入 AutoNodeID 时按主机名推导。
func Setup(id int64) error {
	resolved, err := resolveNodeID(id)
	if err != nil {
		return err
	}
	node, err := snowflake.NewNode(resolved)
	if err != nil {
		return err
	}
	mu.Lock()
	defer mu.Unlock()
	gen = node
	nodeID = resolved
	return nil
}

// NodeID 返回当前实际生效的节点号；尚未初始化时返回 AutoNodeID。
func NodeID() int64 {
	mu.RLock()
	defer mu.RUnlock()
	return nodeID
}

// Next 生成下一个雪花 ID；生成器尚未初始化时返回错误。
func Next() (int64, error) {
	mu.RLock()
	node := gen
	mu.RUnlock()
	if node == nil {
		return 0, ErrNotInitialized
	}
	return node.Generate().Int64(), nil
}

// resolveNodeID 校验显式节点号，或按主机名稳定推导一个合法节点号。
func resolveNodeID(id int64) (int64, error) {
	if id != AutoNodeID {
		if id < 0 || id > MaxNodeID {
			return 0, errors.New("snowflake: 节点号超出允许范围")
		}
		return id, nil
	}
	return autoNodeID()
}

// autoNodeID 用主机名的 FNV-1a 哈希对节点号上界取模，保证同一主机稳定。
func autoNodeID() (int64, error) {
	host, err := os.Hostname()
	if err != nil {
		return 0, err
	}
	hasher := fnv.New32a()
	if _, err := hasher.Write([]byte(host)); err != nil {
		return 0, err
	}
	return int64(hasher.Sum32()) % (MaxNodeID + 1), nil
}
