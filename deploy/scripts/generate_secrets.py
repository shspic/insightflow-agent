#!/usr/bin/env python3
import argparse
import secrets
import stat
from pathlib import Path


def replace_line(text: str, name: str, value: str) -> str:
    prefix = f"{name}="
    lines = text.splitlines()
    replaced = False
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            lines[index] = f"{prefix}{value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{prefix}{value}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="生成生产认证密钥和一次性管理员初始密码")
    parser.add_argument("--template", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--admin-password-file", required=True)
    args = parser.parse_args()

    template = Path(args.template).resolve()
    output = Path(args.output).resolve()
    password_file = Path(args.admin_password_file).resolve()
    if output.exists() or password_file.exists():
        raise SystemExit("目标已存在，拒绝覆盖现有生产密钥")
    if not template.is_file():
        raise SystemExit("环境模板不存在")

    output.parent.mkdir(parents=True, exist_ok=True)
    password_file.parent.mkdir(parents=True, exist_ok=True)
    # 两个密钥独立随机生成且互不相同（MCP token 是独立 HMAC 签名密钥）
    auth_key = secrets.token_urlsafe(48)
    mcp_token = secrets.token_urlsafe(48)
    while mcp_token == auth_key:
        mcp_token = secrets.token_urlsafe(48)
    env_text = replace_line(
        template.read_text(encoding="utf-8"),
        "AUTH_SECRET_KEY",
        auth_key,
    )
    env_text = replace_line(env_text, "ENGINEERING_MCP_INTERNAL_TOKEN", mcp_token)
    output.write_text(env_text, encoding="utf-8")
    password_file.write_text(f"If!{secrets.token_urlsafe(24)}\n", encoding="utf-8")
    output.chmod(stat.S_IRUSR | stat.S_IWUSR)
    password_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
    print(f"已创建生产环境文件：{output}")
    print(f"已创建一次性管理员密码文件：{password_file}")
    print("密钥内容未输出；请离线保存管理员密码并完成环境占位符替换。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
