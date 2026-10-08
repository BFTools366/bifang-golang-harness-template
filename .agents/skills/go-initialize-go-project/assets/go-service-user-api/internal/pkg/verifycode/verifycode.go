// Package verifycode 负责验证码的生成、哈希与比对。
//
// 只做纯计算，不碰数据库也不碰网络 —— 这样它既能在 service 里用，
// 也能被测试直接调用，不需要任何依赖。
package verifycode

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"fmt"
	"math/big"
)

// DefaultLength 默认验证码位数
const DefaultLength = 6

// maxLength 位数上限。位数再大也不会更安全（真正的防线是有效期与次数限制），
// 只会让用户更难输入。
const maxLength = 10

// Generate 生成 length 位纯数字验证码。
//
// 用 crypto/rand 而不是 math/rand：后者的默认源可预测，
// 攻击者拿到几个历史验证码就能推出后续值，等于绕过整个验证环节。
//
// 返回值用 %0*d 补齐前导零，保证「000123」这种码也是 length 位。
func Generate(length int) (string, error) {
	if length <= 0 {
		length = DefaultLength
	}
	if length > maxLength {
		return "", fmt.Errorf("验证码位数 %d 超出上限 %d", length, maxLength)
	}

	// 上界是 10^length，rand.Int 返回 [0, 上界) 的均匀分布整数
	upper := new(big.Int).Exp(big.NewInt(10), big.NewInt(int64(length)), nil)
	n, err := rand.Int(rand.Reader, upper)
	if err != nil {
		return "", fmt.Errorf("生成随机验证码失败: %w", err)
	}
	return fmt.Sprintf("%0*d", length, n), nil
}

// Hash 计算验证码的存储哈希。
//
// 把 target 一起拌进去，让同一个码发给不同目标时产生不同哈希 ——
// 这样即使数据库被拖走，也无法把一个目标的哈希拿去撞另一个目标。
//
// 必须清楚它的边界：6 位数字只有 10^6 种取值，拿到哈希后离线爆破是瞬间的事。
// 存哈希的目的是让数据库导出、慢查询日志、备份文件这些渠道拿不到明文，
// **不是**用来替代有效期 / 一次性消费 / 次数限制。
func Hash(code, target string) string {
	sum := sha256.Sum256([]byte(target + ":" + code))
	return hex.EncodeToString(sum[:])
}

// Match 恒定时间比对验证码哈希，避免通过响应耗时侧信道逐位猜测。
//
// 注意 subtle.ConstantTimeCompare 要求两个切片等长，长度不同会直接返回 0，
// 所以这里先判长度再比对，不会 panic。
func Match(hash, code, target string) bool {
	expected := Hash(code, target)
	return subtle.ConstantTimeCompare([]byte(expected), []byte(hash)) == 1
}
