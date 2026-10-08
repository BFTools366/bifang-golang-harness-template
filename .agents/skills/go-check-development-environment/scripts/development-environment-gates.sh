#!/bin/sh
set -eu

# Go 最低版本的唯一事实来源见 docs/GO_WEB_TEMPLATE.md；修改此值时必须同步更新 development-environment-gates.ps1。
MIN_GO_MAJOR=1
MIN_GO_MINOR=26
MIN_GO_PATCH=0
GO_REQUIREMENT='>=1.26.0'
GIT_REQUIREMENT='>=2.36.0'
TEST_MODE=${AFH_TEST_MODE:-0}
MODE=install
INTERFACES=

# 输出稳定的命令入口说明，避免调用方误把只读模式当成首次开发安装模式。
usage() {
    printf '%s\n' "用法：development-environment-gates.sh [--install-missing|--check-only] --interfaces CLI,TUI,MCP,GUI"
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --install-missing) MODE=install ;;
        --check-only) MODE=check ;;
        --interfaces)
            [ "$#" -ge 2 ] || { usage >&2; exit 2; }
            INTERFACES=$2
            shift
            ;;
        --help|-h) usage; exit 0 ;;
        *) printf '未知参数：%s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

PROBE_PATH=${AFH_PREREQ_PATH:-${PATH}}
GO_CHANGED=existing
GIT_CHANGED=existing
GO_BIN_DIR=
GIT_BIN_DIR=
TEMP_DIR=
FISH_TEMP_FILE=
FRESH_VERIFY_FILE=
FRESH_VERIFY_DIR=
LINK_TEMP_DIR=
PROFILE_TEMP_FILE=
PROFILE_SNAPSHOT_FILE=
FRESH_SHELL_STATUS=not-required

# 只清理本进程通过 mktemp 创建的下载目录，不触碰安装目标或用户已有文件。
cleanup() {
    for gate_temp_file in "$FISH_TEMP_FILE" "$FRESH_VERIFY_FILE" "$PROFILE_TEMP_FILE" "$PROFILE_SNAPSHOT_FILE"; do
        [ -n "$gate_temp_file" ] || continue
        if [ -f "$gate_temp_file" ] || [ -L "$gate_temp_file" ]; then rm -f "$gate_temp_file" 2>/dev/null || true; fi
    done
    if [ -n "$LINK_TEMP_DIR" ] && [ -d "$LINK_TEMP_DIR" ] && [ ! -L "$LINK_TEMP_DIR" ]; then
        find "$LINK_TEMP_DIR" -depth -delete 2>/dev/null || true
    fi
    if [ -n "$FRESH_VERIFY_DIR" ] && [ -d "$FRESH_VERIFY_DIR" ] && [ ! -L "$FRESH_VERIFY_DIR" ]; then
        find "$FRESH_VERIFY_DIR" -depth -delete 2>/dev/null || true
    fi
    if [ -n "$TEMP_DIR" ] && [ -d "$TEMP_DIR" ]; then
        find "$TEMP_DIR" -depth -delete 2>/dev/null || true
    fi
}
trap cleanup EXIT HUP INT TERM

# 以稳定退出码终止门禁，让 Agent 能区分缺失、版本、下载和校验失败。
fail() {
    code=$1
    shift
    printf '错误：%s\n' "$*" >&2
    exit "$code"
}

# 探测路径、下载镜像和安装目录覆盖都只允许显式隔离测试使用。
case "$TEST_MODE" in
    0|1) ;;
    *) fail 2 "AFH_TEST_MODE 只接受显式值 1" ;;
esac
for override_name in \
    AFH_PREREQ_PATH AFH_ALLOW_FILE_URLS AFH_GO_DIST_BASE \
    AFH_MANAGED_GOROOT AFH_SKIP_PERSIST_PATH AFH_TEST_HOST_OS AFH_TEST_HOST_ARCH \
    AFH_TEST_SYSTEM_PATH; do
    eval "override_value=\${$override_name-}"
    if [ -n "$override_value" ] && [ "$TEST_MODE" != 1 ]; then
        fail 2 "测试覆盖 $override_name 仅在 AFH_TEST_MODE=1 时允许"
    fi
done

