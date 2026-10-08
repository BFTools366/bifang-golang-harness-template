package middleware

import (
	"strconv"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"golang.org/x/time/rate"

	"project_id/internal/apperr"
	"project_id/internal/config"
)

// gcInterval 是访问记录回收的间隔。
const gcInterval = time.Minute

// visitor 保存单个客户端的限流状态。
type visitor struct {
	// mu 保护 limiter 与 lastSeen 的并发访问。
	mu sync.Mutex
	// limiter 是该客户端专属的令牌桶。
	limiter *rate.Limiter
	// lastSeen 记录该客户端最近一次请求时间。
	lastSeen time.Time
}

// limiterStore 保存全部客户端限流状态。
type limiterStore struct {
	// mu 保护 visitors 的并发访问。
	mu sync.Mutex
	// visitors 按客户端键保存限流状态。
	visitors map[string]*visitor
	// rps 是每秒允许的请求数。
	rps float64
	// burst 是允许的瞬时突发请求数。
	burst int
}

// RateLimit 按客户端限制请求速率，超限时返回统一错误。
func RateLimit(cfg config.RateLimit) gin.HandlerFunc {
	rps := cfg.RPS
	if rps <= 0 {
		rps = 1
	}
	burst := cfg.Burst
	if burst <= 0 {
		burst = 1
	}
	store := &limiterStore{
		visitors: make(map[string]*visitor),
		rps:      rps,
		burst:    burst,
	}
	startGC(store)

	return func(c *gin.Context) {
		item := store.get(c.ClientIP())
		allowed, remaining := item.allow(store.rps, store.burst)
		c.Writer.Header().Set("X-RateLimit-Limit", strconv.Itoa(store.burst))
		c.Writer.Header().Set("X-RateLimit-Remaining", strconv.Itoa(remaining))
		if !allowed {
			panic(apperr.ErrTooManyRequests)
		}
		c.Next()
	}
}

// get 返回客户端对应的限流状态，不存在时创建。
func (s *limiterStore) get(key string) *visitor {
	s.mu.Lock()
	defer s.mu.Unlock()
	item, ok := s.visitors[key]
	if !ok {
		item = &visitor{limiter: rate.NewLimiter(rate.Limit(s.rps), s.burst)}
		s.visitors[key] = item
	}
	item.lastSeen = time.Now()
	return item
}

// allow 判断当前请求是否放行，并返回剩余可用额度。
func (v *visitor) allow(rps float64, burst int) (bool, int) {
	v.mu.Lock()
	defer v.mu.Unlock()
	allowed := v.limiter.Allow()
	remaining := int(v.limiter.Tokens())
	if remaining < 0 {
		remaining = 0
	}
	if remaining > burst {
		remaining = burst
	}
	return allowed, remaining
}

// gcLocked 回收长时间未访问的客户端状态。
func (s *limiterStore) gcLocked() {
	cutoff := time.Now().Add(-gcInterval * 3)
	for key, item := range s.visitors {
		item.mu.Lock()
		stale := item.lastSeen.Before(cutoff)
		item.mu.Unlock()
		if stale {
			delete(s.visitors, key)
		}
	}
}

// startGC 启动访问记录回收协程，直到进程结束。
func startGC(store *limiterStore) {
	ticker := time.NewTicker(gcInterval)
	go func() {
		for range ticker.C {
			store.mu.Lock()
			store.gcLocked()
			store.mu.Unlock()
		}
	}()
}
