import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchPublicSite } from "../api/site";
import { AuthPage } from "./Login";

function Placeholder({ label }) {
  return <span className="legal-placeholder">[{label}：待运营者填写]</span>;
}

// AI 辅助功能说明（阶段 6D-2）。
// 依据《人工智能生成合成内容标识办法》（国信办通字〔2025〕2 号）向用户说明
// 本服务中 AI 参与生成/规划的内容、显式标识方式与人工复核义务。
export default function LegalAiDisclosure() {
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

  const modelName = site?.ai_model_display_name || "";
  const modelFiling = site?.ai_model_filing_number || "";
  const notice = site?.ai_assisted_notice || "AI 辅助生成，须人工复核";

  return (
    <AuthPage title="AI 辅助功能说明" description="本服务中人工智能参与的内容与标识方式">
      <article className="legal-document">
        <h2>一、本服务如何使用人工智能</h2>
        <p>
          本服务的智能核验（Verification Agent）与监督编排（Supervisor）等环节
          可能使用大语言模型辅助生成检索计划与查询。参与生成/规划的模型：
          {modelName || <Placeholder label="模型显示名" />}。
          {modelFiling && <>模型/生成式 AI 服务备案号：{modelFiling}。</>}
          {!modelFiling && (
            <span className="muted"> 模型备案信息待补充（备案办理中）。</span>
          )}
        </p>

        <h2>二、AI 辅助生成的内容与标识</h2>
        <ul>
          <li>
            智能核验页面与报告页面显示固定提示：
            <strong>{notice}</strong>。
          </li>
          <li>
            生成的 Markdown 与 PDF 报告包含可见的 AI 辅助生成声明
            （报告中"报告声明"一节），声明不承诺结果完全准确，
            并明确检索结果与候选证据须经专业人员人工确认后方可采信。
          </li>
          <li>
            智能核验的候选证据仅在人工接受后才成为正式证据；
            接受候选不会自动确认问题、降低风险或修改结论。
          </li>
        </ul>

        <h2>三、人工复核义务</h2>
        <p>
          本服务中所有 AI 参与生成/规划的内容均须人工复核后再行使用。
          报告、审查结论与证据定位仅用于辅助审查、风险提示与证据检索，
          不构成自动合规判断或投标有效性认定；最终由具备相应权限的专业人员确认。
        </p>

        <h2>四、合规说明</h2>
        <p>
          本页面依据《人工智能生成合成内容标识办法》等现行规定提供可见标识说明。
          本页面不构成完整法律合规意见；具体合规事项请咨询专业机构。
          相关页面：<Link to="/legal/privacy">隐私政策</Link> ·{" "}
          <Link to="/legal/terms">用户协议</Link>
        </p>
      </article>
    </AuthPage>
  );
}
