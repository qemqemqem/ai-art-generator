import { useState } from "react";
import type { QueueItem, GeneratedArtifact } from "../types";
import { submitApproval, getFileUrl } from "../api/client";

interface ApprovalQueueProps {
  queue: QueueItem[];
  onRefresh: () => void;
}

export function ApprovalQueue({ queue, onRefresh }: ApprovalQueueProps) {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [selectedVariation, setSelectedVariation] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [modifiedPrompt, setModifiedPrompt] = useState("");

  if (queue.length === 0) {
    return (
      <div className="text-center py-12 text-gray-400">
        <div className="text-4xl mb-4">✨</div>
        <p className="text-xl">No items awaiting approval</p>
        <p className="mt-2">Add assets and start processing to see them here</p>
      </div>
    );
  }

  const currentItem = queue[currentIndex];
  const { asset, step_id, step_result } = currentItem;

  const handleApprove = async () => {
    if (selectedVariation === null) return;
    
    setLoading(true);
    try {
      await submitApproval({
        asset_id: asset.id,
        step_id,
        approved: true,
        selected_index: selectedVariation,
      });
      setSelectedVariation(null);
      onRefresh();
    } catch (error) {
      console.error("Approval failed:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleReject = async (regenerate: boolean) => {
    setLoading(true);
    try {
      await submitApproval({
        asset_id: asset.id,
        step_id,
        approved: false,
        regenerate,
        modified_prompt: regenerate ? modifiedPrompt || undefined : undefined,
      });
      setModifiedPrompt("");
      setSelectedVariation(null);
      onRefresh();
    } catch (error) {
      console.error("Rejection failed:", error);
    } finally {
      setLoading(false);
    }
  };

  const renderVariation = (artifact: GeneratedArtifact, index: number) => {
    const isSelected = selectedVariation === index;
    
    if (artifact.type === "image" || artifact.type === "sprite") {
      const imageUrl = artifact.path ? getFileUrl(artifact.path) : undefined;

      return (
        <button
          key={index}
          onClick={() => setSelectedVariation(index)}
          className={`relative rounded-lg overflow-hidden transition-all ${
            isSelected
              ? "ring-4 ring-blue-500 scale-105"
              : "ring-2 ring-gray-700 hover:ring-gray-500"
          }`}
        >
          {imageUrl ? (
            <img
              src={imageUrl}
              alt={`Variation ${index + 1}`}
              className="w-full h-auto"
            />
          ) : (
            <div className="w-full h-48 bg-gray-800 flex items-center justify-center">
              <span className="text-gray-500">No image</span>
            </div>
          )}
          <div
            className={`absolute bottom-2 right-2 px-2 py-1 rounded text-sm ${
              isSelected ? "bg-blue-500" : "bg-gray-800"
            }`}
          >
            #{index + 1}
          </div>
        </button>
      );
    }

    if (artifact.type === "name" || artifact.type === "text") {
      return (
        <button
          key={index}
          onClick={() => setSelectedVariation(index)}
          className={`p-4 rounded-lg text-left transition-all ${
            isSelected
              ? "ring-4 ring-blue-500 bg-gray-700"
              : "ring-2 ring-gray-700 bg-gray-800 hover:ring-gray-500"
          }`}
        >
          <div className="text-sm text-gray-400 mb-1">Option {index + 1}</div>
          <div className="text-lg">{artifact.content}</div>
        </button>
      );
    }

    if (artifact.type === "research") {
      return (
        <div key={index} className="p-4 rounded-lg bg-gray-800 ring-2 ring-gray-700">
          <div className="text-sm text-gray-400 mb-2">Research Results</div>
          <div className="text-sm whitespace-pre-wrap">{artifact.content}</div>
        </div>
      );
    }

    return null;
  };

  return (
    <div className="space-y-6">
      {/* Progress indicator */}
      <div className="flex items-center justify-between text-sm text-gray-400">
        <span>
          Item {currentIndex + 1} of {queue.length}
        </span>
        <div className="flex gap-2">
          <button
            onClick={() => setCurrentIndex(Math.max(0, currentIndex - 1))}
            disabled={currentIndex === 0}
            className="px-3 py-1 rounded bg-gray-700 disabled:opacity-50"
          >
            Previous
          </button>
          <button
            onClick={() =>
              setCurrentIndex(Math.min(queue.length - 1, currentIndex + 1))
            }
            disabled={currentIndex === queue.length - 1}
            className="px-3 py-1 rounded bg-gray-700 disabled:opacity-50"
          >
            Next
          </button>
        </div>
      </div>

      {/* Asset info */}
      <div className="bg-gray-800 rounded-lg p-4">
        <div className="flex items-start justify-between">
          <div>
            <h3 className="text-lg font-semibold">{asset.id}</h3>
            <p className="text-gray-400 mt-1">{asset.input_description}</p>
          </div>
          <div className="text-sm text-gray-500">
            Step: <span className="text-gray-300">{step_id}</span>
          </div>
        </div>
      </div>

      {/* Variations grid */}
      <div>
        <h4 className="text-sm font-medium text-gray-400 mb-3">
          Select a variation ({step_result.variations.length} options)
        </h4>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {step_result.variations.map((artifact, index) =>
            renderVariation(artifact, index)
          )}
        </div>
      </div>

      {/* Actions */}
      <div className="flex flex-col gap-4">
        <div className="flex gap-4">
          <button
            onClick={handleApprove}
            disabled={selectedVariation === null || loading}
            className="flex-1 py-3 px-6 rounded-lg bg-green-600 hover:bg-green-500 disabled:opacity-50 disabled:cursor-not-allowed font-medium transition-colors"
          >
            {loading ? "Processing..." : "Approve Selection"}
          </button>
          <button
            onClick={() => handleReject(false)}
            disabled={loading}
            className="py-3 px-6 rounded-lg bg-red-600 hover:bg-red-500 disabled:opacity-50 font-medium transition-colors"
          >
            Reject
          </button>
        </div>

        {/* Regenerate option */}
        <div className="bg-gray-800 rounded-lg p-4">
          <div className="text-sm text-gray-400 mb-2">
            Or regenerate with modified prompt:
          </div>
          <div className="flex gap-2">
            <input
              type="text"
              value={modifiedPrompt}
              onChange={(e) => setModifiedPrompt(e.target.value)}
              placeholder="Enter modified prompt (optional)"
              className="flex-1 px-3 py-2 rounded bg-gray-700 border border-gray-600 focus:border-blue-500 focus:outline-none"
            />
            <button
              onClick={() => handleReject(true)}
              disabled={loading}
              className="px-4 py-2 rounded bg-yellow-600 hover:bg-yellow-500 disabled:opacity-50 font-medium transition-colors"
            >
              Regenerate
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
