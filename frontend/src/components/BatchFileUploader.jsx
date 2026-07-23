import { useRef, useState } from "react";

const ACCEPTED_FILE_TYPES = ".csv,.xlsx,.pdf,.png,.jpg,.jpeg,.webp,.md,.markdown";

function formatBytes(value) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

export default function BatchFileUploader({ uploadAction, onUploaded }) {
  const inputRef = useRef(null);
  const [selected, setSelected] = useState([]);
  const [results, setResults] = useState([]);
  const [isUploading, setIsUploading] = useState(false);
  const [message, setMessage] = useState("");

  function setFiles(fileList) {
    const files = Array.from(fileList || []);
    setSelected(files);
    setResults(
      files.map((file) => ({
        filename: file.name,
        type: file.type || "未知类型",
        size: file.size,
        status: "等待上传",
        message: "",
      })),
    );
    setMessage("");
  }

  async function submit(event) {
    event.preventDefault();
    if (selected.length === 0) {
      setMessage("请至少选择一个文件");
      return;
    }
    setIsUploading(true);
    setMessage("正在执行服务端安全校验并上传");
    setResults((current) => current.map((item) => ({ ...item, status: "上传中" })));
    try {
      const response = await uploadAction(selected);
      setResults(
        response.results.map((item, index) => ({
          filename: item.filename,
          type: selected[index]?.type || "未知类型",
          size: selected[index]?.size || 0,
          status: item.status === "uploaded" ? "已上传" : "失败",
          message: item.message,
        })),
      );
      setMessage(response.status === "completed" ? "全部文件上传完成" : "部分文件未上传");
      if (response.results.some((item) => item.status === "uploaded")) {
        onUploaded?.();
      }
      setSelected([]);
      if (inputRef.current) inputRef.current.value = "";
    } catch (error) {
      setResults((current) =>
        current.map((item) => ({ ...item, status: "失败", message: error.message })),
      );
      setMessage(error.message);
    } finally {
      setIsUploading(false);
    }
  }

  return (
    <form
      className="batch-upload"
      onSubmit={submit}
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => {
        event.preventDefault();
        setFiles(event.dataTransfer.files);
      }}
    >
      <div className="batch-upload__dropzone">
        <label className="file-input-label">
          <span>选择多个文件</span>
          <input
            ref={inputRef}
            type="file"
            multiple
            accept={ACCEPTED_FILE_TYPES}
            onChange={(event) => setFiles(event.target.files)}
          />
        </label>
        <p>也可以把文件拖到这里。最终类型、大小和配额由服务端校验。</p>
        <button type="submit" disabled={isUploading || selected.length === 0}>
          {isUploading ? "上传中" : `上传 ${selected.length || ""} 个文件`}
        </button>
      </div>
      {results.length > 0 && (
        <div className="upload-result-list">
          {results.map((item, index) => {
            return (
              <div key={`${item.filename}-${index}`} className="upload-result-item">
                <span>{item.filename}</span>
                <span>{item.type} · {formatBytes(item.size)}</span>
                <strong>{item.status}</strong>
                {item.message && <span>{item.message}</span>}
              </div>
            );
          })}
        </div>
      )}
      {message && <p className="form-message">{message}</p>}
    </form>
  );
}
