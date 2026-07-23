import { useState } from "react";
import { uploadFile } from "../api/files";

const ACCEPTED_FILE_TYPES = ".xlsx,.csv,.pdf,.png,.jpg,.jpeg";

function FileUploader({ onUploaded, uploadAction = uploadFile }) {
  const [selectedFile, setSelectedFile] = useState(null);
  const [isUploading, setIsUploading] = useState(false);
  const [message, setMessage] = useState("");
  const [messageType, setMessageType] = useState("info");

  async function handleSubmit(event) {
    event.preventDefault();

    if (!selectedFile) {
      setMessageType("error");
      setMessage("请先选择文件");
      return;
    }

    setIsUploading(true);
    setMessageType("info");
    setMessage("正在上传文件");

    try {
      await uploadAction(selectedFile);
      setSelectedFile(null);
      event.target.reset();
      setMessageType("success");
      setMessage("上传成功");
      onUploaded?.();
    } catch (error) {
      setMessageType("error");
      setMessage(error.message);
    } finally {
      setIsUploading(false);
    }
  }

  return (
    <form className="upload-form" onSubmit={handleSubmit}>
      <label className="file-input-label">
        <span>选择文件</span>
        <input
          type="file"
          accept={ACCEPTED_FILE_TYPES}
          onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
        />
      </label>

      <div className="selected-file">
        {selectedFile ? selectedFile.name : "未选择文件"}
      </div>

      <button type="submit" disabled={isUploading}>
        {isUploading ? "上传中" : "上传"}
      </button>

      {message && <p className={`form-message form-message--${messageType}`}>{message}</p>}
    </form>
  );
}

export default FileUploader;
