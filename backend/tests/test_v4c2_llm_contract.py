"""阶段 4C-2 补修：llm_service 请求契约测试（官方 JSON 模式参数）。

使用 monkeypatch 捕获发送给 urllib.request.Request 的 JSON payload，
不访问真实网络。
"""

from __future__ import annotations

import json
from unittest import mock

import pytest

from app.services.llm_service import LLMResult, call_llm


@pytest.fixture
def _env_ok(monkeypatch):
    """模拟 LLM 可用环境（settings 为 frozen dataclass，用 object.__setattr__）。"""
    from app.core.config import settings

    for attr, value in (
        ("llm_enabled", True),
        ("llm_model", "deepseek-v4-pro"),
        ("llm_max_retries", 0),
    ):
        object.__setattr__(settings, attr, value)
    monkeypatch.setattr("app.services.llm_service._has_real_api_key", lambda: True)
    monkeypatch.setattr(
        "app.services.llm_service.model_configuration_issue", lambda: None
    )


def _fake_response_data(content="ok", finish_reason="stop", model="deepseek-v4-pro",
                        reasoning_content="secret-chain-of-thought", usage=None):
    data = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": content,
                    "reasoning_content": reasoning_content,
                },
                "finish_reason": finish_reason,
            }
        ],
        "model": model,
    }
    if usage:
        data["usage"] = usage
    return data


def _capture_payload(monkeypatch, response_data):
    """monkeypatch urlopen 捕获 payload 并返回模拟响应。"""
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(response_data).encode("utf-8")

    def fake_urlopen(request, timeout=30):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    return captured


class TestCallLlmContract:
    def test_legacy_call_no_new_fields(self, _env_ok, monkeypatch):
        """旧调用不传新参数时，payload 不含 thinking/response_format。"""
        captured = _capture_payload(
            monkeypatch, _fake_response_data(usage={"total_tokens": 5})
        )
        result = call_llm([{"role": "user", "content": "hi"}])
        assert result.success is True
        assert "thinking" not in captured["payload"]
        assert "response_format" not in captured["payload"]
        assert captured["payload"]["model"] == "deepseek-v4-pro"

    def test_verification_payload_includes_official_json_mode(self, _env_ok, monkeypatch):
        """Verification 调用包含 thinking=disabled + response_format=json_object。"""
        captured = _capture_payload(
            monkeypatch, _fake_response_data(usage={"total_tokens": 5})
        )
        result = call_llm(
            [{"role": "user", "content": "hi"}],
            temperature=0,
            max_tokens=2400,
            response_format="json_object",
            thinking="disabled",
        )
        assert result.success is True
        assert captured["payload"]["model"] == "deepseek-v4-pro"
        assert captured["payload"]["thinking"] == {"type": "disabled"}
        assert captured["payload"]["response_format"] == {"type": "json_object"}

    def test_invalid_thinking_rejected_before_network(self, _env_ok, monkeypatch):
        """非法 thinking 在网络前拒绝（urlopen 不被调用）。"""
        called = []

        def fake_urlopen(request, timeout=30):
            called.append(request)
            raise AssertionError("不应发起网络请求")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        result = call_llm([{"role": "user", "content": "hi"}], thinking="sometimes")
        assert result.success is False
        assert not called

    def test_invalid_response_format_rejected_before_network(self, _env_ok, monkeypatch):
        """非法 response_format 在网络前拒绝。"""
        called = []

        def fake_urlopen(request, timeout=30):
            called.append(request)
            raise AssertionError("不应发起网络请求")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        result = call_llm([{"role": "user", "content": "hi"}], response_format="xml")
        assert result.success is False
        assert not called

    def test_finish_reason_stop_read(self, _env_ok, monkeypatch):
        """finish_reason=stop 被读取到 LLMResult。"""
        _capture_payload(monkeypatch, _fake_response_data(finish_reason="stop"))
        result = call_llm([{"role": "user", "content": "hi"}])
        assert result.finish_reason == "stop"
        assert result.model == "deepseek-v4-pro"

    def test_finish_reason_length_read(self, _env_ok, monkeypatch):
        """finish_reason=length 被读取到 LLMResult。"""
        _capture_payload(monkeypatch, _fake_response_data(finish_reason="length"))
        result = call_llm([{"role": "user", "content": "hi"}])
        assert result.finish_reason == "length"

    def test_reasoning_content_not_exposed(self, _env_ok, monkeypatch):
        """reasoning_content 不进入 LLMResult（不持久化 Chain of Thought）。"""
        _capture_payload(
            monkeypatch,
            _fake_response_data(
                content="正式内容", reasoning_content="secret-chain-of-thought"
            ),
        )
        result = call_llm([{"role": "user", "content": "hi"}])
        assert result.content == "正式内容"
        dumped = json.dumps({
            "content": result.content,
            "message": result.message,
            "token_usage": result.token_usage,
            "finish_reason": result.finish_reason,
            "model": result.model,
        })
        assert "secret-chain-of-thought" not in dumped
        assert "reasoning_content" not in dumped

    def test_empty_content_reports_failure(self, _env_ok, monkeypatch):
        """空 content 返回 success=False（供 fallback 使用）。"""
        _capture_payload(monkeypatch, _fake_response_data(content=None))
        result = call_llm([{"role": "user", "content": "hi"}])
        assert result.success is False
        assert result.finish_reason == "stop"  # 仍记录 finish_reason 供判定

    def test_token_usage_read(self, _env_ok, monkeypatch):
        """token usage 正常读取。"""
        usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
        _capture_payload(monkeypatch, _fake_response_data(usage=usage))
        result = call_llm([{"role": "user", "content": "hi"}])
        assert result.token_usage == usage
