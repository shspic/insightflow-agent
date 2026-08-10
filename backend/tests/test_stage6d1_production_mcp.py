"""阶段 6D-1：生产 MCP Server / Compose / 密钥 / 运维脚本专项测试。

离线（普通 pytest）：
- 不调用 DeepSeek / 不访问公网 / 不写默认 app.db/uploads/reports/retrieval
- 真实 Streamable HTTP MCP（子进程，allow_container_bind 容器网络模式）
- 真实 Host 头注入模拟 Docker 内网 mcp 主机名访问
- 生产安全校验 / 密钥生成脚本 / compose 与部署脚本文件契约

用户隔离、错误 token、过期 token、permanent failure、recovered retry
的完整场景由 test_v5a1_review_tools_mcp.py 与
test_v5a2_verification_mcp_integration.py 覆盖，本文件做容器绑定
模式下的认证回归与部署契约断言。
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import replace
from pathlib import Path

import httpx2
import pytest
import yaml
from sqlalchemy import create_engine

import app.models  # noqa: F401
from app.core.config import Settings, settings, validate_production_security
from app.db.base import Base
from app.mcp.capability_tokens import issue_capability_token
from app.mcp.healthcheck import mcp_healthcheck_ok, mcp_probe_ok
from app.mcp.review_tools_client import ReviewToolsMCPClient
from app.mcp.review_tools_server import (
    ALLOWED_MCP_TOOL_NAMES,
    MCP_CONTAINER_INTERNAL_HOST,
    build_transport_security,
    run_review_tools_server,
)
from app.services.health_service import readiness_details

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
DEPLOY_SCRIPTS = REPO_ROOT / "deploy" / "scripts"
GENERATE_SECRETS = DEPLOY_SCRIPTS / "generate_secrets.py"


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


# ── compose / 环境模板 / 部署脚本契约 ──────────────────────────────


@pytest.fixture(scope="module")
def compose_data() -> dict:
    return yaml.safe_load(read("docker-compose.prod.yml"))


class TestComposeServices:

    def test_compose_has_four_services(self, compose_data):
        services = compose_data["services"]
        assert set(services) == {"backend", "worker", "mcp", "web"}

    def test_mcp_has_no_ports(self, compose_data):
        assert "ports" not in compose_data["services"]["mcp"]

    def test_mcp_8765_not_published_to_host(self, compose_data):
        for name in ("backend", "worker", "mcp"):
            assert "ports" not in compose_data["services"][name], f"{name} 不应发布端口"
        web = compose_data["services"]["web"]
        assert web["ports"] == ["80:80", "443:443"]
        assert "8765" not in str(web)

    def test_mcp_uses_backend_image_and_exposes_internal_port(self, compose_data):
        mcp = compose_data["services"]["mcp"]
        assert mcp["image"] == "${INSIGHTFLOW_BACKEND_IMAGE:-insightflow-backend:local}"
        assert mcp["command"] == ["python", "-m", "app.mcp.run_review_tools_server"]
        assert mcp["expose"] == ["8765"]
        assert mcp["depends_on"]["backend"]["condition"] == "service_healthy"
        assert mcp["restart"] == "unless-stopped"
        assert "app.mcp.healthcheck" in mcp["healthcheck"]["test"]
        assert mcp["mem_limit"] == "512m"
        assert mcp["logging"]["options"]["max-size"] == "10m"
        assert mcp["read_only"] is True

    def test_backend_reaches_mcp_via_internal_url(self):
        env = read("deploy/.env.production.example")
        assert "ENGINEERING_MCP_ENABLED=true" in env
        assert "ENGINEERING_MCP_URL=http://mcp:8765/mcp" in env
        assert "ENGINEERING_MCP_TIMEOUT_SECONDS=15" in env
        assert "ENGINEERING_MCP_INTERNAL_TOKEN=replace_with_generated_secret" in env
        assert "ENGINEERING_MCP_ALLOW_CONTAINER_BIND=true" in env

    def test_allow_container_bind_default_off_in_code(self):
        assert settings.engineering_mcp_allow_container_bind is False


class TestDeployScriptsMcp:
    def test_deploy_starts_four_services_and_waits_mcp(self):
        deploy = read("deploy/scripts/deploy.sh")
        assert "compose up -d backend mcp worker" in deploy
        assert "wait_readiness 45" in deploy
        assert "wait_mcp_healthy 45" in deploy

    def test_upgrade_stops_and_starts_mcp(self):
        upgrade = read("deploy/scripts/upgrade.sh")
        assert "compose stop worker backend mcp" in upgrade
        assert "compose up -d backend mcp worker" in upgrade
        assert "wait_mcp_healthy 45" in upgrade

    def test_healthcheck_checks_mcp_container_and_real_availability(self):
        healthcheck = read("deploy/scripts/healthcheck.sh")
        assert "for service in backend worker mcp web" in healthcheck
        assert "app.mcp.healthcheck" in healthcheck
        assert "MCP 视图" in healthcheck  # readiness 不把 MCP 故障误报健康
        assert 'exit "${failures}"' in healthcheck

    def test_rollback_handles_mcp(self):
        rollback = read("deploy/scripts/rollback.sh")
        assert "compose stop worker backend mcp" in rollback
        assert "compose up -d backend mcp worker" in rollback
        assert "wait_mcp_healthy 45" in rollback

    def test_common_has_wait_mcp_healthy(self):
        common = read("deploy/scripts/common.sh")
        assert "wait_mcp_healthy()" in common
        assert "app.mcp.healthcheck" in common
        assert "--url http://127.0.0.1:8765/mcp" in common

    def test_scripts_fail_fast_on_missing_docker(self):
        for name in ("deploy.sh", "upgrade.sh", "healthcheck.sh"):
            script = read(f"deploy/scripts/{name}")
            assert "set -Eeuo pipefail" in script
            assert "require_command docker" in script


# ── 绑定安全（默认拒绝危险绑定；显式启用容器内部绑定）──────────────


class TestBindSecurity:
    def test_default_rejects_0_0_0_0(self):
        with pytest.raises(ValueError):
            run_review_tools_server(host="0.0.0.0", port=1)

    def test_default_bind_is_localhost(self):
        import inspect

        sig = inspect.signature(run_review_tools_server)
        assert sig.parameters["host"].default == "127.0.0.1"
        assert sig.parameters["allow_container_bind"].default is False

    def test_default_rejects_foreign_bind_host(self):
        with pytest.raises(ValueError):
            run_review_tools_server(host="192.168.1.5", port=1)

    def test_container_bind_allows_0_0_0_0(self, monkeypatch):
        called: dict = {}

        class FakeServer:
            def run(self, **kwargs):
                called["kwargs"] = kwargs

        monkeypatch.setattr(
            "app.mcp.review_tools_server.build_review_tools_mcp_server",
            lambda: FakeServer(),
        )
        run_review_tools_server(host="0.0.0.0", port=8765, allow_container_bind=True)
        assert called["kwargs"]["host"] == "0.0.0.0"
        security = called["kwargs"]["transport_security"]
        assert security.enable_dns_rebinding_protection is True
        assert f"{MCP_CONTAINER_INTERNAL_HOST}:*" in security.allowed_hosts

    def test_container_bind_still_rejects_foreign_host(self, monkeypatch):
        monkeypatch.setattr(
            "app.mcp.review_tools_server.build_review_tools_mcp_server",
            lambda: object(),
        )
        with pytest.raises(ValueError):
            run_review_tools_server(host="192.168.1.5", port=8765, allow_container_bind=True)

    def test_transport_security_uses_explicit_allowlists(self):
        local = build_transport_security(allow_container_bind=False)
        assert set(local.allowed_hosts) == {"127.0.0.1:*", "localhost:*", "[::1]:*"}
        assert f"{MCP_CONTAINER_INTERNAL_HOST}:*" not in local.allowed_hosts
        assert local.allowed_origins == [
            "http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*",
        ]
        container = build_transport_security(allow_container_bind=True)
        assert f"{MCP_CONTAINER_INTERNAL_HOST}:*" in container.allowed_hosts
        assert len(container.allowed_hosts) == 4
        # 不允许 * 全通配
        for allowed in (local, container):
            assert "*" not in (set(a.split(":")[0] for a in allowed.allowed_hosts)
                               | set(a.split(":")[0] for a in allowed.allowed_origins))
            assert not any(a == "*:*" or a == "*" for a in allowed.allowed_hosts)
            assert not any(a == "*:*" or a == "*" for a in allowed.allowed_origins)


# ── 容器网络模式：真实 MCP Server（0.0.0.0 绑定）+ Host 头注入 ──────


@pytest.fixture(scope="module")
def mcp_env_container(tmp_path_factory):
    """模块级：临时文件 DB + allow_container_bind 的 MCP Server 子进程。"""
    tmp_root = tmp_path_factory.mktemp("v6d1_mcp")
    db_path = tmp_root / "mcp.db"
    db_url = f"sqlite:///{db_path.as_posix()}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    engine.dispose()

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    secret = "v6d1-secret-" + uuid.uuid4().hex[:16]
    out_file = tmp_root / "server.log"

    server_code = (
        "import os, sys\n"
        f"sys.path.insert(0, {str(BACKEND_DIR)!r})\n"
        f"os.environ['DATABASE_URL'] = {db_url!r}\n"
        "os.environ['LLM_ENABLED'] = 'false'\n"
        "import app.models\n"
        "from app.mcp.review_tools_server import run_review_tools_server\n"
        f"run_review_tools_server(host='0.0.0.0', port={port}, "
        "streamable_http_path='/mcp', allow_container_bind=True)\n"
    )
    env = dict(os.environ)
    env["ENGINEERING_MCP_INTERNAL_TOKEN"] = secret
    env["ENGINEERING_MCP_ENABLED"] = "true"
    env["DATABASE_URL"] = db_url

    with open(out_file, "wb") as fout:
        proc = subprocess.Popen(
            [sys.executable, "-c", server_code], env=env, cwd=BACKEND_DIR,
            stdout=fout, stderr=subprocess.STDOUT,
        )
        ok = False
        for _ in range(80):
            if proc.poll() is not None:
                break
            try:
                sck = socket.create_connection(("127.0.0.1", port), timeout=1)
                sck.close()
                ok = True
                break
            except Exception:
                time.sleep(0.25)
        if not ok:
            log = open(out_file, encoding="utf-8", errors="replace").read()[:2000]
            proc.terminate()
            pytest.fail(f"MCP Server（容器绑定模式）未就绪: {log}")

    url = f"http://127.0.0.1:{port}/mcp"
    yield {"url": url, "secret": secret, "proc": proc, "out_file": out_file,
           "port": port, "db_url": db_url}

    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _cap_token(mcp_env_container, user_id: int = 7) -> str:
    return issue_capability_token(user_id, secret=mcp_env_container["secret"])


_INIT_PAYLOAD = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {
        "protocolVersion": "2026-07-28",
        "capabilities": {},
        "clientInfo": {"name": "v6d1-test", "version": "1"},
    },
}


def _post_with_host(mcp_env_container, host_header: str, auth_token: str | None,
                    token_kind: str = "capability") -> int:
    headers = {"Accept": "application/json, text/event-stream",
               "Host": host_header}
    if auth_token is not None:
        headers["Authorization"] = f"Bearer {auth_token}"
    return httpx2.post(
        mcp_env_container["url"], json=_INIT_PAYLOAD, headers=headers, timeout=10,
    ).status_code


class TestContainerNetworkSecurity:
    def test_internal_host_header_passes_host_check(self, mcp_env_container):
        """Host: mcp:<port> 通过 Host 允许列表（带有效 token 完整 initialize 成功）。"""
        host_header = f"{MCP_CONTAINER_INTERNAL_HOST}:{mcp_env_container['port']}"
        assert _post_with_host(
            mcp_env_container, host_header, _cap_token(mcp_env_container)) == 200

    def test_localhost_host_still_allowed(self, mcp_env_container):
        assert _post_with_host(
            mcp_env_container, f"127.0.0.1:{mcp_env_container['port']}",
            _cap_token(mcp_env_container)) == 200

    def test_evil_public_host_rejected_421(self, mcp_env_container):
        """公网域名 Host 头被 DNS rebinding 防护拒绝（421，需先过认证层）。"""
        for evil in ("evil.example.com", "mcp.example.com"):
            assert _post_with_host(
                mcp_env_container, evil, _cap_token(mcp_env_container)) == 421

    def test_container_bind_mode_rejects_wrong_token(self, mcp_env_container):
        assert _post_with_host(
            mcp_env_container,
            f"{MCP_CONTAINER_INTERNAL_HOST}:{mcp_env_container['port']}",
            "wrong-token") == 401

    def test_container_bind_mode_rejects_raw_secret(self, mcp_env_container):
        assert _post_with_host(
            mcp_env_container,
            f"{MCP_CONTAINER_INTERNAL_HOST}:{mcp_env_container['port']}",
            mcp_env_container["secret"]) == 401

    def test_container_bind_mode_rejects_expired_token(self, mcp_env_container):
        expired = issue_capability_token(
            7, secret=mcp_env_container["secret"],
            ttl_seconds=1, now=int(time.time()) - 100,
        )
        assert _post_with_host(
            mcp_env_container,
            f"{MCP_CONTAINER_INTERNAL_HOST}:{mcp_env_container['port']}",
            expired) == 401

    def test_real_discovery_via_internal_host(self, mcp_env_container):
        """模拟 backend 在 Docker 内网以 mcp 主机名访问并发现白名单工具。"""
        import asyncio

        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        port = mcp_env_container["port"]
        headers = {
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {_cap_token(mcp_env_container)}",
            "Host": f"{MCP_CONTAINER_INTERNAL_HOST}:{port}",
        }

        async def _discover():
            transport = streamable_http_client(
                mcp_env_container["url"],
                http_client=httpx2.AsyncClient(
                    headers=headers, timeout=httpx2.Timeout(10)),
            )
            async with transport as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
            return sorted(t.name for t in (result.tools or []))

        tools = asyncio.run(_discover())
        assert tools == sorted(ALLOWED_MCP_TOOL_NAMES)
        assert len(tools) == 2


class TestHealthcheckModule:
    def test_healthcheck_ok_on_live_server(self, mcp_env_container):
        assert mcp_healthcheck_ok(
            url=mcp_env_container["url"], timeout_seconds=10,
            internal_token=mcp_env_container["secret"]) is True

    def test_probe_ok_on_live_server(self, mcp_env_container):
        assert mcp_probe_ok(url=mcp_env_container["url"], timeout_seconds=10) is True

    def test_healthcheck_fails_on_dead_server(self, tmp_path):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        dead_port = sock.getsockname()[1]
        sock.close()
        assert mcp_healthcheck_ok(
            url=f"http://127.0.0.1:{dead_port}/mcp", timeout_seconds=2,
            internal_token="test-secret-for-dead-server-check") is False
        assert mcp_probe_ok(
            url=f"http://127.0.0.1:{dead_port}/mcp", timeout_seconds=2) is False

    def test_healthcheck_false_when_no_signing_key(self, mcp_env_container):
        assert mcp_healthcheck_ok(url=mcp_env_container["url"], timeout_seconds=10) is False

    def test_cli_exit_codes(self, mcp_env_container, monkeypatch):
        from app.mcp import healthcheck as hc_mod

        monkeypatch.setattr(
            hc_mod, "mcp_healthcheck_ok",
            lambda url=None, timeout_seconds=5.0, internal_token=None: True,
        )
        assert hc_mod.main(["--url", mcp_env_container["url"], "--timeout", "10"]) == 0
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        dead_port = sock.getsockname()[1]
        sock.close()
        monkeypatch.setattr(
            hc_mod, "mcp_healthcheck_ok",
            lambda url=None, timeout_seconds=5.0, internal_token=None: False,
        )
        assert hc_mod.main(["--url", f"http://127.0.0.1:{dead_port}/mcp", "--timeout", "2"]) == 1

    def test_cli_output_has_no_token(self, mcp_env_container, monkeypatch, capsys):
        from app.mcp import healthcheck as hc_mod

        monkeypatch.setattr(
            hc_mod, "mcp_healthcheck_ok",
            lambda url=None, timeout_seconds=5.0, internal_token=None: True,
        )
        assert hc_mod.main(["--url", mcp_env_container["url"], "--timeout", "10"]) == 0
        captured = capsys.readouterr()
        assert mcp_env_container["secret"] not in captured.out
        assert mcp_env_container["secret"] not in captured.err
        assert "MCP 健康检查通过" in captured.out

    def test_healthcheck_token_has_no_business_authority(self, mcp_env_container):
        """健康检查专用 subject(0) 的 token 无法访问任何 workspace/run。"""
        client = ReviewToolsMCPClient(
            url=mcp_env_container["url"],
            internal_token=issue_capability_token(0, secret=mcp_env_container["secret"]),
            timeout_seconds=10, require_enabled=False,
        )
        from app.mcp.errors import MCPError, MCPErrorCode

        with pytest.raises(MCPError) as exc:
            client.call_tool_sync("search_review_rules", {
                "workspace_id": 1, "review_run_id": 1,
                "query": "x", "top_k": 3, "request_id": "r1",
            })
        assert exc.value.code == MCPErrorCode.REQUEST_INVALID


# ── backend readiness 的 MCP 视图 ─────────────────────────────────


class TestReadinessMcp:
    def _set_mcp(self, enabled: bool, url: str, token: str):
        object.__setattr__(settings, "engineering_mcp_enabled", enabled)
        object.__setattr__(settings, "engineering_mcp_url", url)
        object.__setattr__(settings, "engineering_mcp_internal_token", token)

    def _restore(self, enabled: bool, url: str, token: str):
        self._set_mcp(enabled, url, token)

    def test_readiness_degraded_when_mcp_unreachable(self, db_session, monkeypatch):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        dead_port = sock.getsockname()[1]
        sock.close()
        original = (settings.engineering_mcp_enabled, settings.engineering_mcp_url,
                    settings.engineering_mcp_internal_token)
        try:
            self._set_mcp(True, f"http://127.0.0.1:{dead_port}/mcp",
                          "test-readiness-secret-with-enough-entropy")
            details = readiness_details(db_session)
        finally:
            self._restore(*original)
        assert details["checks"]["mcp"]["status"] == "degraded"
        assert details["status"] != "ready", "永久 MCP 故障不得误报为完全健康"

    def test_readiness_ok_when_mcp_healthy(self, db_session, mcp_env_container):
        original = (settings.engineering_mcp_enabled, settings.engineering_mcp_url,
                    settings.engineering_mcp_internal_token)
        try:
            self._set_mcp(True, mcp_env_container["url"], mcp_env_container["secret"])
            details = readiness_details(db_session)
        finally:
            self._restore(*original)
        assert details["checks"]["mcp"]["status"] == "ok"

    def test_readiness_no_mcp_key_when_disabled(self, db_session):
        original = (settings.engineering_mcp_enabled, settings.engineering_mcp_url,
                    settings.engineering_mcp_internal_token)
        try:
            self._set_mcp(False, "http://127.0.0.1:8765/mcp", "")
            details = readiness_details(db_session)
        finally:
            self._restore(*original)
        assert "mcp" not in details["checks"]

    def test_readiness_response_has_no_token(self, db_session, mcp_env_container):
        original = (settings.engineering_mcp_enabled, settings.engineering_mcp_url,
                    settings.engineering_mcp_internal_token)
        try:
            self._set_mcp(True, mcp_env_container["url"], mcp_env_container["secret"])
            details = readiness_details(db_session)
        finally:
            self._restore(*original)
        text = json.dumps(details, ensure_ascii=False)
        assert mcp_env_container["secret"] not in text


# ── 生产安全校验（MCP 部分）────────────────────────────────────────


def production_settings(**changes) -> Settings:
    base = replace(
        settings,
        env="production",
        auth_secret_key="6gT!4zQp9#Lm2@Rx7$Vn8^Ks3&Yw5*Ha",
        auth_cookie_secure=True,
        enable_legacy_v1_api=False,
        debug=False,
        trust_proxy_headers=True,
        trusted_proxy_ips="172.30.0.10",
        enable_hsts=True,
        cors_origins_raw="https://insightflow.test.cn",
        public_site_url="https://insightflow.test.cn",
        database_url="sqlite:////app/data/insightflow.db",
        upload_dir="/app/storage/uploads",
        chart_dir="/app/storage/charts",
        report_dir="/app/storage/reports",
        backup_dir="/app/backups",
        sqlite_journal_mode="WAL",
        sqlite_busy_timeout_ms=30000,
        engineering_mcp_enabled=True,
        engineering_mcp_internal_token="7xKp!9Qw2#Lm4@Rt6$Yn8^Cv3&Zh5*Bgh",
        engineering_mcp_url="http://mcp:8765/mcp",
        engineering_mcp_allow_container_bind=True,
    )
    return replace(base, **changes)


class TestProductionSecurityMcp:
    def test_hardened_settings_accepted(self):
        validate_production_security(production_settings())

    def test_localhost_mcp_url_without_container_bind_rejected(self):
        with pytest.raises(RuntimeError, match="ENGINEERING_MCP_ALLOW_CONTAINER_BIND"):
            validate_production_security(production_settings(
                engineering_mcp_allow_container_bind=False))

    @pytest.mark.parametrize(
        ("changes", "message"),
        [
            ({"engineering_mcp_internal_token": "short-token"}, "32 个字符"),
            ({"engineering_mcp_internal_token":
              "replace_with_generated_secret_xxxxxxxxxxxx"}, "占位符"),
            ({"engineering_mcp_internal_token": "change_me_please_x" * 3}, "占位符"),
            ({"engineering_mcp_internal_token":
              "your_secret_here_12345678901234_xx"}, "占位符"),
            ({"engineering_mcp_internal_token": "a" * 40}, "随机性"),
        ],
    )
    def test_weak_tokens_rejected(self, changes, message):
        with pytest.raises(RuntimeError, match=message):
            validate_production_security(production_settings(**changes))

    @pytest.mark.parametrize(
        "url",
        [
            "https://mcp.example.com/mcp",
            "http://mcp.example.com/mcp",
            "https://api.deepseek.com/v1",
            "http://8.8.8.8:8765/mcp",
            "http://10.0.0.1:8765/mcp",
            "http://backend.mcp.io:8765/mcp",
            "http://:8765/mcp",
        ],
    )
    def test_public_or_foreign_urls_rejected(self, url):
        with pytest.raises(RuntimeError, match="受控内部地址"):
            validate_production_security(production_settings(
                engineering_mcp_url=url))

    def test_disabled_keeps_legacy_behavior(self):
        """ENABLED=false 时跳过 MCP 校验（弱 token + 公网 URL 均不拦截）。"""
        validate_production_security(production_settings(
            engineering_mcp_enabled=False,
            engineering_mcp_internal_token="",
            engineering_mcp_url="https://public.example.com/mcp",
            engineering_mcp_allow_container_bind=False,
        ))

    def test_config_defaults_safe(self):
        assert settings.engineering_mcp_enabled is False
        assert settings.engineering_mcp_url == "http://127.0.0.1:8765/mcp"
        assert settings.engineering_mcp_timeout_seconds == 15.0
        assert settings.engineering_mcp_internal_token == ""


# ── generate_secrets.py ────────────────────────────────────────────


class TestGenerateSecrets:
    def _template(self, tmp_path: Path) -> Path:
        template = tmp_path / "env.template"
        template.write_text(
            "ENV=production\n"
            "AUTH_SECRET_KEY=replace_with_generated_high_entropy_secret\n"
            "ENGINEERING_MCP_INTERNAL_TOKEN=replace_with_generated_secret\n"
            "OTHER_KEEP=value\n",
            encoding="utf-8",
        )
        return template

    @staticmethod
    def _decode(data: bytes) -> str:
        """跨平台解码子进程输出：先 UTF-8 后 GBK（Windows 控制台默认编码）。"""
        for encoding in ("utf-8", "gbk"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="replace")

    def _run(self, template: Path, output: Path, password_file: Path):
        result = subprocess.run(
            [sys.executable, str(GENERATE_SECRETS),
             "--template", str(template),
             "--output", str(output),
             "--admin-password-file", str(password_file)],
            capture_output=True, timeout=60,
        )
        result.stdout = self._decode(result.stdout)
        result.stderr = self._decode(result.stderr)
        return result

    def test_two_keys_generated_distinct_and_secret(self, tmp_path):
        output = tmp_path / "env.production"
        pw = tmp_path / "admin.pw"
        result = self._run(self._template(tmp_path), output, pw)
        assert result.returncode == 0, result.stderr
        text = output.read_text(encoding="utf-8")
        auth_key = re.search(r"^AUTH_SECRET_KEY=(.*)$", text, re.M).group(1)
        mcp_token = re.search(
            r"^ENGINEERING_MCP_INTERNAL_TOKEN=(.*)$", text, re.M).group(1)
        assert auth_key.startswith("replace_") is False
        assert mcp_token.startswith("replace_") is False
        assert len(auth_key) >= 32 and len(mcp_token) >= 32
        assert auth_key != mcp_token, "两个密钥不得相同"
        assert "OTHER_KEEP=value" in text

    def test_stdout_has_no_keys(self, tmp_path):
        output = tmp_path / "env.production"
        pw = tmp_path / "admin.pw"
        result = self._run(self._template(tmp_path), output, pw)
        text = output.read_text(encoding="utf-8")
        for key in ("AUTH_SECRET_KEY=", "ENGINEERING_MCP_INTERNAL_TOKEN="):
            value = re.search(rf"^{re.escape(key)}(.*)$", text, re.M).group(1)
            assert value not in result.stdout, "stdout 泄漏密钥"
            assert value not in result.stderr, "stderr 泄漏密钥"

    def test_refuses_to_overwrite_existing(self, tmp_path):
        output = tmp_path / "env.production"
        output.write_text("EXISTING=1\n", encoding="utf-8")
        pw = tmp_path / "admin.pw"
        result = self._run(self._template(tmp_path), output, pw)
        assert result.returncode != 0
        assert "拒绝覆盖" in result.stderr

    def test_no_fixed_keys_between_runs(self, tmp_path):
        values: dict[str, set[str]] = {"auth": set(), "mcp": set()}
        for index in range(2):
            out = tmp_path / f"env-{index}.production"
            pw = tmp_path / f"admin-{index}.pw"
            result = self._run(self._template(tmp_path), out, pw)
            assert result.returncode == 0
            text = out.read_text(encoding="utf-8")
            values["auth"].add(re.search(r"^AUTH_SECRET_KEY=(.*)$", text, re.M).group(1))
            values["mcp"].add(re.search(
                r"^ENGINEERING_MCP_INTERNAL_TOKEN=(.*)$", text, re.M).group(1))
        assert len(values["auth"]) == 2, "两次生成 AUTH_SECRET_KEY 相同（固定密钥）"
        assert len(values["mcp"]) == 2, "两次生成 MCP token 相同（固定密钥）"

    def test_file_permissions_restricted(self, tmp_path):
        if os.name == "nt":
            pytest.skip("Windows 不强制 POSIX 权限位")
        output = tmp_path / "env.production"
        pw = tmp_path / "admin.pw"
        result = self._run(self._template(tmp_path), output, pw)
        assert result.returncode == 0
        for path in (output, pw):
            mode = path.stat().st_mode & 0o777
            assert mode == 0o600, f"权限应为 0600，实际 {oct(mode)}"
