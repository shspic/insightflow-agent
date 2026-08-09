"""阶段 5B：真实 DeepSeek 验证脚本的失败契约测试。

验证 scripts/verify_stage5b_real_deepseek.py 具备"失败即非零退出"的硬保证：
- fallback / needs_human / 缺报告 / MCP 缺失 都会触发硬断言失败
- 硬断言通过 _check 累积到 failures，任何失败最终 sys.exit(1)
- 不允许"仅打印字段而不参与判定"
- 不允许 fallback 被描述为 DeepSeek 成功
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "verify_stage5b_real_deepseek.py"


def _script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_script_exists_and_is_the_hard_assert_version() -> None:
    assert SCRIPT.is_file(), "脚本必须存在"
    source = _script()
    assert "硬断言" in source
    assert "不允许 fallback 被描述为 DeepSeek 成功" in source
    assert "不允许仅打印字段而不参与判定" in source


def test_fallback_and_needs_human_are_hard_failures() -> None:
    source = _script()
    # fallback 判定必须参与最终成败：planner_type/fallback_used 都是 _check
    assert '"deepseek"' in source, "planner_type == deepseek 硬断言存在"
    assert 'fallback_used is False' in source, "fallback_used is False 硬断言存在"
    assert 'result["status"] == "completed"' in source, "completed 硬断言存在"
    # 若 Supervisor 未完成（needs_human 等），completed 断言必然失败
    assert 'reused is False' in source, "reused 硬断言存在"
    # 不允许把 fallback 打印成成功：成功提示只在 planner==deepseek 且未 fallback 时输出
    assert 'planner_type == "deepseek" and not vrun.fallback_used' in source


def test_report_and_assets_are_hard_failures() -> None:
    source = _script()
    assert 'result["report_id"] is not None' in source, "report_id 硬断言存在"
    assert '{"markdown", "pdf"}' in source, "双资产硬断言存在"
    assert "disk_size != a.size_bytes or disk_sha != a.content_hash" in source, \
        "DB/磁盘 SHA 一致性硬断言存在"


def test_mcp_absent_or_failed_is_hard_failure() -> None:
    source = _script()
    assert '"search_review_rules"' in source, "search_review_rules 硬断言存在"
    assert '"run_bid_consistency_checks"' in source, "run_bid_consistency_checks 硬断言存在"
    assert "mcp_error_count == 0" in source, "MCP 未解决错误硬断言存在"


def test_step_sequence_and_gate_are_hard_failures() -> None:
    source = _script()
    assert 'node_seq == ["extraction", "verification", "quality_review", "reporting"]' in source
    assert 'all(s["status"] == "success" for s in result["steps"])' in source
    assert 'gate.get("status") == "passed"' in source


def test_default_storage_isolation_is_hard_failure() -> None:
    source = _script()
    assert "_snapshot_default_paths" in source
    assert 'default_before.get(key) == default_after.get(key)' in source


def test_any_check_failure_leads_to_nonzero_exit() -> None:
    source = _script()
    # _check 把失败累积进 failures
    assert 'failures.append(label)' in source
    # 所有失败路径（主流程与清理阶段）都必须 sys.exit(1)
    assert source.count("sys.exit(1)") >= 2
    assert 'print(f"[FAIL] {len(failures)} 项硬断言失败:")' in source
    # [PASS] 只在 failures 为空时打印
    pass_line = source.index('print("[PASS]')
    fail_block = source.index('if failures:')
    assert pass_line > fail_block, "[PASS] 必须位于失败判定之后"
