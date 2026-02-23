import { useState } from "react";
import type { Asset, GeneratedArtifact, AssetStatus } from "../types";
import { submitApproval, getFileUrl } from "../api/client";

interface StageAssetPanelProps {
  asset: Asset;
  stageId: string;
  onActionComplete: () => void;
}

const statusLabels: Record<AssetStatus, string> = {
  pending: "Pending",
  processing: "Processing",
  awaiting_approval: "Awaiting Approval",
  approved: "Approved",
  rejected: "Rejected",
  completed: "Completed",
  failed: "Failed",
};

export function StageAssetPanel({
  asset,
  stageId,
  onActionComplete,
}: StageAssetPanelProps) {
  const [selectedVariation, setSelectedVariation] = useState<number | null>(null);
  const [modifiedPrompt, setModifiedPrompt] = useState("");
  const [loading, setLoading] = useState(false);
  const [zoomedImage, setZoomedImage] = useState<string | null>(null);

  const stepResult = asset.results[stageId];

  if (!stepResult) {
    const isCurrentStep = asset.current_step === stageId;
    return (
      <div className="h-full flex items-center justify-center text-gray-400">
        <div className="text-center">
          <div className="text-5xl mb-4">{isCurrentStep ? "⏳" : "—"}</div>
          <h2 className="text-xl font-semibold mb-2">
            {isCurrentStep ? "Processing..." : "Not yet reached"}
          </h2>
          <p className="text-sm">
            {isCurrentStep
              ? "This asset is currently being processed at this stage."
              : "This asset hasn't reached this stage yet."}
          </p>
        </div>
      </div>
    );
  }

  const handleApprove = async () => {
    if (selectedVariation === null) return;
    setLoading(true);
    try {
      await submitApproval({
        asset_id: asset.id,
        step_id: stageId,
        approved: true,
        selected_index: selectedVariation,
      });
      setSelectedVariation(null);
      onActionComplete();
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
        step_id: stageId,
        approved: false,
        regenerate,
        modified_prompt: regenerate ? modifiedPrompt || undefined : undefined,
      });
      setModifiedPrompt("");
      setSelectedVariation(null);
      onActionComplete();
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
              ? "ring-4 ring-blue-500 scale-[1.02]"
              : "ring-2 ring-gray-700 hover:ring-gray-500"
          }`}
        >
          {imageUrl ? (
            <img
              src={imageUrl}
              alt={`Variation ${index + 1}`}
              className="w-full h-auto cursor-zoom-in"
              onClick={(e) => {
                e.stopPropagation();
                setZoomedImage(imageUrl);
              }}
            />
          ) : (
            <div className="w-full h-48 bg-gray-800 flex items-center justify-center text-gray-500">
              No image
            </div>
          )}
          <div
            className={`absolute bottom-2 right-2 px-2 py-1 rounded text-sm font-medium ${
              isSelected ? "bg-blue-500 text-white" : "bg-gray-800/80 text-gray-400"
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
        <div
          key={index}
          className="p-4 rounded-lg bg-gray-800 ring-2 ring-gray-700"
        >
          <div className="text-sm text-gray-400 mb-2">Research Results</div>
          <div className="text-sm whitespace-pre-wrap">{artifact.content}</div>
        </div>
      );
    }

    return null;
  };

  const isAwaitingApproval = stepResult.status === "awaiting_approval";
  const isCompleted =
    stepResult.status === "completed" || stepResult.status === "approved";

  return (
    <div className="h-full overflow-auto p-6">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="mb-6">
          <div className="flex items-center gap-3 mb-2">
            <h2 className="text-2xl font-bold">{asset.id}</h2>
            <span
              className={`px-2 py-0.5 rounded text-xs font-medium ${
                isAwaitingApproval
                  ? "bg-yellow-500/20 text-yellow-400"
                  : isCompleted
                  ? "bg-green-500/20 text-green-400"
                  : stepResult.status === "failed"
                  ? "bg-red-500/20 text-red-400"
                  : "bg-gray-700 text-gray-300"
              }`}
            >
              {statusLabels[stepResult.status]}
            </span>
          </div>
          <p className="text-gray-400">{asset.input_description}</p>
        </div>

        {/* Error state */}
        {stepResult.status === "failed" && stepResult.error && (
          <div className="mb-6 bg-red-500/10 border border-red-500/20 rounded-lg p-4">
            <h3 className="text-sm font-medium text-red-400 mb-1">Error</h3>
            <p className="text-sm text-red-300">{stepResult.error}</p>
          </div>
        )}

        {/* Variations */}
        {stepResult.variations.length > 0 && (
          <div className="mb-6">
            <h3 className="text-sm font-medium text-gray-400 mb-3">
              {isAwaitingApproval
                ? `Select a variation (${stepResult.variations.length} options)`
                : isCompleted && stepResult.selected_index != null
                ? "Selected"
                : `Variations (${stepResult.variations.length})`}
            </h3>

            {isCompleted && stepResult.selected_index != null ? (
              <div className="max-w-md">
                {renderVariation(
                  stepResult.variations[stepResult.selected_index],
                  stepResult.selected_index
                )}
              </div>
            ) : (
              <div
                className={`grid gap-4 ${
                  stepResult.variations.length === 1
                    ? "grid-cols-1 max-w-md"
                    : stepResult.variations.length === 2
                    ? "grid-cols-2"
                    : "grid-cols-2 md:grid-cols-4"
                }`}
              >
                {stepResult.variations.map((artifact, i) =>
                  renderVariation(artifact, i)
                )}
              </div>
            )}
          </div>
        )}

        {/* Approval actions */}
        {isAwaitingApproval && (
          <div className="space-y-4">
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

            <div className="bg-gray-800 rounded-lg p-4">
              <div className="text-sm text-gray-400 mb-2">
                Regenerate with modified prompt:
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
        )}

        {/* Zoom modal */}
        {zoomedImage && (
          <div
            className="fixed inset-0 bg-black/90 flex items-center justify-center z-50"
            onClick={() => setZoomedImage(null)}
          >
            <img
              src={zoomedImage}
              alt="Zoomed"
              className="max-w-[90vw] max-h-[90vh] object-contain"
            />
            <button
              onClick={() => setZoomedImage(null)}
              className="absolute top-4 right-4 text-white text-2xl hover:text-gray-300"
            >
              ✕
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