# 生产调用使用各工具的标准当前用户安装根；用户已设置的标准 GOROOT 会被原样尊重。
USER_HOME=${HOME:?必须设置 HOME}
case "$USER_HOME" in
    /*) ;;
    *) fail 24 "HOME 必须是绝对路径" ;;
esac
case "$USER_HOME" in
    *:*) fail 24 "HOME 不能包含 PATH 分隔符冒号" ;;
esac
MANAGED_GOROOT=${GOROOT:-$USER_HOME/.local/go}
MANAGED_GOPATH=${GOPATH:-$USER_HOME/go}
if [ "$TEST_MODE" = 1 ]; then
    MANAGED_GOROOT=${AFH_MANAGED_GOROOT:-$MANAGED_GOROOT}
fi
for managed_path in "$MANAGED_GOROOT" "$MANAGED_GOPATH"; do
    case "$managed_path" in
        /*) ;;
        *) fail 24 "受管安装根必须是绝对路径：$managed_path" ;;
    esac
    case "$managed_path" in
        *:*) fail 24 "受管安装根不能包含 PATH 分隔符冒号：$managed_path" ;;
    esac
done

# 删除 PATH 空段和重复项，永远不把空段解释为当前工作目录。
sanitize_path() {
    input_path=$1
    result_path=
    old_ifs=$IFS
    glob_was_enabled=0
    case $- in
        *f*) ;;
        *) set -f; glob_was_enabled=1 ;;
    esac
    IFS=:
    for path_entry in $input_path; do
        [ -n "$path_entry" ] || continue
        case "$path_entry" in /*) ;; *) continue ;; esac
        case ":$result_path:" in
            *":$path_entry:"*) ;;
            *) [ -n "$result_path" ] && result_path=$result_path:$path_entry || result_path=$path_entry ;;
        esac
    done
    IFS=$old_ifs
    [ "$glob_was_enabled" -eq 0 ] || set +f
    printf '%s\n' "$result_path"
}

PATH=$(sanitize_path "${PATH}")
export PATH
PROBE_PATH=$(sanitize_path "$PROBE_PATH")
FRESH_BASE_PATH=/usr/bin:/bin:/usr/sbin:/sbin
if [ "$TEST_MODE" = 1 ] && [ -n "${AFH_TEST_SYSTEM_PATH:-}" ]; then
    FRESH_BASE_PATH=$AFH_TEST_SYSTEM_PATH
fi
FRESH_BASE_PATH=$(sanitize_path "$FRESH_BASE_PATH")
[ -n "$FRESH_BASE_PATH" ] || fail 24 "新登录会话的系统 PATH 基线为空"

normalized_interfaces=$(printf '%s' "$INTERFACES" | tr '[:lower:]' '[:upper:]' | tr -d ' ')
for interface in $(printf '%s' "$normalized_interfaces" | tr ',' ' '); do
    case "$interface" in
        CLI|TUI|MCP|GUI) ;;
        *) printf '不支持的接口：%s\n' "$interface" >&2; usage >&2; exit 2 ;;
    esac
done

# 仅在门禁探测路径中解析工具，隔离测试可因此隐藏机器已有环境。
find_tool() {
    tool_name=$1
    old_ifs=$IFS
    glob_was_enabled=0
    case $- in
        *f*) ;;
        *) set -f; glob_was_enabled=1 ;;
    esac
    IFS=:
    for tool_dir in $PROBE_PATH; do
        [ -n "$tool_dir" ] || continue
        if [ -x "$tool_dir/$tool_name" ] && [ ! -d "$tool_dir/$tool_name" ]; then
            printf '%s\n' "$tool_dir/$tool_name"
            IFS=$old_ifs
            [ "$glob_was_enabled" -eq 0 ] || set +f
            return 0
        fi
    done
    IFS=$old_ifs
    [ "$glob_was_enabled" -eq 0 ] || set +f
    return 1
}

# 下载官方 HTTPS 制品；file URL 只在显式测试开关下用于隔离测试夹具。
download() {
    source_url=$1
    destination=$2
    case "$source_url" in
        https://*) curl --proto '=https' --tlsv1.2 -fsSL "$source_url" -o "$destination" ;;
        file://*)
            [ "$TEST_MODE" = 1 ] && [ "${AFH_ALLOW_FILE_URLS:-0}" = 1 ] || fail 24 "file URL 已禁用"
            curl -fsSL "$source_url" -o "$destination"
            ;;
        *) fail 24 "不支持的下载 URL 协议：$source_url" ;;
    esac
}

# 验证 go 为稳定发布版，并用 go env 复核标准根；低于 1.26.0 时返回升级需求。
validate_go() {
    go_path=$1
    go_text=$("$go_path" version 2>/dev/null) || fail 23 "Go 探测失败"
    [ "$(printf '%s\n' "$go_text" | awk 'END { print NR }')" -eq 1 ] || fail 23 "go version 必须返回唯一一行"
    go_release=$(printf '%s\n' "$go_text" | awk '{ print $3 }')
    case "$go_release" in
        go[0-9]*) ;;
        *) fail 23 "现有 Go 不是可识别的稳定发布版：$go_text" ;;
    esac
    go_release=${go_release#go}
    case "$go_release" in
        *-*|*+*) fail 23 "现有 Go 不是可识别的稳定发布版：$go_text" ;;
        *.*|*.*.*) ;;
        *) fail 23 "无法识别 Go 发布版本：$go_text" ;;
    esac
    case "$go_release" in
        *[!0-9.]*) fail 23 "无法识别 Go 发布版本：$go_text" ;;
    esac
    go_major=$(printf '%s\n' "$go_release" | awk -F. '{ print $1 }')
    go_minor=$(printf '%s\n' "$go_release" | awk -F. '{ print $2 }')
    go_patch=$(printf '%s\n' "$go_release" | awk -F. '{ print ($3 == "" ? 0 : $3) }')
    case "$go_major:$go_minor:$go_patch" in
        *[!0-9:]*|::*|*::|*::*:*) fail 23 "无法识别 Go 发布版本：$go_text" ;;
    esac
    go_env=$(PATH=$PROBE_PATH${PATH:+:$PATH} "$go_path" env GOROOT GOPATH GOMODCACHE 2>/dev/null) || fail 23 "go env 探测失败"
    [ "$(printf '%s\n' "$go_env" | awk 'END { print NR }')" -eq 3 ] || fail 23 "go env 未返回 GOROOT/GOPATH/GOMODCACHE 三个值"
    GO_ROOT=$(printf '%s\n' "$go_env" | sed -n '1p')
    GO_PATH_DIR=$(printf '%s\n' "$go_env" | sed -n '2p')
    GO_MOD_CACHE=$(printf '%s\n' "$go_env" | sed -n '3p')
    for go_env_value in "$GO_ROOT" "$GO_PATH_DIR" "$GO_MOD_CACHE"; do
        case "$go_env_value" in
            /*) ;;
            *) fail 23 "go env 返回的路径必须是绝对路径：$go_env_value" ;;
        esac
        case "$go_env_value" in
            *:*) fail 23 "go env 返回的路径不能包含 PATH 分隔符冒号：$go_env_value" ;;
        esac
    done
    GO_VERSION=$go_text
    GO_STATUS=passed
    if [ "$go_major" -lt "$MIN_GO_MAJOR" ] || {
        [ "$go_major" -eq "$MIN_GO_MAJOR" ] && {
            [ "$go_minor" -lt "$MIN_GO_MINOR" ] || {
                [ "$go_minor" -eq "$MIN_GO_MINOR" ] && [ "$go_patch" -lt "$MIN_GO_PATCH" ];
            };
        };
    }; then
        GO_STATUS=upgrade-required
    fi
}

# Git 是所有初始化路径的基础工具；低于 2.36.0 时返回升级需求。
validate_git() {
    git_path=$1
    git_text=$("$git_path" --version 2>/dev/null) || fail 29 "Git 探测失败"
    git_release=$(printf '%s\n' "$git_text" | awk '{print $3}')
    git_major=$(printf '%s\n' "$git_release" | awk -F. '{print $1}')
    git_minor=$(printf '%s\n' "$git_release" | awk -F. '{print $2}')
    git_patch=$(printf '%s\n' "$git_release" | awk -F. '{print $3}')
    case "$git_major:$git_minor:$git_patch" in
        *[!0-9:]*|::*|*::|*::*:*) fail 29 "现有 Git 不是可识别的稳定发布版：$git_text" ;;
    esac
    git_base="$git_major.$git_minor.$git_patch"
    if [ "$git_release" != "$git_base" ]; then
        git_windows_prefix="${git_base}.windows."
        case "$git_release" in
            "$git_windows_prefix"*)
                git_windows_serial=${git_release#"$git_windows_prefix"}
                case "$git_windows_serial" in
                    ''|*[!0-9]*) fail 29 "现有 Git 不是可识别的稳定发布版：$git_text" ;;
                esac
                ;;
            *) fail 29 "现有 Git 不是可识别的稳定发布版：$git_text" ;;
        esac
    fi
    GIT_VERSION=$git_text
    if [ "$git_major" -gt 2 ] || { [ "$git_major" -eq 2 ] && [ "$git_minor" -ge 36 ]; }; then
        GIT_STATUS=passed
    else
        GIT_STATUS=upgrade-required
    fi
}

# Linux 包管理器需要提权时只使用既有 sudo；不下载或安装新的包管理器。
run_git_package_manager() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
        return
    fi
    sudo_path=$(find_tool sudo 2>/dev/null || true)
    [ -n "$sudo_path" ] || fail 29 "安装 Git 需要既有 sudo 或管理员权限"
    "$sudo_path" "$@"
}

# 只通过宿主已有的受管包管理器安装或升级 Git，完成后由主流程重新探测。
install_git() {
    requested_change=$1
    git_host_os=$(uname -s 2>/dev/null) || fail 29 "无法为 Git 安装探测操作系统"
    case "$git_host_os" in
        Darwin)
            brew_path=$(find_tool brew 2>/dev/null || true)
            if [ -z "$brew_path" ]; then
                for brew_candidate in /opt/homebrew/bin/brew /usr/local/bin/brew; do
                    if [ -x "$brew_candidate" ] && [ ! -d "$brew_candidate" ]; then
                        brew_path=$brew_candidate
                        break
                    fi
                done
            fi
            [ -n "$brew_path" ] || fail 29 "macOS 安装 Git 需要既有 Homebrew；门禁不会自动安装 Homebrew"
            printf '正在通过既有 Homebrew 安装或升级 Git。\n' >&2
            "$brew_path" install git || fail 29 "Homebrew 安装 Git 失败"
            brew_prefix=$($brew_path --prefix 2>/dev/null || true)
            if [ -n "$brew_prefix" ] && [ -d "$brew_prefix/bin" ]; then
                GIT_BIN_DIR=$brew_prefix/bin
                prepend_probe_path "$brew_prefix/bin"
            fi
            ;;
        Linux)
            git_manager=
            for manager_name in apt-get dnf yum zypper apk pacman; do
                manager_path=$(find_tool "$manager_name" 2>/dev/null || true)
                if [ -n "$manager_path" ]; then
                    git_manager=$manager_name
                    break
                fi
            done
            [ -n "$git_manager" ] || fail 29 "Linux 安装 Git 需要受支持的既有系统包管理器（apt-get/dnf/yum/zypper/apk/pacman）"
            printf '正在通过既有 %s 安装或升级 Git。\n' "$git_manager" >&2
            case "$git_manager" in
                apt-get)
                    run_git_package_manager "$manager_path" update || fail 29 "apt-get 更新软件包索引失败"
                    run_git_package_manager "$manager_path" install -y git || fail 29 "apt-get 安装 Git 失败"
                    ;;
                dnf|yum) run_git_package_manager "$manager_path" install -y git || fail 29 "$git_manager 安装 Git 失败" ;;
                zypper) run_git_package_manager "$manager_path" --non-interactive install git || fail 29 "zypper 安装 Git 失败" ;;
                apk) run_git_package_manager "$manager_path" add --no-cache git || fail 29 "apk 安装 Git 失败" ;;
                pacman) run_git_package_manager "$manager_path" --sync --needed --noconfirm git || fail 29 "pacman 安装 Git 失败" ;;
            esac
            ;;
        *) fail 29 "不支持在此 Unix 操作系统自动安装 Git：$git_host_os" ;;
    esac
    GIT_CHANGED=$requested_change
}

# 将 Unix 宿主映射到 Go 官方归档命名；未知组合必须停止而非猜测。
host_go_platform() {
    if [ -n "${AFH_TEST_HOST_OS:-}" ]; then
        host_os=$AFH_TEST_HOST_OS
    else
        host_os=$(uname -s 2>/dev/null) || fail 22 "无法探测操作系统"
    fi
    if [ -n "${AFH_TEST_HOST_ARCH:-}" ]; then
        host_arch=$AFH_TEST_HOST_ARCH
    else
        host_arch=$(uname -m 2>/dev/null) || fail 22 "无法探测 CPU 架构"
    fi
    case "$host_os" in
        Darwin) go_platform=darwin ;;
        Linux) go_platform=linux ;;
        *) fail 22 "Go 不支持此 Unix 操作系统：$host_os" ;;
    esac
    case "$host_arch" in
        x86_64|amd64) go_arch=amd64 ;;
        arm64|aarch64) go_arch=arm64 ;;
        i386|i486|i586|i686) go_arch=386 ;;
        *) fail 22 "Go 不支持此 CPU 架构：$host_arch" ;;
    esac
}

# 使用宿主已有 SHA-256 工具计算制品摘要，缺少校验能力时拒绝任何安装。
sha256_file() {
    checksum_path=$1
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$checksum_path" | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$checksum_path" | awk '{print $1}'
    else
        fail 25 "校验下载制品需要 sha256sum 或 shasum"
    fi
}

# 从官方发布清单解析目标归档的 SHA-256，再解压到标准当前用户 GOROOT。
install_go() {
    requested_change=$1
    command -v curl >/dev/null 2>&1 || fail 22 "安装 Go 需要 curl"
    command -v tar >/dev/null 2>&1 || fail 22 "安装 Go 需要 tar"
    host_go_platform
    go_dist_base=${AFH_GO_DIST_BASE:-https://go.dev/dl}
    go_dist_base=${go_dist_base%/}
    TEMP_DIR=$(mktemp -d) || fail 22 "无法创建临时目录"
    index_path=$TEMP_DIR/index.json
    download "$go_dist_base/?mode=json&include=all" "$index_path" || fail 22 "Go 发布版本索引下载失败"
    # 只接受稳定版本（无 rc/beta 后缀），按 major/minor/patch 取当前最高版本。
    go_version=$(awk '
        {
            line = $0
            while (match(line, /"version"[ \t]*:[ \t]*"go[0-9]+\.[0-9]+(\.[0-9]+)?"/)) {
                token = substr(line, RSTART, RLENGTH)
                sub(/.*"go/, "", token)
                sub(/"$/, "", token)
                printf "%s\n", token
                line = substr(line, RSTART + RLENGTH)
            }
        }
    ' "$index_path" | awk -F. '
        {
            patch = ($3 == "" ? 0 : $3)
            if (!found || $1 > best_major ||
                ($1 == best_major && ($2 > best_minor ||
                ($2 == best_minor && patch > best_patch)))) {
                found = 1
                best_major = $1
                best_minor = $2
                best_patch = patch
                best_version = $1 "." $2 "." patch
            }
        }
        END { if (found) print best_version }
    ')
    [ -n "$go_version" ] || fail 22 "Go 发布版本索引中没有可识别的稳定版"
    go_release_parts=$(printf '%s\n' "$go_version" | awk -F. '{ print $1 ":" $2 ":" $3 }')
    case "$go_release_parts" in
        [0-9]*:[0-9]*:[0-9]*) ;;
        *) fail 22 "Go 发布版本索引返回了不可识别的版本：$go_version" ;;
    esac
    go_archive=go$go_version.$go_platform-$go_arch.tar.gz
    archive_path=$TEMP_DIR/$go_archive
    printf '正在安装或升级 Go %s，来源为 %s，目标为标准当前用户 GOROOT。\n' "$go_version" "$go_dist_base" >&2
    download "$go_dist_base/$go_archive" "$archive_path" || fail 22 "Go 归档下载失败"
    checksums_path=$TEMP_DIR/checksums.txt
    download "$go_dist_base/go$go_version.$go_platform-$go_arch.tar.gz.sha256" "$checksums_path" 2>/dev/null || true
    if [ -s "$checksums_path" ]; then
        expected_sum=$(awk '{ print $1; exit }' "$checksums_path")
        [ -n "$expected_sum" ] || fail 22 "Go 归档校验和为空"
        case "$expected_sum" in
            *[!0-9A-Fa-f]*) fail 22 "Go 归档校验和格式无效：$go_archive" ;;
        esac
        [ "${#expected_sum}" -eq 64 ] || fail 22 "Go 归档校验和格式无效：$go_archive"
    else
        fail 22 "Go 官方归档校验和下载失败：$go_archive"
    fi
    actual_sum=$(sha256_file "$archive_path")
    [ "$actual_sum" = "$(printf '%s' "$expected_sum" | tr 'A-F' 'a-f')" ] || fail 22 "Go 归档 SHA-256 校验失败"
    prepare_managed_directory_path "$MANAGED_GOROOT" "Go 当前用户安装根"
    extracted_dir=$TEMP_DIR/go
    tar -xzf "$archive_path" -C "$TEMP_DIR" || fail 22 "Go 归档解压失败"
    [ -x "$extracted_dir/bin/go" ] || fail 22 "Go 归档不包含预期 go 可执行文件"
    extracted_go_version=$("$extracted_dir/bin/go" version 2>/dev/null) || fail 22 "Go 归档版本探测失败"
    [ "$extracted_go_version" = "go version go$go_version $go_platform/$go_arch" ] || \
        fail 22 "Go 归档版本与已选择稳定版不一致：期望 go$go_version，实际 $extracted_go_version"
    for goroot_entry in "$MANAGED_GOROOT"/* "$MANAGED_GOROOT"/.[!.]* "$MANAGED_GOROOT"/..?*; do
        [ -e "$goroot_entry" ] || [ -L "$goroot_entry" ] || continue
        find "$goroot_entry" -depth -delete 2>/dev/null || true
    done
    for extracted_entry in "$extracted_dir"/* "$extracted_dir"/.[!.]* "$extracted_dir"/..?*; do
        [ -e "$extracted_entry" ] || [ -L "$extracted_entry" ] || continue
        mv "$extracted_entry" "$MANAGED_GOROOT"/ || fail 22 "无法完成 Go 安装"
    done
    GO_BIN_DIR=$MANAGED_GOROOT/bin
    prepend_probe_path "$GO_BIN_DIR"
    GOROOT=$MANAGED_GOROOT
    export GOROOT
    GO_CHANGED=$requested_change
    cleanup
    TEMP_DIR=
}

# 把目录加入当前门禁探测路径并去重；空目录永远不会退化为当前工作目录。
prepend_probe_path() {
    candidate=$1
    [ -n "$candidate" ] && [ -d "$candidate" ] || return 0
    case ":$PROBE_PATH:" in
        *":$candidate:"*) ;;
        *) PROBE_PATH=$candidate${PROBE_PATH:+:$PROBE_PATH} ;;
    esac
}

# 只创建一个已经验证父目录的普通目录；既有符号链接或非目录对象一律拒绝。
ensure_plain_directory() {
    afh_directory_path=$1
    afh_directory_label=$2
    [ ! -L "$afh_directory_path" ] || fail 24 "$afh_directory_label 不能是符号链接：$afh_directory_path"
    if [ -e "$afh_directory_path" ]; then
        [ -d "$afh_directory_path" ] || fail 24 "$afh_directory_label 不是普通目录：$afh_directory_path"
    else
        mkdir "$afh_directory_path" || fail 24 "无法创建${afh_directory_label}：$afh_directory_path"
    fi
    [ -d "$afh_directory_path" ] && [ ! -L "$afh_directory_path" ] || fail 24 "$afh_directory_label 在创建时发生变化：$afh_directory_path"
}

# 逐级验证当前用户受管安装根；测试重定向也只能位于隔离 HOME 的同级测试根内。
validate_managed_directory_path() {
    afh_candidate=$1
    afh_directory_label=$2
    case "$afh_candidate" in
        "$USER_HOME"/*)
            afh_trusted_root=$USER_HOME
            afh_relative=${afh_candidate#"$USER_HOME"/}
            ;;
        *)
            [ "$TEST_MODE" = 1 ] || fail 24 "$afh_directory_label 必须位于当前用户目录内：$afh_candidate"
            afh_test_root=${USER_HOME%/*}
            case "$afh_candidate" in
                "$afh_test_root"/*)
                    afh_trusted_root=$afh_test_root
                    afh_relative=${afh_candidate#"$afh_test_root"/}
                    ;;
                *) fail 24 "测试受管安装根必须位于隔离 HOME 的同级测试根内：$afh_candidate" ;;
            esac
            ;;
    esac
    afh_directory_cursor=$afh_trusted_root
    afh_old_ifs=$IFS
    afh_glob_was_enabled=0
    case $- in
        *f*) ;;
        *) set -f; afh_glob_was_enabled=1 ;;
    esac
    IFS=/
    for afh_component in $afh_relative; do
        case "$afh_component" in
            ''|.|..) fail 24 "$afh_directory_label 包含不安全路径组件：$afh_candidate" ;;
        esac
        afh_directory_cursor=$afh_directory_cursor/$afh_component
        [ ! -L "$afh_directory_cursor" ] || fail 24 "$afh_directory_label 的路径组件不能是符号链接：$afh_directory_cursor"
        if [ -e "$afh_directory_cursor" ] && [ ! -d "$afh_directory_cursor" ]; then
            fail 24 "$afh_directory_label 的路径组件不是普通目录：$afh_directory_cursor"
        fi
    done
    IFS=$afh_old_ifs
    [ "$afh_glob_was_enabled" -eq 0 ] || set +f
}

# 预检通过后逐级创建同一路径，每一步都复核没有被符号链接替换。
prepare_managed_directory_path() {
    afh_candidate=$1
    afh_directory_label=$2
    validate_managed_directory_path "$afh_candidate" "$afh_directory_label"
    case "$afh_candidate" in
        "$USER_HOME"/*)
            afh_trusted_root=$USER_HOME
            afh_relative=${afh_candidate#"$USER_HOME"/}
            ;;
        *)
            afh_trusted_root=${USER_HOME%/*}
            afh_relative=${afh_candidate#"$afh_trusted_root"/}
            ;;
    esac
    afh_directory_cursor=$afh_trusted_root
    afh_old_ifs=$IFS
    afh_glob_was_enabled=0
    case $- in
        *f*) ;;
        *) set -f; afh_glob_was_enabled=1 ;;
    esac
    IFS=/
    for afh_component in $afh_relative; do
        afh_directory_cursor=$afh_directory_cursor/$afh_component
        if [ ! -e "$afh_directory_cursor" ]; then
            mkdir "$afh_directory_cursor" || fail 24 "无法创建${afh_directory_label}：$afh_directory_cursor"
        fi
        [ -d "$afh_directory_cursor" ] && [ ! -L "$afh_directory_cursor" ] || fail 24 "$afh_directory_label 在创建时发生变化：$afh_directory_cursor"
    done
    IFS=$afh_old_ifs
    [ "$afh_glob_was_enabled" -eq 0 ] || set +f
}

# 标准当前用户 PATH 块只有这一份规范字节；预检与写入共用，避免 marker 与正文分离。
profile_managed_block() {
    printf '%s\n' \
        '# agent-first-harness: standard current-user tool PATH' \
        'user_path_result=' \
        'user_go_root=${GOROOT:-$HOME/.local/go}' \
        'case "$user_go_root" in "$HOME"/*) case "$user_go_root" in *:*|*/../*|*/..|*/./*|*/.) user_go_root= ;; esac ;; *) user_go_root= ;; esac' \
        'for user_path_entry in "${user_go_root:+$user_go_root/bin}" "$HOME/go/bin" "$HOME/.local/bin"; do' \
        '    [ -n "$user_path_entry" ] || continue' \
        '    case "$user_path_entry" in /*) ;; *) continue ;; esac' \
        '    case ":$user_path_result:" in *":$user_path_entry:"*) ;; *) [ -n "$user_path_result" ] && user_path_result=$user_path_result:$user_path_entry || user_path_result=$user_path_entry ;; esac' \
        'done' \
        'user_path_old_ifs=$IFS' \
        'user_path_glob_was_enabled=0' \
        'case $- in *f*) ;; *) set -f; user_path_glob_was_enabled=1 ;; esac' \
        'IFS=:' \
        'for user_path_entry in ${PATH-}; do' \
        '    [ -n "$user_path_entry" ] || continue' \
        '    case "$user_path_entry" in /*) ;; *) continue ;; esac' \
        '    case ":$user_path_result:" in *":$user_path_entry:"*) ;; *) [ -n "$user_path_result" ] && user_path_result=$user_path_result:$user_path_entry || user_path_result=$user_path_entry ;; esac' \
        'done' \
        'IFS=$user_path_old_ifs' \
        '[ "$user_path_glob_was_enabled" -eq 0 ] || set +f' \
        'PATH=$user_path_result' \
        'export PATH' \
        'unset user_path_result user_path_entry user_go_root user_path_old_ifs user_path_glob_was_enabled' \
        '# agent-first-harness: end standard current-user tool PATH'
}

# 配置文件写入前必须已经是普通文件；受管块必须唯一、正序且正文逐字匹配。
validate_profile_file_shape() {
    afh_profile_path=$1
    [ ! -L "$afh_profile_path" ] || fail 24 "shell profile 不能是符号链接：$afh_profile_path"
    if [ -e "$afh_profile_path" ] && [ ! -f "$afh_profile_path" ]; then
        fail 24 "shell profile 不是普通文件：$afh_profile_path"
    fi
    [ -f "$afh_profile_path" ] || return 0
    afh_path_marker='# agent-first-harness: standard current-user tool PATH'
    afh_path_end_marker='# agent-first-harness: end standard current-user tool PATH'
    afh_path_marker_count=$(grep -Fxc "$afh_path_marker" "$afh_profile_path" || true)
    afh_path_end_marker_count=$(grep -Fxc "$afh_path_end_marker" "$afh_profile_path" || true)
    [ "$afh_path_marker_count" -eq "$afh_path_end_marker_count" ] && [ "$afh_path_marker_count" -le 1 ] || \
        fail 24 "shell profile 中的标准用户 PATH 管理块不完整或重复：$afh_profile_path"
    if [ "$afh_path_marker_count" -eq 1 ]; then
        afh_actual_block=$(awk -v start="$afh_path_marker" -v finish="$afh_path_end_marker" \
            '$0 == start { capture = 1 } capture { print } capture && $0 == finish { exit }' "$afh_profile_path")
        afh_expected_block=$(profile_managed_block)
        [ "$afh_actual_block" = "$afh_expected_block" ] || \
            fail 24 "shell profile 中的标准用户 PATH 管理块顺序或正文已损坏：$afh_profile_path"
    fi
}

validate_managed_file_shape() {
    afh_managed_file=$1
    afh_managed_label=$2
    afh_expected_marker='# managed by agent-first-harness development environment gate'
    [ ! -L "$afh_managed_file" ] || fail 24 "$afh_managed_label 不能是符号链接：$afh_managed_file"
    if [ -e "$afh_managed_file" ]; then
        [ -f "$afh_managed_file" ] || fail 24 "$afh_managed_label 不是普通文件：$afh_managed_file"
        [ "$(sed -n '1p' "$afh_managed_file")" = "$afh_expected_marker" ] || fail 24 "$afh_managed_label 已存在且不受门禁管理：$afh_managed_file"
    fi
}

# 验证标准 ~/.local/bin 的每个固定路径组件都是普通目录，禁止沿预置符号链接写出预期范围。
validate_user_tool_directory_path() {
    afh_local_dir=${HOME:?必须设置 HOME}/.local
    afh_user_bin=$afh_local_dir/bin
    for afh_directory in "$afh_local_dir" "$afh_user_bin"; do
        [ ! -L "$afh_directory" ] || fail 24 "用户级工具目录组件不能是符号链接：$afh_directory"
        if [ -e "$afh_directory" ] && [ ! -d "$afh_directory" ]; then
            fail 24 "用户级工具目录组件不是普通目录：$afh_directory"
        fi
    done
}

# 逐级创建并复核标准用户 bin；不用 mkdir -p 跨越未经验证的中间组件。
prepare_user_tool_directory() {
    validate_user_tool_directory_path
    for afh_directory in "$afh_local_dir" "$afh_user_bin"; do
        if [ ! -e "$afh_directory" ]; then
            mkdir "$afh_directory" || fail 24 "无法创建用户级工具目录组件：$afh_directory"
        fi
        [ -d "$afh_directory" ] && [ ! -L "$afh_directory" ] || fail 24 "用户级工具目录组件在创建时发生变化：$afh_directory"
    done
    USER_BIN_DIR=$afh_user_bin
}

# 把存在父目录的路径归一化为物理绝对路径；不能证明时保持失败关闭。
physical_path_with_existing_parent() {
    afh_candidate=$1
    case "$afh_candidate" in
        /*) ;;
        *) return 1 ;;
    esac
    afh_parent=${afh_candidate%/*}
    afh_name=${afh_candidate##*/}
    afh_physical_parent=$(CDPATH= cd -P "$afh_parent" 2>/dev/null && pwd -P) || return 1
    printf '%s/%s\n' "$afh_physical_parent" "$afh_name"
}

