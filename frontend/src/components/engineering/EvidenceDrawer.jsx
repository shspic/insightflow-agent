import { Alert, Badge, Drawer, EmptyState } from "../common";
import { formatEvidenceLocator, shortHash } from "../../utils/engineeringReview";

export default function EvidenceDrawer({ open, onClose, finding, evidences, missingIds, files }) {
  const fileNames = new Map(files.map((file) => [Number(file.file_id), file.display_name]));
  return (
    <Drawer open={open} onClose={onClose} title={finding ? `${finding.issue_code} 的证据` : "证据"}>
      {missingIds.length > 0 && (
        <Alert title="Evidence 数据完整性警告" tone="danger">
          Finding 引用了不存在的 Evidence ID：{missingIds.join("、")}。请停止依赖该条结果并联系管理员核查。
        </Alert>
      )}
      <div className="evidence-list">
        {evidences.map((evidence) => {
          const fileName = fileNames.get(Number(evidence.file_id)) || `未知文件 #${evidence.file_id}`;
          return (
            <article className="evidence-card" key={evidence.id}>
              <div className="engineering-section-heading">
                <strong>{formatEvidenceLocator(evidence, fileName)}</strong>
                <Badge>{evidence.locator_type}</Badge>
              </div>
              <dl className="engineering-detail-list">
                <div><dt>来源文件名</dt><dd>{fileName}</dd></div>
                <div><dt>file_id</dt><dd>{evidence.file_id}</dd></div>
                <div><dt>locator_type</dt><dd>{evidence.locator_type}</dd></div>
                <div><dt>PDF 页码</dt><dd>{evidence.page_number ?? "—"}</dd></div>
                <div><dt>Excel 工作表</dt><dd>{evidence.sheet_name || "—"}</dd></div>
                <div><dt>Excel 单元格</dt><dd>{evidence.cell_range || "—"}</dd></div>
                <div><dt>text chunk</dt><dd>{evidence.chunk_id ?? "—"}</dd></div>
                <div><dt>content_hash</dt><dd><code>{shortHash(evidence.content_hash)}</code></dd></div>
                <div><dt>parser_name</dt><dd>{evidence.parser_name || "接口未提供"}</dd></div>
                <div><dt>parser_version</dt><dd>{evidence.parser_version || "接口未提供"}</dd></div>
              </dl>
              <blockquote>{evidence.quote || "（无引用文本）"}</blockquote>
            </article>
          );
        })}
        {evidences.length === 0 && missingIds.length === 0 && (
          <EmptyState title="没有关联证据" description="该 Finding 未绑定 Evidence。" />
        )}
      </div>
    </Drawer>
  );
}
