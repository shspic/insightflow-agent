import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchPublicSite } from "../api/site";
import { AuthPage } from "./Login";

// 隐私政策（阶段 6D-2）。
// 内容只描述系统实际具备的能力；未知信息（如运营者实际保存期限承诺）
// 保留显式配置占位，不虚构。上线门禁（PUBLIC_LAUNCH_ENABLED=true）要求
// 运营主体、联系邮箱、隐私政策版本等必填项完整。
function Placeholder({ label }) {
  return <span className="legal-placeholder">[{label}：待运营者填写]</span>;
}

export default function LegalPrivacy() {
  const [site, setSite] = useState(null);

  useEffect(() => {
    let cancelled = false;
    fetchPublicSite()
      .then((data) => {
        if (!cancelled) setSite(data);
      })
      .catch(() => {
        if (!cancelled) setSite(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const operator = site?.site_operator_name || "";
  const contact = site?.site_contact_email || "";
  const version = site?.privacy_policy_version || "";
  const launched = Boolean(site?.public_launch_enabled);

  return (
    <AuthPage title="隐私政策" description="我们如何处理您上传的文件与使用数据">
      <article className="legal-document">
        {!launched && (
          <p className="muted">
            当前站点尚未公开发布，本页面为政策模板；上线前由运营者完成全部信息配置。
          </p>
        )}
        <h2>一、适用范围</h2>
        <p>
          本政策适用于 InsightFlow Agent 网站（以下称“本服务”）。本服务为多模态文档与数据分析工具，
          供获得邀请码并注册的账号使用。运营主体：{operator || <Placeholder label="运营主体" />}。
          版本：{version || <Placeholder label="隐私政策版本" />}。
        </p>

        <h2>二、我们收集的数据与用途</h2>
        <h3>1. 您上传的文件</h3>
        <p>
          本服务支持上传 Excel、CSV、PDF、图片（以及系统支持的文档格式）等文件。
          文件仅用于完成您提交的分析、审查、检索与报告生成任务，包括：解析文件内容、
          建立检索索引、执行审查与核验、生成报告。上传文件受大小与数量限制，由部署配置控制。
        </p>
        <h3>2. 账号与登录数据</h3>
        <p>
          为提供账号服务，我们处理您的用户名、密码（以安全哈希形式存储）、会话与安全凭证，
          用于身份认证、权限控制与登录安全（含登录失败限流）。
        </p>
        <h3>3. 日志数据</h3>
        <p>
          为保障服务安全与审计需要，我们记录操作日志（如登录、上传、任务执行、报告生成、
          管理操作），用于故障排查、安全事件调查与滥用防护。日志不包含您的密码与密钥。
        </p>
        <h3>4. 模型调用数据</h3>
        <p>
          当您使用依赖大语言模型的功能（如智能核验中的模型规划）时，任务相关内容（如审查结论摘要、
          规则信息与检索查询）会发送至本服务配置的第三方模型 API（默认 DeepSeek），
          用于生成计划与查询。是否启用模型调用由部署配置控制。
        </p>

        <h2>三、是否向第三方模型 API 发送数据</h2>
        <p>
          是。当模型调用功能启用时，前述"模型调用数据"一节所述内容会发送至配置的第三方模型 API；
          您的密码、会话凭证、内部密钥等绝不发送给第三方模型服务。发送范围以部署配置为准。
        </p>

        <h2>四、数据保存期限</h2>
        <p>
          文件、任务、报告与审计记录在本服务数据库中保存。系统按部署配置执行日志与记录的保留期清理
          （如会话记录、事件日志、审计记录等均有配置化保留天数）。具体保存期限以运营者实际配置为准：
          <Placeholder label="数据保存期限说明" />。
        </p>

        <h2>五、数据的删除方式</h2>
        <p>
          您可以通过工作区管理功能删除工作区（系统设有宽限期，宽限期内可恢复），
          删除后相关文件、任务与报告从系统中移除；报告版本按版本化机制管理，历史版本不可变。
          删除处理的具体流程与恢复窗口以运营者配置为准：<Placeholder label="删除流程说明" />。
        </p>

        <h2>六、您不得上传的内容</h2>
        <p>
          您不得上传无权处理的个人信息、商业秘密、国家秘密和法律法规禁止处理的其他敏感数据。
          如您上传的内容包含他人个人信息，您应保证已取得合法授权。因违规上传导致的后果由您自行承担。
        </p>

        <h2>七、联系我们与投诉</h2>
        <p>
          如对本政策或数据处理有疑问、意见或投诉，请联系：{contact ? (
          <a href={`mailto:${contact}`}>{contact}</a>
        ) : (
          <Placeholder label="联系邮箱" />
        )}。
        </p>

        <h2>八、政策更新</h2>
        <p>
          本政策版本更新时将在本页面公布。重大变更将通过站内可见方式提示。
          本政策不构成法律意见；具体合规事项请咨询专业机构。
          相关页面：<Link to="/legal/terms">用户协议</Link> ·{" "}
          <Link to="/legal/ai-disclosure">AI 辅助功能说明</Link>
        </p>
      </article>
    </AuthPage>
  );
}
