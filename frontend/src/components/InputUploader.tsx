import { useState } from "react";
import { uploadInput, processAll } from "../api/client";

interface InputUploaderProps {
  onUploadComplete: () => void;
}

export function InputUploader({ onUploadComplete }: InputUploaderProps) {
  const [content, setContent] = useState("");
  const [format, setFormat] = useState("text");
  const [loading, setLoading] = useState(false);
  const [autoStart, setAutoStart] = useState(true);

  const handleUpload = async () => {
    if (!content.trim()) return;

    setLoading(true);
    try {
      await uploadInput(content, format, autoStart);
      setContent("");
      onUploadComplete();
    } catch (error) {
      console.error("Upload failed:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleStartProcessing = async () => {
    setLoading(true);
    try {
      await processAll(false);
      onUploadComplete();
    } catch (error) {
      console.error("Processing failed:", error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-400 mb-2">
          Input Format
        </label>
        <select
          value={format}
          onChange={(e) => setFormat(e.target.value)}
          className="w-full px-3 py-2 rounded bg-gray-700 border border-gray-600 focus:border-blue-500 focus:outline-none"
        >
          <option value="text">Plain Text (one per line)</option>
          <option value="csv">CSV</option>
          <option value="json">JSON</option>
          <option value="jsonl">JSON Lines</option>
        </select>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-400 mb-2">
          Input Content
        </label>
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder={
            format === "text"
              ? "Enter descriptions, one per line:\n\nA wise owl wizard\nFire-breathing dragon\nEnchanted forest"
              : format === "csv"
              ? "id,description\n001,A wise owl wizard\n002,Fire-breathing dragon"
              : format === "json"
              ? '[\n  {"description": "A wise owl wizard"},\n  {"description": "Fire-breathing dragon"}\n]'
              : '{"description": "A wise owl wizard"}\n{"description": "Fire-breathing dragon"}'
          }
          rows={8}
          className="w-full px-3 py-2 rounded bg-gray-700 border border-gray-600 focus:border-blue-500 focus:outline-none font-mono text-sm"
        />
      </div>

      <div className="flex items-center gap-2">
        <input
          type="checkbox"
          id="autoStart"
          checked={autoStart}
          onChange={(e) => setAutoStart(e.target.checked)}
          className="rounded bg-gray-700 border-gray-600"
        />
        <label htmlFor="autoStart" className="text-sm text-gray-400">
          Start processing immediately
        </label>
      </div>

      <div className="flex gap-3">
        <button
          onClick={handleUpload}
          disabled={!content.trim() || loading}
          className="flex-1 py-2 px-4 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed font-medium"
        >
          {loading ? "Uploading..." : "Add Assets"}
        </button>
        <button
          onClick={handleStartProcessing}
          disabled={loading}
          className="py-2 px-4 rounded bg-green-600 hover:bg-green-500 disabled:opacity-50 font-medium"
        >
          Process All
        </button>
      </div>
    </div>
  );
}
