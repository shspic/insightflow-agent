import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchPublicSite } from "../api/site";
import { AuthPage } from "./Login";

function Placeholder({ label }) {
  return <span className="legal-placeholder">[{label}：待运营者填写]</span>;
}

// 用户协议（阶段 6D-2）：只描述系统实际行为，未知信息保留显式占位。
export default function LegalTerms() {
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
  const version = site?.terms_version || "";
  const launched = Boolean(site?.public_launch_enabled);

  return (
    <AuthPage title="用户协议" description="使用本服务前请阅读以下条款">
      <article className="legal-document">
        {!launched && (
          <p className="muted">
            当前站点尚未公开发布，本页面为协议模板；上线前由运营者完成全部信息配置。
          </p>
        )}
        <h2>一、服务说明</h2>
        <p>
          本服务为多模态文档与数据分析工具，向获得邀请码并注册的账号提供服务（邀请制，不开放自由注册）。
          运营主体：{operator || <Placeholder label="运营主体" />}。版本：{version || <Placeholder label="用户协议版本" />}。
        </p>

        <h2>二、账号与邀请制</h2>
        <p>
          注册采用邀请码机制，邀请码由管理员创建。您应妥善保管账号与密码，
          不得出借或转让账号；因账号保管不善导致的后果由您承担。
        </p>

        <h2>三、使用规范</h2>
        <ul>
          <li>您只能上传您有权处理的内容，不得上传无权处理的个人信息、商业秘密或敏感数据。</li>
          <li>不得利用本服务从事违法违规活动，不得尝试越权访问其他用户的工作区、文件或报告。</li>
          <li>系统生成的分析结果、审查发现与报告仅用于辅助决策，不构成自动合规判断；最终判断由专业人员作出。</li>
          <li>AI 辅助生成的内容（含报告、检索结果与候选证据）必须经人工复核后使用。</li>
        </ul>

        <h2>四、服务与结果边界</h2>
        <p>
          本服务可能使用人工智能模型辅助生成或规划内容。模型输出可能不准确或不完整，
          本服务不承诺结果完全准确。报告、检索结果与候选证据仅作为线索，
          使用前必须经具备相应权限的专业人员确认。
        </p>

        <h2>五、知识产权与数据</h2>
        <p>
          您上传的原始文件归您所有或由您合法持有；系统生成的报告与统计数据按版本化机制保存。
          数据处理方式详见<Link to="/legal/privacy">隐私政策</Link>。
        </p>

        <h2>六、免责与责任限制</h2>
        <p>
          本服务按"现状"提供，运营者对因模型输出、网络故障、第三方模型 API 不可用等原因
          造成的损失在适用法律允许的范围内承担有限责任。本协议不构成法律意见；具体合规事项请咨询专业机构。
        </p>

        <h2>七、联系我们</h2>
        <p>
          对本协议有任何疑问，请联系：{contact ? (
          <a href={`mailto:${contact}`}>{contact}</a>
        ) : (
          <Placeholder label="联系邮箱" />
        )}。
        </p>
      </article>
    </AuthPage>
  );
}
