import { useEffect, useMemo, useState } from "react";
import { Link, NavLink, Navigate, useNavigate, useParams } from "react-router-dom";
import {
  fetchCurrentReviewBrief,
  fetchReviewFindings,
  fetchReviewRun,
  fetchReviewRuns,
} from "../api/engineeringReviews";
import { fetchWorkspaceFileProfile } from "../api/fileUnderstanding";
import { fetchWorkspace } from "../api/workspaces";
import { fetchWorkspaceFiles } from "../api/workspaceFiles";
import EngineeringMaterialsPanel from "../components/engineering/EngineeringMaterialsPanel";
import ReviewBriefEditor from "../components/engineering/ReviewBriefEditor";
import ReviewFindingsPanel from "../components/engineering/ReviewFindingsPanel";
import ReviewReportPanel from "../components/engineering/ReviewReportPanel";
import ReviewRunPanel from "../components/engineering/ReviewRunPanel";
import VerificationPanel from "../components/engineering/VerificationPanel";
import {
  Alert,
  Badge,
  Card,
  PageHeader,
  Skeleton,
  StatusBadge,
  Stepper,
} from "../components/common";
import {
  FINDING_SEVERITY,
  FINDING_STATUS,
  REVIEW_RUN_STATUS,
  getMaterialRoleState,
  getReviewNextStep,
  summarizeFindings,
} from "../utils/engineeringReview";
import { formatDate } from "../utils/ui";

const SECTIONS = [
  ["overview", "审查概览", ""],
  ["materials", "材料与角色", "materials"],
  ["requirements", "审查要求", "requirements"],
  ["review", "执行审查", "review"],
  ["findings", "问题清单", "findings"],
  ["verification", "智能核验", "verification"],
  ["reports", "审查报告", "reports"],
  ["settings", "项目信息", "settings"],
];

function sectionFromPath(value) {
  return SECTIONS.find(([, , path]) => path === (value || ""))?.[0] || null;
}

async function loadProfiles(workspaceId, files) {
  const entries = await Promise.all(files.map(async (file) => {
    if (!["ready", "failed", "unsupported"].includes(file.status)) return null;
    try {
      return [file.file_id, await fetchWorkspaceFileProfile(workspaceId, file.file_id)];
    } catch {
      return null;
    }
  }));
  return Object.fromEntries(entries.filter(Boolean));
}

function ReviewOverview({ basePath, materialState, brief, latestRun, latestFindings }) {
  const findingCounts = summarizeFindings(latestFindings);
  const nextStep = getReviewNextStep({ materials: materialState, brief, runs: latestRun ? [latestRun] : [], findings: latestFindings });
  const stepIndex = nextStep.section === "materials" ? 0 : nextStep.section === "requirements" ? 1 : nextStep.section === "review" ? 2 : 3;
  const severityCounts = latestRun?.severity_counts || findingCounts.severity;
  return (
    <div className="engineering-stack">
      <Stepper steps={["材料与角色", "审查要求", "执行审查", "人工复核"]} current={stepIndex} />
      <div className="overview-grid engineering-overview-grid">
        <Card><span className="muted">必需角色</span><p className="usage-value">{materialState.completedCount} / 5</p>
          <Link to={`${basePath}/materials`}>{materialState.complete ? "查看已确认角色" : "补齐材料角色"}</Link></Card>
        <Card><span className="muted">当前 confirmed Brief</span><p className="usage-value">{brief ? `v${brief.version}` : "未确认"}</p>
          <Link to={`${basePath}/requirements`}>查看审查要求</Link></Card>
        <Card><span className="muted">最近 ReviewRun</span><p className="usage-value">{latestRun ? `#${latestRun.id}` : "尚无"}</p>
          {latestRun ? <StatusBadge status={latestRun.status} dictionary={REVIEW_RUN_STATUS} /> : <Link to={`${basePath}/review`}>创建 Run</Link>}</Card>
        <Card><span className="muted">下一步建议</span><p className="overview-next-step">{nextStep.label}</p>
          <Link to={`${basePath}/${nextStep.section}`}>前往处理</Link></Card>
      </div>
      <div className="overview-grid">
        <Card><h3>风险等级</h3><div className="metric-grid">
          {Object.entries(FINDING_SEVERITY).map(([value, meta]) => <div key={value}><span>{meta[0]}</span><strong>{severityCounts[value] || 0}</strong></div>)}
        </div></Card>
        <Card><h3>人工复核状态</h3><div className="status-count-list">
          {Object.entries(FINDING_STATUS).map(([value, meta]) => <div key={value}><StatusBadge status={value} dictionary={FINDING_STATUS} /><strong>{findingCounts.status[value] || 0}</strong></div>)}
        </div></Card>
      </div>
      <Alert title="审查边界" tone="info">
        当前审查要求由用户人工确认；Supervisor 自动意图解释将在可信 Agent 阶段接入。
      </Alert>
    </div>
  );
}

