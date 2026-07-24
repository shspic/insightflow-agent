import { useMemo, useRef, useState } from "react";
import { Alert, Badge, Button, Progress } from "./common";
import { formatBytes } from "../utils/ui";

const ACCEPTED_FILE_TYPES = ".csv,.xlsx,.pdf,.png,.jpg,.jpeg,.webp,.md,.markdown";
const EXTENSIONS = new Set(ACCEPTED_FILE_TYPES.split(","));
const MAX_FILES = 10;
const MAX_FILE_SIZE = 20 * 1024 * 1024;

function queueItem(file) {
  const extension = `.${file.name.split(".").pop()?.toLowerCase()}`;
  if (!EXTENSIONS.has(extension)) {
    return { id: crypto.randomUUID(), file, status: "失败", tone: "danger", message: "不支持此文件类型" };
  }
  if (file.size > MAX_FILE_SIZE) {
    return { id: crypto.randomUUID(), file, status: "失败", tone: "danger", message: "文件超过 20 MB 前端提示上限" };
  }
  return { id: crypto.randomUUID(), file, status: "等待", tone: "neutral", message: "" };
}

export default function BatchFileUploader({ uploadAction, onUploaded, storageHint }) {
  const inputRef = useRef(null);
  const [queue, setQueue] = useState([]);
  const [isUploading, setIsUploading] = useState(false);
  const [message, setMessage] = useState("");
  const pending = useMemo(() => queue.filter((item) => item.status === "等待"), [queue]);
  const failed = useMemo(() => queue.filter((item) => item.status === "失败" && item.file), [queue]);

  function appendFiles(fileList) {
    const files = Array.from(fileList || []);
    setQueue((current) => {
      const known = new Set(current.map((item) => `${item.file.name}:${item.file.size}:${item.file.lastModified}`));
      const next = files
        .filter((file) => !known.has(`${file.name}:${file.size}:${file.lastModified}`))
        .slice(0, Math.max(0, MAX_FILES - current.length))
        .map(queueItem);
      return [...current, ...next];
    });
    setMessage(files.length > MAX_FILES ? `单次最多选择 ${MAX_FILES} 个文件` : "");
  }

  async function uploadItems(items) {
    if (!items.length) {
      setMessage("没有可上传的文件");
      return;
    }
    setIsUploading(true);
    setMessage("正在上传并等待服务端安全校验");
    const ids = new Set(items.map((item) => item.id));
    setQueue((current) => current.map((item) =>
      ids.has(item.id) ? { ...item, status: "上传中", tone: "info", message: "" } : item));
    try {
      const response = await uploadAction(items.map((item) => item.file));
      setQueue((current) => current.map((item) => {
        if (!ids.has(item.id)) return item;
        const index = items.findIndex((entry) => entry.id === item.id);
        const result = response.results[index];
        const succeeded = result?.status === "uploaded";
        return {
          ...item,
          status: succeeded ? "已上传" : "失败",
          tone: succeeded ? "success" : "danger",
          message: result?.message || (succeeded ? "服务端校验通过" : "上传失败"),
        };
      }));
      const succeeded = response.results.filter((item) => item.status === "uploaded");
      setMessage(succeeded.length === response.results.length
        ? "全部文件已上传，可继续执行批量理解"
        : `${succeeded.length} 个文件上传成功，其他文件可单独重试`);
      if (succeeded.length) onUploaded?.(response);
    } catch (error) {
      setQueue((current) => current.map((item) =>
        ids.has(item.id) ? { ...item, status: "失败", tone: "danger", message: error.message } : item));
      setMessage(error.message);
    } finally {
      setIsUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  return (
    <section
      className="batch-upload"
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => {
        event.preventDefault();
        appendFiles(event.dataTransfer.files);
      }}
      aria-label="批量文件上传"
    >
      <div className="batch-upload__dropzone">
        <div>
          <strong>拖入资料，或从设备选择</strong>
          <p>支持 CSV、XLSX、PDF、PNG、JPG、WEBP 与 Markdown；单文件最多 20 MB，单次最多 10 个。</p>
          {storageHint && <p>{storageHint}</p>}
        </div>
        <label className="file-input-label">
          选择文件
          <input ref={inputRef} type="file" multiple accept={ACCEPTED_FILE_TYPES}
            onChange={(event) => appendFiles(event.target.files)} />
        </label>
      </div>
      {queue.length > 0 && (
        <>
          <div className="upload-result-list" aria-live="polite">
            {queue.map((item) => (
              <div key={item.id} className="upload-result-item">
                <span title={item.file.name}>{item.file.name}</span>
                <span className="muted">{item.file.type || "类型待服务端确认"} · {formatBytes(item.file.size)}</span>
                <Badge tone={item.tone}>{item.status}</Badge>
                <span className="muted">{item.message || "等待操作"}</span>
                {["等待", "失败"].includes(item.status) && !isUploading && (
                  <Button variant="ghost" size="sm" onClick={() =>
                    setQueue((current) => current.filter((entry) => entry.id !== item.id))}>
                    移除
                  </Button>
                )}
              </div>
            ))}
          </div>
          {isUploading && <Progress value={45} label="正在上传与校验" />}
          <div className="row-actions">
            <Button onClick={() => uploadItems(pending)} disabled={isUploading || !pending.length}
              loading={isUploading}>上传 {pending.length || ""} 个文件</Button>
            {failed.length > 0 && !isUploading && (
              <Button variant="secondary" onClick={() => {
                setQueue((current) => current.map((item) =>
                  item.status === "失败" ? { ...item, status: "等待", tone: "neutral", message: "" } : item));
              }}>将失败文件加入重试</Button>
            )}
            <Button variant="ghost" disabled={isUploading} onClick={() => setQueue([])}>全部清空</Button>
          </div>
        </>
      )}
      {message && <Alert title={message.includes("成功") || message.includes("全部") ? "上传状态" : "上传提示"}
        tone={failed.length ? "warning" : "info"}>{message}</Alert>}
    </section>
  );
}
