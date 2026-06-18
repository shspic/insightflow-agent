import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from app.core.config import settings

SUPPORTED_TASK_TYPES = {
    "data_analysis",
    "chart_generation",
    "file_summary",
    "document_qa",
    "image_extract",
    "report_generation",
    "multi_file_analysis",
    "unsupported",
}

PLACEHOLDER_KEYS = {"", "your_api_key_here", "your_deepseek_api_key", "replace_me"}


@dataclass
class LLMResult:
    success: bool
    content: str | None = None
    message: str | None = None
    skipped: bool = False


def is_llm_ready() -> bool:
    return settings.llm_enabled and _has_real_api_key()


def call_llm(
    messages: list[dict[str, str]],
    temperature: float = 0.2,
    max_tokens: int = 800,
    timeout_seconds: int = 30,
) -> LLMResult:
    if not settings.llm_enabled:
        return LLMResult(success=False, skipped=True, message="LLM 已关闭，使用本地规则降级。")

    if not _has_real_api_key():
        return LLMResult(success=False, skipped=True, message="LLM_API_KEY 未配置，使用本地规则降级。")

    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    request = urllib.request.Request(
        _resolve_chat_url(),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.llm_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return LLMResult(success=False, message=f"LLM 调用失败：HTTP {exc.code}")
    except urllib.error.URLError as exc:
        return LLMResult(success=False, message=f"LLM 调用失败：{exc.reason}")
    except Exception as exc:
        return LLMResult(success=False, message=f"LLM 调用失败：{exc}")

    content = _extract_content(response_data)
    if not content:
        return LLMResult(success=False, message="LLM 返回内容为空。")

    return LLMResult(success=True, content=content.strip())


def classify_task_with_llm(user_input: str, file_type: str | None) -> LLMResult:
    result = call_llm(
        messages=[
            {
                "role": "system",
                "content": (
                    "你是任务分类器。只能从以下任务类型中选择一个返回："
                    "data_analysis、chart_generation、file_summary、document_qa、"
                    "image_extract、report_generation、multi_file_analysis、unsupported。"
                    "只返回任务类型字符串，不要解释。"
                ),
            },
            {
                "role": "user",
                "content": f"用户输入：{user_input}\n文件类型：{file_type or '未知'}",
            },
        ],
        temperature=0,
        max_tokens=40,
    )
    if not result.success:
        return result

    task_type = _normalize_task_type(result.content or "")
    if task_type not in SUPPORTED_TASK_TYPES:
        return LLMResult(success=False, message="LLM 返回了不支持的任务类型。")

    return LLMResult(success=True, content=task_type)


def build_plan_with_llm(user_input: str, task_type: str, fallback_plan: list[str]) -> LLMResult:
    result = call_llm(
        messages=[
            {
                "role": "system",
                "content": (
                    "你是 Agent 计划生成器。只能围绕现有工具能力生成计划，"
                    "不要编造新工具，不要生成代码，不要要求执行 Python。"
                    "请返回 JSON 数组，数组元素是简短中文步骤。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"任务类型：{task_type}\n"
                    f"用户输入：{user_input}\n"
                    f"固定计划参考：{json.dumps(fallback_plan, ensure_ascii=False)}"
                ),
            },
        ],
        temperature=0.2,
        max_tokens=300,
    )
    if not result.success:
        return result

    plan = _parse_plan(result.content or "")
    if not plan:
        return LLMResult(success=False, message="LLM 计划解析失败。")

    return LLMResult(success=True, content=json.dumps(plan, ensure_ascii=False))


def write_final_answer_with_llm(
    task_type: str,
    user_input: str,
    tool_results: dict[str, Any],
    fallback_answer: str,
) -> LLMResult:
    if task_type == "document_qa":
        return _write_rag_answer_with_llm(user_input, tool_results, fallback_answer)

    system_prompt = (
        "你是结果整理助手。只能基于工具结果生成中文回答，"
        "不得编造工具结果中没有的数据、文件、页码或图表。"
        "如果工具结果为空或包含失败信息，必须如实说明。"
    )
    result = call_llm(
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"任务类型：{task_type}\n"
                    f"用户输入：{user_input}\n"
                    f"工具结果：{safe_json_dumps(tool_results, max_length=6000)}\n"
                    f"本地模板回答：{fallback_answer}\n"
                    "请生成更自然但不夸大的中文 final_answer。"
                ),
            },
        ],
        temperature=0.3,
        max_tokens=900,
    )
    return result


