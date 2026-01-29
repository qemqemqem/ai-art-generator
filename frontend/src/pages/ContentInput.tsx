import { useState, useCallback, DragEvent } from "react";
import { uploadInput } from "../api/client";

interface ParsedItem {
  id: string;
  description: string;
  metadata?: Record<string, unknown>;
}

interface ContentInputProps {
  onNext: (items: ParsedItem[]) => void;
  onSkip?: () => void;
}

type InputFormat = "text" | "csv" | "tsv" | "json" | "jsonl";

export function ContentInput({ onNext, onSkip }: ContentInputProps) {
  const [content, setContent] = useState("");
  const [format, setFormat] = useState<InputFormat>("text");
  const [parsedItems, setParsedItems] = useState<ParsedItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [loading, setLoading] = useState(false);

  // Parse content into items
  const parseContent = useCallback((text: string, fmt: InputFormat): ParsedItem[] => {
    const items: ParsedItem[] = [];
    
    try {
      switch (fmt) {
        case "text": {
          const lines = text.split("\n").filter((l) => l.trim());
          lines.forEach((line, i) => {
            items.push({
              id: `item_${i + 1}`,
              description: line.trim(),
            });
          });
          break;
        }
        case "csv":
        case "tsv": {
          const sep = fmt === "csv" ? "," : "\t";
          const lines = text.split("\n").filter((l) => l.trim());
          const headers = lines[0]?.split(sep).map((h) => h.trim().toLowerCase());
          
          for (let i = 1; i < lines.length; i++) {
            const values = lines[i].split(sep);
            const item: ParsedItem = {
              id: `item_${i}`,
              description: "",
            };
            
            headers?.forEach((h, j) => {
              const val = values[j]?.trim() || "";
              if (h === "id") item.id = val || item.id;
              else if (h === "description" || h === "desc" || h === "name") {
                item.description = val;
              } else {
                item.metadata = { ...item.metadata, [h]: val };
              }
            });
            
            if (item.description) items.push(item);
          }
          break;
        }
        case "json": {
          const data = JSON.parse(text);
          const arr = Array.isArray(data) ? data : [data];
          arr.forEach((obj, i) => {
            items.push({
              id: obj.id || `item_${i + 1}`,
              description: obj.description || obj.name || obj.desc || "",
              metadata: obj.metadata || {},
            });
          });
          break;
        }
        case "jsonl": {
          const lines = text.split("\n").filter((l) => l.trim());
          lines.forEach((line, i) => {
            const obj = JSON.parse(line);
            items.push({
              id: obj.id || `item_${i + 1}`,
              description: obj.description || obj.name || obj.desc || "",
              metadata: obj.metadata || {},
            });
          });
          break;
        }
      }
    } catch (e) {
      throw new Error(`Failed to parse as ${fmt.toUpperCase()}: ${e}`);
    }
    
    return items.filter((i) => i.description);
  }, []);

  // Auto-detect format and parse
  const handleContentChange = useCallback(
    (text: string) => {
      setContent(text);
      setError(null);
      
      if (!text.trim()) {
        setParsedItems([]);
        return;
      }
      
      // Auto-detect format
      let detectedFormat: InputFormat = "text";
      const trimmed = text.trim();
      
      if (trimmed.startsWith("[") || trimmed.startsWith("{")) {
        // JSON or JSONL
        if (trimmed.includes("\n") && !trimmed.startsWith("[")) {
          detectedFormat = "jsonl";
        } else {
          detectedFormat = "json";
        }
      } else if (trimmed.includes("\t")) {
        detectedFormat = "tsv";
      } else if (trimmed.includes(",") && trimmed.split("\n")[0]?.includes(",")) {
        detectedFormat = "csv";
      }
      
      setFormat(detectedFormat);
      
      try {
        const items = parseContent(text, detectedFormat);
        setParsedItems(items);
      } catch (e) {
        setError(String(e));
        setParsedItems([]);
      }
    },
    [parseContent]
  );

  // Handle file drop
  const handleDrop = useCallback(
    (e: DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      
      const file = e.dataTransfer.files[0];
      if (!file) return;
      
      const reader = new FileReader();
      reader.onload = (event) => {
        const text = event.target?.result as string;
        handleContentChange(text);
      };
      reader.readAsText(file);
    },
    [handleContentChange]
  );

  // Handle file upload via button
  const handleFileUpload = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;
      
      const reader = new FileReader();
      reader.onload = (event) => {
        const text = event.target?.result as string;
        handleContentChange(text);
      };
      reader.readAsText(file);
    },
    [handleContentChange]
  );

  // Submit to backend
  const handleSubmit = async () => {
    if (parsedItems.length === 0) {
      setError("No items to submit");
      return;
    }
    
    setLoading(true);
    try {
      await uploadInput(content, format, false);
      onNext(parsedItems);
    } catch (e) {
      setError(`Failed to upload: ${e}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto">
      <div className="mb-8">
        <h2 className="text-2xl font-bold mb-2">Content Input</h2>
        <p className="text-gray-400">
          Paste or upload your content. One concept per line, or use CSV/JSON format.
        </p>
      </div>

      {/* Text area */}
      <div
        className={`relative mb-6 ${isDragging ? "ring-2 ring-blue-500" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
      >
        <textarea
          value={content}
          onChange={(e) => handleContentChange(e.target.value)}
          placeholder="Paste your content here (one item per line)&#10;&#10;Examples:&#10;Fire Dragon with scales of obsidian&#10;Ice Wizard holding a crystalline staff&#10;Forest Spirit emerging from an ancient oak"
          className="w-full h-64 bg-gray-800 border border-gray-700 rounded-lg p-4 text-gray-100 placeholder-gray-500 resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        
        {isDragging && (
          <div className="absolute inset-0 bg-blue-500/20 rounded-lg flex items-center justify-center">
            <span className="text-blue-300 font-medium">Drop file here</span>
          </div>
        )}
      </div>

      {/* File upload */}
      <div className="flex items-center gap-4 mb-6">
        <span className="text-gray-400">or</span>
        <label className="cursor-pointer">
          <input
            type="file"
            accept=".txt,.csv,.tsv,.json,.jsonl"
            onChange={handleFileUpload}
            className="hidden"
          />
          <span className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors">
            Upload File
          </span>
        </label>
        <span className="text-gray-500 text-sm">
          Supports: .txt, .csv, .tsv, .json, .jsonl
        </span>
      </div>

      {/* Format indicator */}
      <div className="flex items-center gap-2 mb-6">
        <span className="text-gray-400">Detected format:</span>
        <span className="px-2 py-1 bg-gray-700 rounded text-sm font-mono">
          {format.toUpperCase()}
        </span>
      </div>

      {/* Error message */}
      {error && (
        <div className="mb-6 p-4 bg-red-900/30 border border-red-700 rounded-lg text-red-300">
          {error}
        </div>
      )}

      {/* Preview table */}
      {parsedItems.length > 0 && (
        <div className="mb-6">
          <h3 className="text-lg font-semibold mb-3">
            Preview ({parsedItems.length} items)
          </h3>
          <div className="bg-gray-800 rounded-lg overflow-hidden">
            <table className="w-full">
              <thead className="bg-gray-700">
                <tr>
                  <th className="px-4 py-2 text-left text-sm font-medium text-gray-300">#</th>
                  <th className="px-4 py-2 text-left text-sm font-medium text-gray-300">ID</th>
                  <th className="px-4 py-2 text-left text-sm font-medium text-gray-300">Description</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-700">
                {parsedItems.slice(0, 10).map((item, i) => (
                  <tr key={item.id} className="hover:bg-gray-700/50">
                    <td className="px-4 py-2 text-gray-400">{i + 1}</td>
                    <td className="px-4 py-2 font-mono text-sm">{item.id}</td>
                    <td className="px-4 py-2 truncate max-w-md">{item.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {parsedItems.length > 10 && (
              <div className="px-4 py-2 text-gray-400 text-sm bg-gray-700/50">
                ...and {parsedItems.length - 10} more items
              </div>
            )}
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="flex justify-between items-center">
        <button
          onClick={onSkip}
          className="px-4 py-2 text-gray-400 hover:text-gray-200 transition-colors"
        >
          Skip (use existing assets)
        </button>
        
        <button
          onClick={handleSubmit}
          disabled={parsedItems.length === 0 || loading}
          className="px-6 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-600 disabled:cursor-not-allowed rounded-lg font-medium transition-colors"
        >
          {loading ? "Uploading..." : `Continue with ${parsedItems.length} items →`}
        </button>
      </div>
    </div>
  );
}