# 解析最终组件及其 symlink 链，确保 containment 检查不会停在可逃逸的末端链接上。
physical_existing_path() {
    afh_resolved_candidate=$1
    afh_symlink_hops=0
    while [ -L "$afh_resolved_candidate" ]; do
        afh_symlink_hops=$((afh_symlink_hops + 1))
        [ "$afh_symlink_hops" -le 40 ] || return 1
        afh_link_target=$(readlink "$afh_resolved_candidate") || return 1
        case "$afh_link_target" in
            /*) afh_resolved_candidate=$afh_link_target ;;
            *) afh_resolved_candidate=${afh_resolved_candidate%/*}/$afh_link_target ;;
        esac
        afh_resolved_candidate=$(physical_path_with_existing_parent "$afh_resolved_candidate") || return 1
    done
    [ -e "$afh_resolved_candidate" ] || return 1
    physical_path_with_existing_parent "$afh_resolved_candidate"
}

# 把已经逐级验证过的用户安装根映射为物理路径；末端尚未创建时也不需要提前产生写入。
physical_managed_path() {
    afh_managed_candidate=$1
    case "$afh_managed_candidate" in
        "$USER_HOME"/*)
            afh_managed_trusted_root=$USER_HOME
            afh_managed_relative=${afh_managed_candidate#"$USER_HOME"/}
            ;;
        *)
            [ "$TEST_MODE" = 1 ] || return 1
            afh_managed_trusted_root=${USER_HOME%/*}
            case "$afh_managed_candidate" in
                "$afh_managed_trusted_root"/*)
                    afh_managed_relative=${afh_managed_candidate#"$afh_managed_trusted_root"/}
                    ;;
                *) return 1 ;;
            esac
            ;;
    esac
    afh_managed_physical_root=$(CDPATH= cd -P "$afh_managed_trusted_root" 2>/dev/null && pwd -P) || return 1
    printf '%s/%s\n' "$afh_managed_physical_root" "$afh_managed_relative"
}

# 在产生下载或安装副作用前确认同名稳定入口可由本门禁安全替换。
validate_user_tool_destination() {
    tool_name=$1
    managed_root=$2
    validate_user_tool_directory_path
    destination=$afh_user_bin/$tool_name
    if [ -e "$destination" ] && [ ! -L "$destination" ]; then
        fail 24 "用户级工具目标已存在且不受门禁管理：$destination"
    fi
    [ -L "$destination" ] || return 0
    managed_root_physical=$(physical_managed_path "$managed_root") || fail 24 "无法确认受管安装根：$managed_root"
    existing_target=$(readlink "$destination") || fail 24 "无法读取既有用户级工具链接：$destination"
    case "$existing_target" in
        /*) existing_target_path=$existing_target ;;
        *) existing_target_path=$afh_user_bin/$existing_target ;;
    esac
    existing_target_physical=$(physical_existing_path "$existing_target_path") || fail 24 "既有用户级工具链接无法证明受管归属：$destination"
    case "$existing_target_physical" in
        "$managed_root_physical"/*) ;;
        *) fail 24 "既有用户级工具链接不属于当前受管安装根：$destination" ;;
    esac
}

# 在门禁拥有的稳定用户 bin 中原子替换单个工具链接；既有链接也必须指向同一受管安装根。
link_user_tool() {
    source_path=$1
    tool_name=$2
    managed_root=$3
    [ -x "$source_path" ] && [ ! -d "$source_path" ] || fail 24 "用户级工具源不可执行：$source_path"
    validate_user_tool_destination "$tool_name" "$managed_root"
    prepare_user_tool_directory
    user_bin=$USER_BIN_DIR
    managed_root_physical=$(physical_managed_path "$managed_root") || fail 24 "无法确认受管安装根：$managed_root"
    source_physical=$(physical_existing_path "$source_path") || fail 24 "无法确认用户级工具源范围：$source_path"
    case "$source_physical" in
        "$managed_root_physical"/*) ;;
        *) fail 24 "用户级工具源不在受管安装根内：$source_path" ;;
    esac
    destination=$user_bin/$tool_name
    LINK_TEMP_DIR=$(mktemp -d "$user_bin/.link-$tool_name.XXXXXX") || fail 24 "无法创建用户级工具临时目录：$tool_name"
    [ -d "$LINK_TEMP_DIR" ] && [ ! -L "$LINK_TEMP_DIR" ] || fail 24 "用户级工具临时目录不安全：$tool_name"
    temporary_link=$LINK_TEMP_DIR/$tool_name
    ln -s "$source_path" "$temporary_link" || fail 24 "无法建立用户级工具链接：$tool_name"
    if ! mv -f "$temporary_link" "$destination"; then
        rm -f "$temporary_link"
        fail 24 "无法提交用户级工具链接：$tool_name"
    fi
    rmdir "$LINK_TEMP_DIR" || fail 24 "无法清理用户级工具临时目录：$tool_name"
    LINK_TEMP_DIR=
}

# 以同目录临时文件把标准当前用户目录直接加入 PATH；不创建 Harness 私有环境文件或变量。
ensure_profile_path() {
    profile_path=$1
    path_marker='# agent-first-harness: standard current-user tool PATH'
    path_end_marker='# agent-first-harness: end standard current-user tool PATH'
    legacy_source_line='[ -r "$HOME/.config/agent-first-harness/env.sh" ] && . "$HOME/.config/agent-first-harness/env.sh"'
    if [ -e "$profile_path" ] && { [ ! -f "$profile_path" ] || [ -L "$profile_path" ]; }; then
        fail 24 "shell profile 不是可安全更新的普通文件：$profile_path"
    fi
    has_path_marker=0
    has_path_end_marker=0
    has_legacy_source=0
    if [ -f "$profile_path" ]; then
        grep -Fqx "$path_marker" "$profile_path" && has_path_marker=1
        grep -Fqx "$path_end_marker" "$profile_path" && has_path_end_marker=1
        grep -Fqx "$legacy_source_line" "$profile_path" && has_legacy_source=1
    fi
    [ "$has_path_marker" -eq "$has_path_end_marker" ] || fail 24 "shell profile 中的标准用户 PATH 管理块不完整：$profile_path"
    if [ "$has_path_marker" -eq 1 ] && [ "$has_legacy_source" -eq 0 ]; then
        return
    fi
    profile_parent=${profile_path%/*}
    profile_name=${profile_path##*/}
    umask 077
    profile_temp=$(mktemp "$profile_parent/.$profile_name.agent-first-harness.tmp.XXXXXX") || fail 24 "无法创建 shell profile 临时文件：$profile_path"
    PROFILE_TEMP_FILE=$profile_temp
    profile_snapshot=
    profile_existed=0
    if [ -f "$profile_path" ]; then
        profile_existed=1
        profile_snapshot=$(mktemp "$profile_parent/.$profile_name.agent-first-harness.snapshot.XXXXXX") || fail 24 "无法创建 shell profile 快照：$profile_path"
        PROFILE_SNAPSHOT_FILE=$profile_snapshot
        cp -p "$profile_path" "$profile_snapshot" || fail 24 "无法快照 shell profile：$profile_path"
        cp -p "$profile_path" "$profile_temp" || fail 24 "无法复制 shell profile：$profile_path"
        if [ "$has_legacy_source" -eq 1 ]; then
            : > "$profile_temp" || fail 24 "无法准备旧环境入口迁移：$profile_path"
            while IFS= read -r profile_line || [ -n "$profile_line" ]; do
                [ "$profile_line" = "$legacy_source_line" ] || printf '%s\n' "$profile_line" >> "$profile_temp"
            done < "$profile_snapshot"
        fi
    fi
    if [ "$has_path_marker" -eq 0 ]; then
        printf '\n' >> "$profile_temp" || fail 24 "无法准备 shell profile 更新：$profile_path"
        profile_managed_block >> "$profile_temp" || fail 24 "无法准备 shell profile 更新：$profile_path"
    fi
    [ -f "$profile_temp" ] && [ ! -L "$profile_temp" ] || fail 24 "shell profile 临时文件不安全：$profile_path"
    validate_profile_file_shape "$profile_path"
    if [ "$profile_existed" -eq 1 ]; then
        cmp -s "$profile_path" "$profile_snapshot" || fail 24 "shell profile 在提交前被并发修改：$profile_path"
    elif [ -e "$profile_path" ] || [ -L "$profile_path" ]; then
        fail 24 "shell profile 在提交前被并发创建：$profile_path"
    fi
    mv -f "$profile_temp" "$profile_path" || fail 24 "无法原子提交 shell profile：$profile_path"
    PROFILE_TEMP_FILE=
    if [ -n "$profile_snapshot" ]; then
        rm -f "$profile_snapshot" || fail 24 "无法清理 shell profile 快照：$profile_path"
        PROFILE_SNAPSHOT_FILE=
    fi
    [ -f "$profile_path" ] && [ ! -L "$profile_path" ] && \
        grep -Fqx "$path_marker" "$profile_path" && grep -Fqx "$path_end_marker" "$profile_path" || \
        fail 24 "shell profile 写入后复核失败：$profile_path"
    ! grep -Fqx "$legacy_source_line" "$profile_path" || fail 24 "shell profile 仍引用旧的 Harness 私有环境文件：$profile_path"
}