export default function EngineeringProjectDetail() {
  const { workspaceId, section: rawSection } = useParams();
  const navigate = useNavigate();
  const section = sectionFromPath(rawSection);
  const basePath = `/engineering/projects/${workspaceId}`;
  const [workspace, setWorkspace] = useState(null);
  const [files, setFiles] = useState([]);
  const [profiles, setProfiles] = useState({});
  const [brief, setBrief] = useState(null);
  const [runs, setRuns] = useState([]);
  const [latestRun, setLatestRun] = useState(null);
  const [latestFindings, setLatestFindings] = useState([]);
  const [activeRun, setActiveRun] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function selectRun(run) {
    try {
      const detail = await fetchReviewRun(workspaceId, run.id);
      setActiveRun(detail);
      return detail;
    } catch (requestError) {
      setError(`${requestError.code ? `${requestError.code}：` : ""}${requestError.message}`);
      return null;
    }
  }

  async function loadProject() {
    setLoading(true);
    setError("");
    try {
      const workspaceData = await fetchWorkspace(workspaceId);
      setWorkspace(workspaceData);
      if (workspaceData.workspace_type !== "engineering") return;
      const [fileData, runData, briefData] = await Promise.all([
        fetchWorkspaceFiles(workspaceId),
        fetchReviewRuns(workspaceId),
        fetchCurrentReviewBrief(workspaceId).catch((requestError) => {
          if (requestError.status === 404) return null;
          throw requestError;
        }),
      ]);
      setFiles(fileData);
      setProfiles(await loadProfiles(workspaceId, fileData));
      setBrief(briefData);
      setRuns(runData);
      if (runData.length > 0) {
        const detail = await fetchReviewRun(workspaceId, runData[0].id);
        setLatestRun(detail);
        setActiveRun(detail);
        const findingData = await fetchReviewFindings(workspaceId, detail.id);
        setLatestFindings(findingData);
      } else {
        setLatestRun(null);
        setActiveRun(null);
        setLatestFindings([]);
      }
    } catch (requestError) {
      setError(`${requestError.code ? `${requestError.code}：` : ""}${requestError.message}`);
    } finally {
      setLoading(false);
    }
  }

  async function refreshFiles() {
    const fileData = await fetchWorkspaceFiles(workspaceId);
    setFiles(fileData);
    setProfiles(await loadProfiles(workspaceId, fileData));
  }

  async function handleRunChanged(run) {
    const runData = await fetchReviewRuns(workspaceId);
    setRuns(runData);
    const detail = await fetchReviewRun(workspaceId, run.id);
    setActiveRun(detail);
    if (runData[0]?.id === detail.id) {
      setLatestRun(detail);
      const findingData = await fetchReviewFindings(workspaceId, detail.id);
      setLatestFindings(findingData);
    }
  }

  async function openFindings(run) {
    const detail = await selectRun(run);
    if (detail) navigate(`${basePath}/findings`);
  }

  useEffect(() => { loadProject(); }, [workspaceId]);

  const materialState = useMemo(() => getMaterialRoleState(profiles), [profiles]);

  if (loading) return <section className="page-section"><Skeleton lines={7} /></section>;
  if (!workspace) return <Alert title="工程项目无法加载" tone="danger">{error || "项目不存在或没有访问权限。"}</Alert>;
  if (workspace.workspace_type !== "engineering") return <Navigate to={`/general/workspaces/${workspaceId}`} replace />;
  if (!section) return <Navigate to={basePath} replace />;

  return (
    <section className="page-section engineering-project-page">
      <PageHeader
        eyebrow={<Link to="/engineering/projects">工程项目 / 返回列表</Link>}
        title={workspace.name}
        description={workspace.description || "尚未填写项目说明。"}
        actions={<Badge tone={workspace.status === "active" ? "success" : "warning"}>{workspace.status === "active" ? "审查中" : "已归档"}</Badge>}
      />
      <nav className="workspace-tabs" aria-label="工程审查模块">
        {SECTIONS.map(([, label, path]) => <NavLink key={label} end={path === ""}
          to={`${basePath}${path ? `/${path}` : ""}`}>{label}</NavLink>)}
      </nav>
      {error && <Alert title="部分数据未加载" tone="danger">{error}</Alert>}
      {section === "overview" && <ReviewOverview basePath={basePath} materialState={materialState}
        brief={brief} latestRun={latestRun} latestFindings={latestFindings} />}
      {section === "materials" && <EngineeringMaterialsPanel workspaceId={workspaceId} files={files} profiles={profiles}
        onFilesChanged={refreshFiles} onProfilesChanged={setProfiles} />}
      {section === "requirements" && <ReviewBriefEditor workspaceId={workspaceId} currentBrief={brief} onBriefChanged={setBrief} />}
      {section === "review" && <ReviewRunPanel workspaceId={workspaceId} basePath={basePath} materialState={materialState}
        brief={brief} runs={runs} activeRun={activeRun} onRunChanged={handleRunChanged} onSelectRun={selectRun} onOpenFindings={openFindings} />}
      {section === "findings" && <ReviewFindingsPanel workspaceId={workspaceId} run={activeRun} files={files}
        onFindingsChanged={(findingData) => { if (activeRun?.id === latestRun?.id) setLatestFindings(findingData); }} />}
      {section === "verification" && <VerificationPanel workspaceId={workspaceId} runs={runs}
        activeRun={activeRun} onSelectRun={selectRun} />}
      {section === "reports" && <ReviewReportPanel
        workspaceId={workspaceId} basePath={basePath} runs={runs} activeRun={activeRun}
        onSelectRun={selectRun} />}
      {section === "settings" && <Card>
        <h2>项目信息</h2>
        <dl className="engineering-detail-list">
          <div><dt>项目 ID</dt><dd>{workspace.id}</dd></div>
          <div><dt>名称</dt><dd>{workspace.name}</dd></div>
          <div><dt>类型</dt><dd>{workspace.workspace_type}</dd></div>
          <div><dt>工程模板</dt><dd>{workspace.review_template_key || "—"}</dd></div>
          <div><dt>状态</dt><dd>{workspace.status}</dd></div>
          <div><dt>创建时间</dt><dd>{formatDate(workspace.created_at)}</dd></div>
        </dl>
        <p><strong>说明：</strong>{workspace.description || "未填写"}</p>
        <p className="muted">重命名、编辑说明、归档与永久删除在工程项目列表统一操作。</p>
        <Link to="/engineering/projects">返回工程项目列表</Link>
      </Card>}
    </section>
  );
}
