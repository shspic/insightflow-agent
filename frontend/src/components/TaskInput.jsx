import { useState } from "react";

function TaskInput({ files, isSubmitting, onSubmit }) {
  const [selectedFileId, setSelectedFileId] = useState("");
  const [userInput, setUserInput] = useState("");

  function handleSubmit(event) {
    event.preventDefault();

    if (!selectedFileId || !userInput.trim()) {
      return;
    }

    onSubmit({
      user_input: userInput.trim(),
      file_ids: [Number(selectedFileId)],
    });
  }

  return (
    <form className="task-form" onSubmit={handleSubmit}>
      <label>
        选择文件
        <select value={selectedFileId} onChange={(event) => setSelectedFileId(event.target.value)}>
          <option value="">请选择文件</option>
          {files.map((file) => (
            <option key={file.id} value={file.id}>
              #{file.id} {file.filename} ({file.file_type})
            </option>
          ))}
        </select>
      </label>

      <label>
        任务描述
        <textarea
          value={userInput}
          onChange={(event) => setUserInput(event.target.value)}
          placeholder="例如：帮我分析这个文件的缺失值和字段情况"
          rows="4"
        />
      </label>

      <button type="submit" disabled={isSubmitting || !selectedFileId || !userInput.trim()}>
        {isSubmitting ? "提交中" : "提交任务"}
      </button>
    </form>
  );
}

export default TaskInput;