# 只为可证明会加载所写用户配置的常见 shell 建立持久化；未知 shell 在任何安装前失败关闭。
validate_user_login_shell() {
    LOGIN_SHELL=${SHELL:-/bin/sh}
    [ -x "$LOGIN_SHELL" ] || fail 24 "无法执行用户登录 shell：$LOGIN_SHELL"
    LOGIN_SHELL_NAME=${LOGIN_SHELL##*/}
    case "$LOGIN_SHELL_NAME" in
        sh|sh.exe|dash|ash|ksh|ksh93|mksh|bash|bash.exe|zsh|fish) ;;
        *) fail 24 "不支持自动持久化 PATH 的用户 shell：$LOGIN_SHELL_NAME" ;;
    esac
}

# 任何安装或持久配置写入前，先从不含瞬时探测目录的全新 login shell 复核所有工具。
# passed 项必须路径与版本完全相同；待安装/升级项的当前探测与持久 PATH 也必须同时缺席或解析到同一路径。
# 如果本轮将写入标准用户 PATH 块，还要先按写入后的前缀顺序复核，不得先安装再发现隐藏的同名工具。
verify_persisted_passed_tools_before_write() {
    preflight_git_path=
    preflight_go_path=
    preflight_check_git_shadow=0
    preflight_check_go_shadow=0

    if [ "$GIT_STATUS" = passed ]; then
        preflight_git_path=$git_path
    else
        preflight_check_git_shadow=1
    fi
    if [ "$GO_STATUS" = passed ]; then
        preflight_go_path=$go_path
    else
        preflight_check_go_shadow=1
    fi

    preflight_projected_path=
    if [ "$GO_STATUS" != passed ] && ! { [ "$TEST_MODE" = 1 ] && [ "${AFH_SKIP_PERSIST_PATH:-0}" = 1 ]; }; then
        preflight_go_bin=$MANAGED_GOROOT/bin
        preflight_user_bin=$USER_HOME/.local/bin
        case "$LOGIN_SHELL_NAME" in
            fish) preflight_projected_path=$preflight_user_bin:$preflight_go_bin ;;
            *) preflight_projected_path=$preflight_go_bin:$preflight_user_bin ;;
        esac
    fi

    FRESH_VERIFY_DIR=$(mktemp -d) || fail 24 "无法创建写入前新 shell 复探临时目录"
    [ -d "$FRESH_VERIFY_DIR" ] && [ ! -L "$FRESH_VERIFY_DIR" ] || fail 24 "写入前新 shell 复探临时目录不安全"
    preflight_verifier=$(mktemp "$FRESH_VERIFY_DIR/check.XXXXXX") || fail 24 "无法创建写入前新 shell 复探脚本"
    preflight_launcher=$(mktemp "$FRESH_VERIFY_DIR/launch.XXXXXX") || fail 24 "无法创建写入前新 shell 复探启动器"
    FRESH_VERIFY_FILE=$preflight_verifier
    {
        printf '%s\n' '#!/bin/sh'
        printf '%s\n' 'set -eu'
        printf '%s\n' 'if [ -n "${AFH_PROJECTED_PATH-}" ]; then PATH=$AFH_PROJECTED_PATH${PATH:+:$PATH}; export PATH; fi'
        printf '%s\n' 'check_afh_preflight_tool() {'
        printf '%s\n' '    afh_tool_name=$1'
        printf '%s\n' '    afh_expected_path=$2'
        printf '%s\n' '    afh_expected_version=$3'
        printf '%s\n' '    afh_resolved=$(command -v "$afh_tool_name" 2>/dev/null) || { printf "ERROR_TOOL=%s\n" "$afh_tool_name"; exit 51; }'
        printf '%s\n' '    [ "$afh_resolved" = "$afh_expected_path" ] || { printf "ERROR_TOOL=%s\n" "$afh_tool_name"; exit 52; }'
        printf '%s\n' '    afh_actual_version=$("$afh_resolved" --version 2>/dev/null) || { printf "ERROR_TOOL=%s\n" "$afh_tool_name"; exit 53; }'
        printf '%s\n' '    [ "$afh_actual_version" = "$afh_expected_version" ] || { printf "ERROR_TOOL=%s\n" "$afh_tool_name"; exit 54; }'
        printf '%s\n' '    if [ "$afh_tool_name" = go ]; then'
        printf '%s\n' '        afh_actual_version=$("$afh_resolved" version 2>/dev/null) || { printf "ERROR_TOOL=%s\n" "$afh_tool_name"; exit 55; }'
        printf '%s\n' '        [ "$afh_actual_version" = "$afh_expected_version" ] || { printf "ERROR_TOOL=%s\n" "$afh_tool_name"; exit 55; }'
        printf '%s\n' '        afh_go_root=$("$afh_resolved" env GOROOT 2>/dev/null) || { printf "ERROR_TOOL=%s\n" "$afh_tool_name"; exit 55; }'
        printf '%s\n' '        [ "$afh_go_root" = "$AFH_EXPECTED_GOROOT" ] || { printf "ERROR_TOOL=%s\n" "$afh_tool_name"; exit 55; }'
        printf '%s\n' '    fi'
        printf '%s\n' '}'
        printf '%s\n' 'check_afh_no_shell_shadow() {'
        printf '%s\n' '    afh_tool_name=$1'
        printf '%s\n' '    afh_current_path=$2'
        printf '%s\n' '    if afh_resolved=$(command -v "$afh_tool_name" 2>/dev/null); then'
        printf '%s\n' '        case "$afh_resolved" in /*) ;; *) printf "ERROR_TOOL=%s\n" "$afh_tool_name"; exit 56 ;; esac'
        printf '%s\n' '        [ -n "$afh_current_path" ] && [ "$afh_resolved" = "$afh_current_path" ] || { printf "ERROR_TOOL=%s\n" "$afh_tool_name"; exit 57; }'
        printf '%s\n' '    elif [ -n "$afh_current_path" ]; then'
        printf '%s\n' '        printf "ERROR_TOOL=%s\n" "$afh_tool_name"; exit 58'
        printf '%s\n' '    fi'
        printf '%s\n' '}'
        printf '%s\n' 'if [ -n "${AFH_EXPECTED_GIT_PATH-}" ]; then check_afh_preflight_tool git "$AFH_EXPECTED_GIT_PATH" "$AFH_EXPECTED_GIT"; elif [ "$AFH_CHECK_GIT_SHADOW" = 1 ]; then check_afh_no_shell_shadow git "$AFH_CURRENT_GIT_PATH"; fi'
        printf '%s\n' 'if [ -n "${AFH_EXPECTED_GO_PATH-}" ]; then check_afh_preflight_tool go "$AFH_EXPECTED_GO_PATH" "$AFH_EXPECTED_GO"; elif [ "$AFH_CHECK_GO_SHADOW" = 1 ]; then check_afh_no_shell_shadow go "$AFH_CURRENT_GO_PATH"; fi'
        printf '%s\n' 'printf "AFH_PREFLIGHT_PERSISTED=passed\n"'
    } > "$preflight_verifier" || fail 24 "无法写入写入前新 shell 复探脚本"
    chmod 700 "$preflight_verifier" || fail 24 "无法保护写入前新 shell 复探脚本"
    {
        printf '%s\n' '#!/bin/sh'
        printf '%s\n' 'set -eu'
        printf '%s\n' 'unset GOROOT'
        printf '%s\n' 'exec "$AFH_LOGIN_SHELL" -l -c "$AFH_LOGIN_COMMAND"'
    } > "$preflight_launcher" || fail 24 "无法写入写入前新 shell 复探启动器"
    chmod 700 "$preflight_launcher" || fail 24 "无法保护写入前新 shell 复探启动器"

    preflight_login_command='"$AFH_PREFLIGHT_VERIFY"'
    case "$LOGIN_SHELL_NAME" in
        fish) ;;
        *) preflight_login_command='. "$AFH_PREFLIGHT_VERIFY"' ;;
    esac
    preflight_failure=0
    preflight_environment=$(
        AFH_LOGIN_SHELL=$LOGIN_SHELL \
        AFH_LOGIN_COMMAND=$preflight_login_command \
        AFH_PREFLIGHT_VERIFY=$preflight_verifier \
        AFH_EXPECTED_GIT_PATH=$preflight_git_path \
        AFH_EXPECTED_GO_PATH=$preflight_go_path \
        AFH_CURRENT_GIT_PATH=$git_path \
        AFH_CURRENT_GO_PATH=$go_path \
        AFH_PROJECTED_PATH=$preflight_projected_path \
        AFH_EXPECTED_GIT=$GIT_VERSION \
        AFH_EXPECTED_GO=$GO_VERSION \
        AFH_EXPECTED_GOROOT=$MANAGED_GOROOT \
        AFH_CHECK_GIT_SHADOW=$preflight_check_git_shadow \
        AFH_CHECK_GO_SHADOW=$preflight_check_go_shadow \
        PATH=$FRESH_BASE_PATH \
        "$preflight_launcher" 2>/dev/null
    ) || preflight_failure=$?
    preflight_success_count=$(printf '%s\n' "$preflight_environment" | awk -F= '$1 == "AFH_PREFLIGHT_PERSISTED" && $2 == "passed" { count++ } END { print count + 0 }')
    if [ "$preflight_failure" -ne 0 ] || [ "$preflight_success_count" -ne 1 ]; then
        preflight_failed_tool=$(printf '%s\n' "$preflight_environment" | awk -F= '$1 == "ERROR_TOOL" { print $2; exit }')
        fail 24 "写入前新 shell 无法从持久 PATH 精确解析并执行既有工具 ${preflight_failed_tool:-unknown}（子进程退出码 ${preflight_failure}）"
    fi
    rm -f "$preflight_verifier" "$preflight_launcher" || fail 24 "无法清理写入前新 shell 复探脚本"
    FRESH_VERIFY_FILE=
    rmdir "$FRESH_VERIFY_DIR" || fail 24 "无法清理写入前新 shell 复探临时目录"
    FRESH_VERIFY_DIR=
}

