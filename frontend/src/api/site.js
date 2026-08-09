// 大陆公众站公开信息（阶段 6D-2）：只消费后端 /api/public/site 的公开字段。
// 该端点不返回任何密钥；前端也不持有或引用任何 API Key / MCP token。
import { API_BASE_URL } from "./config.js";

export const PUBLIC_SITE_URL = `${API_BASE_URL}/api/public/site`;

const DEFAULT_SITE = {
  public_launch_enabled: false,
  site_operator_name: "",
  site_contact_email: "",
  icp_filing_number: "",
  icp_filing_url: "",
  public_security_filing_number: "",
  public_security_filing_url: "",
  ai_model_display_name: "",
  ai_model_filing_number: "",
  ai_assisted_notice: "AI 辅助生成，须人工复核",
  privacy_policy_version: "",
  terms_version: "",
};

export async function fetchPublicSite() {
  const response = await fetch(PUBLIC_SITE_URL, {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`公开站点信息获取失败（HTTP ${response.status}）`);
  }
  const data = await response.json();
  return { ...DEFAULT_SITE, ...data };
}
