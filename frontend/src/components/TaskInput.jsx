import { useState } from "react";

function TaskInput({ files, isSubmitting, onSubmit }) {
  const [selectedFileIds, setSelectedFileIds] = useState([]);
  const [userInput, setUserInput] = useState("");
  const selectedFiles = files.filter((file) => selectedFileIds.includes(file.id));

  function handleSubmit(event) {
    event.preventDefault();

    if (selectedFileIds.length === 0 || !userInput.trim()) {
      return;
    }

    onSubmit({
      user_input: userInput.trim(),
      file_ids: selectedFileIds,
    });
  }

  function handleFileToggle(fileId) {
    setSelectedFileIds((currentIds) =>
      currentIds.includes(fileId)
        ? currentIds.filter((currentId) => currentId !== fileId)
        : [...currentIds, fileId]
    );
  }

  return (
    <form className="task-form" onSubmit={handleSubmit}>
      <fieldset className="task-file-picker">
        <legend>选择文件</legend>
        {files.length === 0 ? (
          <p className="parse-empty">暂无可选文件，请先上传文件。</p>
        ) : (
          <div className="task-file-options">
            {files.map((file) => (
              <label key={file.id} className="task-file-option">
                <input
                  type="checkbox"
                  checked={selectedFileIds.includes(file.id)}
                  onChange={() => handleFileToggle(file.id)}
                />
                <span>
                  #{file.id} {file.filename}（{file.file_type}，{file.status}）
                </span>
              </label>
            ))}
          </div>
        )}
      </fieldset>

      {selectedFiles.length > 0 && (
        <div className="selected-task-files">
          <strong>已选文件：</strong>
          {selectedFiles.map((file) => (
            <span key={file.id}>
              #{file.id} {file.filename}（{file.file_type}，{file.status}）
            </span>
          ))}
        </div>
      )}

      <label>
        任务描述
        <textarea
          value={userInput}
          onChange={(event) => setUserInput(event.target.value)}
          placeholder="例如：帮我分析这个文件的缺失值和字段情况"
          rows="4"
        />
      </label>

      <button type="submit" disabled={isSubmitting || selectedFileIds.length === 0 || !userInput.trim()}>
        {isSubmitting ? "提交中" : "提交任务"}
      </button>
    </form>
  );
}

export default TaskInput;