# 非默认 Go 用户根必须能由全新 login shell 自己恢复；当前进程的一次性环境变量不能决定持久安装位置。
validate_durable_go_roots() {
    default_go_root=$USER_HOME/.local/go
    if [ "$MANAGED_GOROOT" = "$default_go_root" ]; then
        return
    fi
    [ "$TEST_MODE" = 1 ] && [ "${AFH_SKIP_PERSIST_PATH:-0}" = 1 ] && return

    FRESH_VERIFY_DIR=$(mktemp -d) || fail 24 "无法创建 Go 用户根持久化复探临时目录"
    [ -d "$FRESH_VERIFY_DIR" ] && [ ! -L "$FRESH_VERIFY_DIR" ] || fail 24 "Go 用户根持久化复探临时目录不安全"
    go_root_verifier=$(mktemp "$FRESH_VERIFY_DIR/check.XXXXXX") || fail 24 "无法创建 Go 用户根持久化复探脚本"
    go_root_launcher=$(mktemp "$FRESH_VERIFY_DIR/launch.XXXXXX") || fail 24 "无法创建 Go 用户根持久化复探启动器"
    FRESH_VERIFY_FILE=$go_root_verifier
    {
        printf '%s\n' '#!/bin/sh'
        printf '%s\n' 'set -eu'
        printf '%s\n' 'printf "AFH_GOROOT=%s\\n" "${GOROOT:-$HOME/.local/go}"'
    } > "$go_root_verifier" || fail 24 "无法写入 Go 用户根持久化复探脚本"
    chmod 700 "$go_root_verifier" || fail 24 "无法保护 Go 用户根持久化复探脚本"
    {
        printf '%s\n' '#!/bin/sh'
        printf '%s\n' 'set -eu'
        printf '%s\n' 'unset GOROOT'
        printf '%s\n' 'exec "$AFH_LOGIN_SHELL" -l -c "$AFH_LOGIN_COMMAND"'
    } > "$go_root_launcher" || fail 24 "无法写入 Go 用户根持久化复探启动器"
    chmod 700 "$go_root_launcher" || fail 24 "无法保护 Go 用户根持久化复探启动器"

    go_root_failure=0
    durable_go_roots=$(
        AFH_LOGIN_SHELL=$LOGIN_SHELL \
        AFH_LOGIN_COMMAND='"$AFH_GO_ROOT_VERIFY"' \
        AFH_GO_ROOT_VERIFY=$go_root_verifier \
        PATH=$FRESH_BASE_PATH \
        "$go_root_launcher" 2>/dev/null
    ) || go_root_failure=$?
    if [ "$go_root_failure" -ne 0 ]; then
        fail 24 "全新 login shell 无法复探非默认 Go 用户安装根（子进程退出码 ${go_root_failure}）"
    fi
    durable_go_root_count=$(printf '%s\n' "$durable_go_roots" | awk -F= '$1 == "AFH_GOROOT" { count++ } END { print count + 0 }')
    durable_go_root=$(printf '%s\n' "$durable_go_roots" | awk -F= '$1 == "AFH_GOROOT" { sub(/^AFH_GOROOT=/, ""); print; exit }')
    [ "$durable_go_root_count" -eq 1 ] && [ "$durable_go_root" = "$MANAGED_GOROOT" ] || \
        fail 24 "非默认 GOROOT 必须由用户级 login shell 持久恢复，不能只存在于当前进程"

    rm -f "$go_root_verifier" "$go_root_launcher" || fail 24 "无法清理 Go 用户根持久化复探脚本"
    FRESH_VERIFY_FILE=
    rmdir "$FRESH_VERIFY_DIR" || fail 24 "无法清理 Go 用户根持久化复探临时目录"
    FRESH_VERIFY_DIR=
}

