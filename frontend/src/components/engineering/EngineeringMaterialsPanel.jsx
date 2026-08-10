import WorkspaceUnderstanding from "../WorkspaceUnderstanding";
import { Alert, Badge, Card, SectionHeader } from "../common";
import { getMaterialRoleState } from "../../utils/engineeringReview";

export default function EngineeringMaterialsPanel({ workspaceId, files, profiles, onFilesChanged, onProfilesChanged }) {
  const roleState = getMaterialRoleState(profiles);
  return (
    <div className="engineering-stack">
      <SectionHeader
        title="材料与角色"
        description="上传资料后先执行文件理解，再由用户确认或修改每份材料的工程角色。"
      />
      <Alert title="审查前必须由用户确认角色" tone="info">
        推荐角色只用于辅助选择；未确认角色不计入完成状态，系统不会根据文件名自动确认。
      </Alert>
      <Card>
        <div className="engineering-section-heading">
          <div><h3>五种必需角色</h3><p className="muted">补充附件为可选角色，不计入完成度。</p></div>
          <Badge tone={roleState.complete ? "success" : "warning"}>{roleState.completedCount} / 5 已完成</Badge>
        </div>
        <ul className="role-checklist">
          {roleState.roles.map((item) => (
            <li key={item.role}>
              <span aria-hidden="true">{item.complete ? "✓" : item.count > 1 ? "!" : "○"}</span>
              <strong>{item.label}</strong>
              <code>{item.role}</code>
              <Badge tone={item.complete ? "success" : item.count > 1 ? "danger" : "warning"}>
                {item.complete ? "已确认" : item.count > 1 ? `重复 ${item.count} 份` : "缺少"}
              </Badge>
            </li>
          ))}
        </ul>
        {roleState.duplicatedRoles.length > 0 && (
          <Alert title="发现重复角色" tone="danger">
            {roleState.duplicatedRoles.map((item) => item.label).join("、")}存在多份已确认文件，请修改为唯一角色后再审查。
          </Alert>
        )}
        {roleState.missingRoles.length > 0 && (
          <Alert title="仍缺少必需角色" tone="warning">
            {roleState.missingRoles.map((item) => item.label).join("、")}尚无已就绪且已人工确认的文件。
          </Alert>
        )}
      </Card>
      <WorkspaceUnderstanding
        workspaceId={workspaceId}
        workspaceType="engineering"
        files={files}
        onFilesChanged={onFilesChanged}
        onProfilesChanged={onProfilesChanged}
        mode="files"
      />
    </div>
  );
}