def write_report_summary_with_llm(
    user_input: str,
    task_type: str,
    tool_results: dict[str, Any],
    fallback_summary: str,
) -> LLMResult:
    return call_llm(
        messages=[
            {
                "role": "system",
                "content": (
                    "你是报告结论助手。只生成 Markdown 报告中“结论与建议”部分的中文内容。"
                    "不要删除报告结构，不要编造数据，不要添加工具结果中没有的事实。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"用户输入：{user_input}\n"
                    f"任务类型：{task_type}\n"
                    f"已有工具结果：{safe_json_dumps(tool_results, max_length=5000)}\n"
                    f"降级结论：{fallback_summary}\n"
                    "请输出 2 到 4 条简洁结论或建议。"
                ),
            },
        ],
        temperature=0.3,
        max_tokens=600,
    )


def safe_json_dumps(value: Any, max_length: int = 4000) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= max_length:
        return text
    return text[:max_length] + "...（已截断）"


def _write_rag_answer_with_llm(user_input: str, tool_results: dict[str, Any], fallback_answer: str) -> LLMResult:
    retrieval = tool_results.get("pdf_retrieval_tool", {})
    sources = retrieval.get("sources") or []
    if not sources:
        return LLMResult(success=False, skipped=True, message="没有 PDF 检索结果，使用模板回答。")

    return call_llm(
        messages=[
            {
                "role": "system",
                "content": (
                    "你是 PDF 问答助手。只能依据提供的引用片段回答。"
                    "必须保留文件名、页码和引用片段，不得编造页码、文件名或不存在的内容。"
                    "如果片段不足以回答，需要明确说明信息不足。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"问题：{user_input}\n"
                    f"引用来源：{safe_json_dumps(sources, max_length=6000)}\n"
                    f"本地模板回答：{fallback_answer}\n"
                    "请生成中文回答，并在末尾列出引用来源。"
                ),
            },
        ],
        temperature=0.2,
        max_tokens=1000,
    )


def _resolve_chat_url() -> str:
    base_url = settings.llm_base_url.strip()
    if not base_url:
        if settings.llm_provider.lower() == "deepseek":
            return "https://api.deepseek.com/v1/chat/completions"
        return "https://api.openai.com/v1/chat/completions"

    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def _has_real_api_key() -> bool:
    return settings.llm_api_key.strip() not in PLACEHOLDER_KEYS


def _extract_content(response_data: dict[str, Any]) -> str | None:
    choices = response_data.get("choices")
    if not isinstance(choices, list) or not choices:
        return None

    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if isinstance(message, dict):
        content = message.get("content")
        return content if isinstance(content, str) else None

    text = choices[0].get("text") if isinstance(choices[0], dict) else None
    return text if isinstance(text, str) else None


def _normalize_task_type(value: str) -> str:
    text = value.strip().strip("`").strip()
    match = re.search(
        r"(data_analysis|chart_generation|file_summary|document_qa|image_extract|report_generation|multi_file_analysis|unsupported)",
        text,
    )
    return match.group(1) if match else text


def _parse_plan(content: str) -> list[str]:
    text = content.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None

    if isinstance(data, list):
        return [str(item).strip() for item in data if str(item).strip()][:8]

    lines = []
    for line in text.splitlines():
        cleaned = re.sub(r"^\s*[-*\d.、)）]+", "", line).strip()
        if cleaned:
            lines.append(cleaned)
    return lines[:8]