# 汇总所有将写入的安装根、profile、受管配置与稳定链接；任何冲突都在下载/安装前失败。
preflight_user_installation() {
    validate_user_login_shell
    if ! { [ "$TEST_MODE" = 1 ] && [ "${AFH_SKIP_PERSIST_PATH:-0}" = 1 ]; }; then
        validate_managed_directory_path "$MANAGED_GOROOT" "Go 当前用户 PATH 根"
        validate_user_tool_directory_path
    fi
    if [ "$GO_STATUS" != passed ]; then
        validate_managed_directory_path "$MANAGED_GOROOT" "Go 当前用户安装根"
        validate_managed_directory_path "$MANAGED_GOPATH" "Go 当前用户工作区根"
    fi
    [ "$TEST_MODE" = 1 ] && [ "${AFH_SKIP_PERSIST_PATH:-0}" = 1 ] && return
    command -v cp >/dev/null 2>&1 || fail 24 "原子维护 shell profile 需要 cp"
    command -v cmp >/dev/null 2>&1 || fail 24 "原子维护 shell profile 需要 cmp"
    validate_profile_file_shape "$USER_HOME/.profile"
    case "$LOGIN_SHELL_NAME" in
        bash|bash.exe)
            validate_profile_file_shape "$USER_HOME/.bashrc"
            validate_profile_file_shape "$USER_HOME/.bash_profile"
            validate_profile_file_shape "$USER_HOME/.bash_login"
            ;;
        zsh)
            validate_profile_file_shape "$USER_HOME/.zprofile"
            validate_profile_file_shape "$USER_HOME/.zshrc"
            ;;
        fish)
            validate_managed_directory_path "$USER_HOME/.config/fish" "fish 用户配置目录"
            validate_managed_directory_path "$USER_HOME/.config/fish/conf.d" "fish 用户配置目录"
            validate_managed_file_shape "$USER_HOME/.config/fish/conf.d/agent-first-harness.fish" "fish 用户 PATH 配置"
            ;;
    esac
    validate_durable_go_roots
}

