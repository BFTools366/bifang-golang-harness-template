package hash_test

import (
	"testing"

	"project_id/internal/pkg/hash"
)

// TestPasswordHashAndVerify 覆盖哈希与校验的正反向路径，含非法哈希。
func TestPasswordHashAndVerify(t *testing.T) {
	hashed, err := hash.Password("demo1234")
	if err != nil {
		t.Fatalf("生成哈希失败: %v", err)
	}
	if hashed == "demo1234" {
		t.Fatal("哈希结果不应等于明文")
	}
	if !hash.VerifyPassword(hashed, "demo1234") {
		t.Fatal("正确密码校验失败")
	}
	if hash.VerifyPassword(hashed, "demo12345") {
		t.Fatal("错误密码不应通过校验")
	}
	if hash.VerifyPassword("not-a-hash", "demo1234") {
		t.Fatal("非法哈希不应通过校验")
	}
}

// TestPasswordHashIsSalted 验证相同密码两次哈希因随机盐而不同。
func TestPasswordHashIsSalted(t *testing.T) {
	first, _ := hash.Password("demo1234")
	second, _ := hash.Password("demo1234")

	if first == second {
		t.Fatal("相同密码两次哈希应因随机盐而不同")
	}
}
