// Package hash 提供密码哈希相关工具。
package hash

import "golang.org/x/crypto/bcrypt"

// DefaultCost bcrypt 计算强度
const DefaultCost = bcrypt.DefaultCost

// Password 生成密码哈希
func Password(plain string) (string, error) {
	hashed, err := bcrypt.GenerateFromPassword([]byte(plain), DefaultCost)
	if err != nil {
		return "", err
	}
	return string(hashed), nil
}

// VerifyPassword 校验明文密码与哈希是否匹配
func VerifyPassword(hashed, plain string) bool {
	return bcrypt.CompareHashAndPassword([]byte(hashed), []byte(plain)) == nil
}