# fish 的层级目录先于任何下载或安装逐级建立并复核，后续配置提交不会因新用户缺少 ~/.config 而半途失败。
prepare_user_configuration_directories() {
    if [ "$LOGIN_SHELL_NAME" = fish ]; then
        prepare_managed_directory_path "$USER_HOME/.config/fish/conf.d" "fish 用户配置目录"
    fi
}

# fish 使用原生命令把标准当前用户工具目录加入 PATH，不创建私有环境变量。
write_fish_path_config() {
    fish_root=${HOME:?必须设置 HOME}/.config/fish
    fish_config_dir=$fish_root/conf.d
    prepare_managed_directory_path "$fish_config_dir" "fish 用户配置目录"
    fish_file=$fish_config_dir/agent-first-harness.fish
    [ ! -e "$fish_file" ] || { [ -f "$fish_file" ] && [ ! -L "$fish_file" ]; } || fail 24 "fish 用户 PATH 配置不是普通文件：$fish_file"
    fish_marker='# managed by agent-first-harness development environment gate'
    if [ -f "$fish_file" ] && [ "$(sed -n '1p' "$fish_file")" != "$fish_marker" ]; then
        fail 24 "fish 用户 PATH 配置已存在且不受门禁管理：$fish_file"
    fi
    umask 077
    fish_temp=$(mktemp "$fish_config_dir/.agent-first-harness.fish.tmp.XXXXXX") || fail 24 "无法创建 fish 用户 PATH 临时文件"
    FISH_TEMP_FILE=$fish_temp
    {
        printf '%s\n' "$fish_marker"
        printf '%s\n' 'set -l user_go_root "$HOME/.local/go"'
        printf '%s\n' 'if set -q GOROOT'
        printf '%s\n' '    set user_go_root "$GOROOT"'
        printf '%s\n' 'end'
        printf '%s\n' 'set -l user_go_safe 1'
        printf '%s\n' 'if not string match -q -- "$HOME/*" "$user_go_root"'
        printf '%s\n' '    set user_go_safe 0'
        printf '%s\n' 'end'
        printf '%s\n' 'for user_go_unsafe_pattern in "*:*" "*/../*" "*/.." "*/./*" "*/."'
        printf '%s\n' '    if string match -q -- "$user_go_unsafe_pattern" "$user_go_root"'
        printf '%s\n' '        set user_go_safe 0'
        printf '%s\n' '    end'
        printf '%s\n' 'end'
        printf '%s\n' 'if test "$user_go_safe" -eq 1; and test "$user_go_root/bin" != "$HOME/.local/bin"'
        printf '%s\n' '    fish_add_path --path "$user_go_root/bin"'
        printf '%s\n' 'end'
        printf '%s\n' 'fish_add_path --path "$HOME/go/bin"'
        printf '%s\n' 'fish_add_path --path "$HOME/.local/bin"'
        printf '%s\n' 'set -e user_go_root user_go_safe user_go_unsafe_pattern'
    } > "$fish_temp" || fail 24 "无法写入 fish 用户 PATH 配置"
    [ -f "$fish_temp" ] && [ ! -L "$fish_temp" ] || fail 24 "fish 用户 PATH 临时文件不安全"
    mv -f "$fish_temp" "$fish_file" || fail 24 "无法提交 fish 用户 PATH 配置"
    FISH_TEMP_FILE=
}

