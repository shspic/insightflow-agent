import { useCallback, useEffect, useState } from "react";
import { fetchFiles, parseFile } from "../api/files";
import FileList from "../components/FileList";
import FileUploader from "../components/FileUploader";

function Upload() {
  const [files, setFiles] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [parsingFileIds, setParsingFileIds] = useState([]);
  const [parseError, setParseError] = useState("");

  const loadFiles = useCallback(async () => {
    setIsLoading(true);
    setError("");

    try {
      const data = await fetchFiles();
      setFiles(data);
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadFiles();
  }, [loadFiles]);

  async function handleParse(fileId) {
    setParseError("");
    setParsingFileIds((currentIds) => [...currentIds, fileId]);

    try {
      await parseFile(fileId);
      await loadFiles();
    } catch (parseFileError) {
      setParseError(parseFileError.message);
      await loadFiles();
    } finally {
      setParsingFileIds((currentIds) => currentIds.filter((id) => id !== fileId));
    }
  }

  return (
    <section className="upload-section">
      <div className="section-heading">
        <h2>文件上传</h2>
        <button type="button" onClick={loadFiles}>
          刷新列表
        </button>
      </div>

      <FileUploader onUploaded={loadFiles} />
      {parseError && <p className="form-message form-message--error">{parseError}</p>}
      <FileList
        files={files}
        isLoading={isLoading}
        error={error}
        parsingFileIds={parsingFileIds}
        onParse={handleParse}
        onRefresh={loadFiles}
      />
    </section>
  );
}

export default Upload;
