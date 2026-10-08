package service

import "strings"

// 组织域当前只负责「账号默认组织」的命名与初始化。
//
// 后续扩展（账号加入他人组织、成员管理、邀请）时新增 OrgService 放在本文件，
// 关联关系落到 org_user 表，model.Org 不需要改动。
//
// 默认组织名后缀
const defaultOrgNameSuffix = "的组织"

// DefaultOrgName 生成账号默认组织名。
//
// 优先用昵称（注册时昵称缺省会回落为用户名，所以这里拿到的一般不为空），
// 两者都为空时用「我的组织」兜底，避免落一个空名字进库。
func DefaultOrgName(nickname, username string) string {
	name := strings.TrimSpace(nickname)
	if name == "" {
		name = strings.TrimSpace(username)
	}
	if name == "" {
		return "我的组织"
	}
	return name + defaultOrgNameSuffix
}