# 工具变化后直接持久化标准当前用户 PATH，并由全新 login shell 锁定路径与版本复探。
persist_user_tool_path() {
    [ "$TEST_MODE" = 1 ] && [ "${AFH_SKIP_PERSIST_PATH:-0}" = 1 ] && return
    validate_user_login_shell
    managed_path_changed=0
    if [ "$GO_CHANGED" != existing ]; then
        managed_path_changed=1
        ensure_profile_path "$HOME/.profile"
        case "$LOGIN_SHELL_NAME" in
            bash|bash.exe)
                ensure_profile_path "$HOME/.bashrc"
                if [ -f "$HOME/.bash_profile" ]; then
                    ensure_profile_path "$HOME/.bash_profile"
                elif [ -f "$HOME/.bash_login" ]; then
                    ensure_profile_path "$HOME/.bash_login"
                fi
                ;;
            zsh)
                ensure_profile_path "$HOME/.zprofile"
                ensure_profile_path "$HOME/.zshrc"
                ;;
            fish)
                write_fish_path_config
                ;;
        esac
        [ -z "${USER_BIN_DIR:-}" ] || prepend_probe_path "$USER_BIN_DIR"
    fi
    FRESH_VERIFY_DIR=$(mktemp -d) || fail 24 "无法创建新 shell 工具复探临时目录"
    [ -d "$FRESH_VERIFY_DIR" ] && [ ! -L "$FRESH_VERIFY_DIR" ] || fail 24 "新 shell 工具复探临时目录不安全"
    fresh_verifier=$(mktemp "$FRESH_VERIFY_DIR/check.XXXXXX") || fail 24 "无法创建新 shell 工具复探脚本"
    fresh_launcher=$(mktemp "$FRESH_VERIFY_DIR/launch.XXXXXX") || fail 24 "无法创建新 shell 工具复探启动器"
    FRESH_VERIFY_FILE=$fresh_verifier
    {
        printf '%s\n' '#!/bin/sh'
        printf '%s\n' 'set -eu'
        printf '%s\n' 'check_afh_tool() {'
        printf '%s\n' '    afh_tool_name=$1'
        printf '%s\n' '    afh_expected_path=$2'
        printf '%s\n' '    afh_expected_version=$3'
        printf '%s\n' '    afh_resolved=$(command -v "$afh_tool_name") || { printf "ERROR_TOOL=%s\n" "$afh_tool_name"; exit 41; }'
        printf '%s\n' '    [ "$afh_resolved" = "$afh_expected_path" ] || { printf "ERROR_TOOL=%s\n" "$afh_tool_name"; exit 42; }'
        printf '%s\n' '    afh_actual_version=$("$afh_resolved" --version) || { printf "ERROR_TOOL=%s\n" "$afh_tool_name"; exit 43; }'
        printf '%s\n' '    [ "$afh_actual_version" = "$afh_expected_version" ] || { printf "ERROR_TOOL=%s\n" "$afh_tool_name"; exit 44; }'
        printf '%s\n' '    if [ "$afh_tool_name" = go ]; then'
        printf '%s\n' '        afh_actual_version=$("$afh_resolved" version) || { printf "ERROR_TOOL=%s\n" "$afh_tool_name"; exit 45; }'
        printf '%s\n' '        [ "$afh_actual_version" = "$afh_expected_version" ] || { printf "ERROR_TOOL=%s\n" "$afh_tool_name"; exit 45; }'
        printf '%s\n' '        afh_go_root=$("$afh_resolved" env GOROOT) || { printf "ERROR_TOOL=%s\n" "$afh_tool_name"; exit 45; }'
        printf '%s\n' '        [ "$afh_go_root" = "$AFH_EXPECTED_GOROOT" ] || { printf "ERROR_TOOL=%s\n" "$afh_tool_name"; exit 45; }'
        printf '%s\n' '    fi'
        printf '%s\n' '}'
        printf '%s\n' 'check_afh_tool git "$AFH_EXPECTED_GIT_PATH" "$AFH_EXPECTED_GIT"'
        printf '%s\n' 'check_afh_tool go "$AFH_EXPECTED_GO_PATH" "$AFH_EXPECTED_GO"'
        printf '%s\n' 'printf "PATH=%s\\n" "$PATH"'
    } > "$fresh_verifier" || fail 24 "无法创建新 shell 工具复探脚本"
    chmod 700 "$fresh_verifier" || fail 24 "无法保护新 shell 工具复探脚本"
    {
        printf '%s\n' '#!/bin/sh'
        printf '%s\n' 'set -eu'
        printf '%s\n' 'unset GOROOT'
        printf '%s\n' 'exec "$AFH_LOGIN_SHELL" -l -c "$AFH_LOGIN_COMMAND"'
    } > "$fresh_launcher" || fail 24 "无法创建新 shell 工具复探启动器"
    chmod 700 "$fresh_launcher" || fail 24 "无法保护新 shell 工具复探启动器"
    expected_git_path=$git_path
    expected_go_path=$go_path
    fresh_failure=0
    persisted_environment=$(
        AFH_LOGIN_SHELL=$LOGIN_SHELL \
        AFH_LOGIN_COMMAND='"$AFH_FRESH_VERIFY"' \
        AFH_FRESH_VERIFY=$fresh_verifier \
        AFH_EXPECTED_GIT_PATH=$expected_git_path \
        AFH_EXPECTED_GO_PATH=$expected_go_path \
        AFH_EXPECTED_GIT=$GIT_VERSION \
        AFH_EXPECTED_GO=$GO_VERSION \
        AFH_EXPECTED_GOROOT=$MANAGED_GOROOT \
        PATH=$FRESH_BASE_PATH \
        "$fresh_launcher" 2>/dev/null
    ) || fresh_failure=$?
    if [ "$fresh_failure" -ne 0 ]; then
        rm -f "$fresh_verifier"
        FRESH_VERIFY_FILE=
        fresh_failed_tool=$(printf '%s\n' "$persisted_environment" | awk -F= '$1 == "ERROR_TOOL" { print $2; exit }')
        fail 24 "新 shell 无法从持久 PATH 解析并执行同一受管工具 ${fresh_failed_tool:-unknown}（子进程退出码 ${fresh_failure}）"
    fi
    rm -f "$fresh_verifier" "$fresh_launcher" || fail 24 "无法清理新 shell 工具复探脚本"
    FRESH_VERIFY_FILE=
    rmdir "$FRESH_VERIFY_DIR" || fail 24 "无法清理新 shell 工具复探临时目录"
    FRESH_VERIFY_DIR=
    persisted_probe=$(printf '%s\n' "$persisted_environment" | awk -F= '$1 == "PATH" { sub(/^PATH=/, ""); print; exit }')
    if [ "$managed_path_changed" -eq 1 ]; then
        if [ "$GO_CHANGED" != existing ]; then
            case ":$persisted_probe:" in
                *":$GO_BIN_DIR:"*) ;;
                *) fail 24 "Go 当前用户 bin 写入后无法由新 shell 读取" ;;
            esac
        fi
    fi
    [ "$(sanitize_path "$persisted_probe")" = "$persisted_probe" ] || fail 24 "新 shell 的用户级 PATH 仍包含空段或重复项"
    FRESH_SHELL_STATUS=passed
}

git_path=$(find_tool git 2>/dev/null || true)
if [ -n "$git_path" ]; then
    validate_git "$git_path"
else
    GIT_VERSION=Missing
    GIT_STATUS=missing
fi

go_path=$(find_tool go 2>/dev/null || true)
if [ -n "$go_path" ]; then
    validate_go "$go_path"
else
    GO_VERSION=Missing
    GO_ROOT=Missing
    GO_PATH_DIR=Missing
    GO_MOD_CACHE=Missing
    GO_STATUS=missing
fi

if [ "$MODE" = check ]; then
    printf 'gate.git.status=%s\n' "$GIT_STATUS"
    printf 'gate.git.requirement=%s\n' "$GIT_REQUIREMENT"
    printf 'gate.git.version=%s\n' "$GIT_VERSION"
    printf 'gate.go.status=%s\n' "$GO_STATUS"
    printf 'gate.go.requirement=%s\n' "$GO_REQUIREMENT"
    printf 'gate.go.version=%s\n' "$GO_VERSION"
    printf 'gate.go.goroot=%s\n' "$GO_ROOT"
    printf 'gate.go.gopath=%s\n' "$GO_PATH_DIR"
    printf 'gate.go.gomodcache=%s\n' "$GO_MOD_CACHE"
    [ "$GIT_STATUS" = passed ] && [ "$GO_STATUS" = passed ] || exit 20
    exit 0
fi

# 受管用户级工具先完成全部只读目标预检，再从真实持久 login shell 精确复核本轮不变工具；
# 通过后才允许为 fish 新用户安全准备配置目录，瞬时 AFH_PREREQ_PATH 不得决定任何持久写入。
if [ "$GO_STATUS" != passed ]; then
    preflight_user_installation
    verify_persisted_passed_tools_before_write
    prepare_user_configuration_directories
elif [ "$GIT_STATUS" != passed ]; then
    validate_user_login_shell
    validate_durable_go_roots
    verify_persisted_passed_tools_before_write
fi

if [ "$GIT_STATUS" != passed ]; then
    git_change=upgraded
    [ "$GIT_STATUS" = missing ] && git_change=installed
    install_git "$git_change"
    git_path=$(find_tool git 2>/dev/null || true)
    [ -n "$git_path" ] || fail 29 "Git 安装完成后仍无法调用 git 可执行文件"
    validate_git "$git_path"
    [ "$GIT_STATUS" = passed ] || fail 29 "Git 安装或升级后仍低于门禁 ${GIT_REQUIREMENT}：$GIT_VERSION"
fi

if [ "$GO_STATUS" != passed ]; then
    go_change=upgraded
    [ "$GO_STATUS" = missing ] && go_change=installed
    install_go "$go_change"
    go_path=$(find_tool go 2>/dev/null || true)
    [ -n "$go_path" ] || fail 22 "Go 安装完成后仍无法调用 go 可执行文件"
    validate_go "$go_path"
    [ "$GO_STATUS" = passed ] || fail 22 "Go 安装或升级后仍低于门禁 ${GO_REQUIREMENT}：$GO_VERSION"
fi

if [ "$GIT_CHANGED" != existing ] || [ "$GO_CHANGED" != existing ]; then
    persist_user_tool_path
fi

changed=false
[ "$GIT_CHANGED" = existing ] || changed=true
[ "$GO_CHANGED" = existing ] || changed=true

printf 'gate.git.status=passed\n'
printf 'gate.git.requirement=%s\n' "$GIT_REQUIREMENT"
printf 'gate.git.version=%s\n' "$GIT_VERSION"
printf 'gate.git.change=%s\n' "$GIT_CHANGED"
printf 'gate.go.status=passed\n'
printf 'gate.go.requirement=%s\n' "$GO_REQUIREMENT"
printf 'gate.go.version=%s\n' "$GO_VERSION"
printf 'gate.go.goroot=%s\n' "$GO_ROOT"
printf 'gate.go.gopath=%s\n' "$GO_PATH_DIR"
printf 'gate.go.gomodcache=%s\n' "$GO_MOD_CACHE"
printf 'gate.go.change=%s\n' "$GO_CHANGED"
printf 'gate.changed=%s\n' "$changed"
printf 'gate.fresh_shell.status=%s\n' "$FRESH_SHELL_STATUS"
if [ -n "$GIT_BIN_DIR" ] || [ -n "$GO_BIN_DIR" ] || [ -n "${USER_BIN_DIR:-}" ]; then
    path_prepend=
    for candidate in "${USER_BIN_DIR:-}" "$GO_BIN_DIR" "$GIT_BIN_DIR"; do
        [ -n "$candidate" ] || continue
        case ":$path_prepend:" in
            *":$candidate:"*) ;;
            *) [ -n "$path_prepend" ] && path_prepend=$path_prepend:$candidate || path_prepend=$candidate ;;
        esac
    done
    printf 'gate.path.prepend=%s\n' "$path_prepend"
fi
