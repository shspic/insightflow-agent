import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchPublicSite } from "../api/site";

// 全站页脚（阶段 6D-2）：
// - ICP 备案号仅在配置提供时显示，并链接工信部备案管理系统（信息产业部 33 号令第十三条）
// - 公安联网备案：未提供号码时显示"办理中"明确状态，不伪造号码
// - 运营主体与联系/投诉邮箱来自配置；private 模式不显示
// - AI 辅助生成标识始终显示（生成内容标识义务，与是否公开上线无关）
export default function SiteFooter() {
  const [site, setSite] = useState(null);

  useEffect(() => {
    let cancelled = false;
    fetchPublicSite()
      .then((data) => {
        if (!cancelled) setSite(data);
      })
      .catch(() => {
        if (!cancelled) setSite({ public_launch_enabled: false });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!site) {
    return <footer className="site-footer" aria-label="页脚"><div className="site-footer__inner muted">加载站点信息…</div></footer>;
  }

  const { public_launch_enabled: launched } = site;
  const hasIcp = launched && Boolean(site.icp_filing_number);
  const hasSecurity = launched && Boolean(site.public_security_filing_number);

  return (
    <footer className="site-footer" aria-label="页脚">
      <div className="site-footer__inner">
        <div className="site-footer__row">
          {launched && site.site_operator_name && (
            <span className="site-footer__item">
              运营主体：{site.site_operator_name}
            </span>
          )}
          {launched && site.site_contact_email && (
            <a className="site-footer__item" href={`mailto:${site.site_contact_email}`}>
              联系 / 投诉：{site.site_contact_email}
            </a>
          )}
          {hasIcp ? (
            <a
              className="site-footer__item"
              href={site.icp_filing_url}
              target="_blank"
              rel="noopener noreferrer"
            >
              {site.icp_filing_number}
            </a>
          ) : (
            launched && <span className="site-footer__item muted">ICP 备案信息待补充</span>
          )}
          {launched && (
            hasSecurity ? (
              <a
                className="site-footer__item"
                href={site.public_security_filing_url}
                target="_blank"
                rel="noopener noreferrer"
              >
                {site.public_security_filing_number}
              </a>
            ) : (
              <span className="site-footer__item muted">
                公安联网备案办理中（法定办理期限内）
              </span>
            )
          )}
        </div>
        <div className="site-footer__row">
          <Link className="site-footer__item" to="/legal/privacy">隐私政策</Link>
          <Link className="site-footer__item" to="/legal/terms">用户协议</Link>
          <Link className="site-footer__item" to="/legal/ai-disclosure">AI 辅助功能说明</Link>
          <span className="site-footer__item muted">
            {site.ai_assisted_notice || "AI 辅助生成，须人工复核"}
          </span>
        </div>
      </div>
    </footer>
  );
}
