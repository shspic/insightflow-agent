import { useCallback, useEffect, useState } from "react";
import { analyzeFile, fetchFiles, generateCharts, indexPdf, parseFile } from "../api/files";
import FileList from "../components/FileList";
import FileUploader from "../components/FileUploader";

function Upload() {
  const [files, setFiles] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [parsingFileIds, setParsingFileIds] = useState([]);
  const [analyzingFileIds, setAnalyzingFileIds] = useState([]);
  const [chartingFileIds, setChartingFileIds] = useState([]);
  const [indexingFileIds, setIndexingFileIds] = useState([]);
  const [parseError, setParseError] = useState("");
  const [analysisError, setAnalysisError] = useState("");
  const [chartError, setChartError] = useState("");
  const [indexError, setIndexError] = useState("");

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

  async function handleAnalyze(fileId) {
    setAnalysisError("");
    setAnalyzingFileIds((currentIds) => [...currentIds, fileId]);

    try {
      await analyzeFile(fileId);
      await loadFiles();
    } catch (analyzeFileError) {
      setAnalysisError(analyzeFileError.message);
      await loadFiles();
    } finally {
      setAnalyzingFileIds((currentIds) => currentIds.filter((id) => id !== fileId));
    }
  }

  async function handleGenerateCharts(fileId) {
    setChartError("");
    setChartingFileIds((currentIds) => [...currentIds, fileId]);

    try {
      await generateCharts(fileId);
      await loadFiles();
    } catch (generateChartsError) {
      setChartError(generateChartsError.message);
      await loadFiles();
    } finally {
      setChartingFileIds((currentIds) => currentIds.filter((id) => id !== fileId));
    }
  }

  async function handleIndexPdf(fileId) {
    setIndexError("");
    setIndexingFileIds((currentIds) => [...currentIds, fileId]);

    try {
      await indexPdf(fileId);
      await loadFiles();
    } catch (indexPdfError) {
      setIndexError(indexPdfError.message);
      await loadFiles();
    } finally {
      setIndexingFileIds((currentIds) => currentIds.filter((id) => id !== fileId));
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
      {analysisError && <p className="form-message form-message--error">{analysisError}</p>}
      {chartError && <p className="form-message form-message--error">{chartError}</p>}
      {indexError && <p className="form-message form-message--error">{indexError}</p>}
      <FileList
        files={files}
        isLoading={isLoading}
        error={error}
        parsingFileIds={parsingFileIds}
        analyzingFileIds={analyzingFileIds}
        chartingFileIds={chartingFileIds}
        indexingFileIds={indexingFileIds}
        onParse={handleParse}
        onAnalyze={handleAnalyze}
        onGenerateCharts={handleGenerateCharts}
        onIndexPdf={handleIndexPdf}
        onRefresh={loadFiles}
      />
    </section>
  );
}

export default Upload;
