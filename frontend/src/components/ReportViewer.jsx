import { apiResourceUrl } from "../api/client";

function ReportViewer({ report }) {
  if (!report) {
    return null;
  }

  return (
    <div className="report-viewer">
      <div className="section-heading">
        <h3>{report.title}</h3>
        <a className="download-link" href={apiResourceUrl(report.download_url)} download>
          下载报告
        </a>
      </div>
      <pre>{report.content}</pre>
    </div>
  );
}

export default ReportViewer;
