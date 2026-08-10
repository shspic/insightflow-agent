"""大陆公众站公开信息 API（阶段 6D-2）。

GET /api/public/site：无认证公开端点，只返回需要公开的字段：
- 运营主体与联系/投诉邮箱
- ICP 备案号与链接（工信部备案管理系统）
- 公安联网备案号（允许为空 = 办理期限内，不伪造号码）与平台链接
- AI 辅助生成标识配置（模型显示名、模型备案号可空、固定提示文案）
- 隐私政策 / 用户协议版本

绝不返回任何密钥：AUTH_SECRET_KEY、ENGINEERING_MCP_INTERNAL_TOKEN、
DEEPSEEK_API_KEY 等任何凭证字段都不在此端点出现。
private/prelaunch 模式（PUBLIC_LAUNCH_ENABLED=false）下运营与备案字段返回空字符串，
前端按"未公开"处理，不显示伪造信息。
"""

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(prefix="/api/public", tags=["public"])


@router.get("/site")
def public_site_config() -> dict:
    return {
        "public_launch_enabled": settings.public_launch_enabled,
        "site_operator_name": settings.site_operator_name if settings.public_launch_enabled else "",
        "site_contact_email": settings.site_contact_email if settings.public_launch_enabled else "",
        "icp_filing_number": settings.icp_filing_number if settings.public_launch_enabled else "",
        "icp_filing_url": settings.icp_filing_url if settings.public_launch_enabled else "",
        "public_security_filing_number": (
            settings.public_security_filing_number if settings.public_launch_enabled else ""
        ),
        "public_security_filing_url": (
            settings.public_security_filing_url if settings.public_launch_enabled else ""
        ),
        # AI 标识是生成内容标识义务，与是否公开上线无关，始终返回
        "ai_model_display_name": settings.ai_model_display_name,
        "ai_model_filing_number": settings.ai_model_filing_number,
        "ai_assisted_notice": settings.ai_assisted_notice,
        "privacy_policy_version": (
            settings.privacy_policy_version if settings.public_launch_enabled else ""
        ),
        "terms_version": settings.terms_version if settings.public_launch_enabled else "",
    }
