import type { Asset, AssetStatus } from "../types";
import { getFileUrl } from "../api/client";

interface AssetSidebarProps {
  assets: Asset[];
  stageId: string;
  selectedAssetId: string | null;
  onSelect: (assetId: string) => void;
}

const statusColors: Record<AssetStatus, string> = {
  pending: "bg-gray-500",
  processing: "bg-blue-500 animate-pulse",
  awaiting_approval: "bg-yellow-500",
  approved: "bg-green-500",
  rejected: "bg-red-500",
  completed: "bg-green-600",
  failed: "bg-red-600",
};

const statusLabels: Record<AssetStatus, string> = {
  pending: "Pending",
  processing: "Processing",
  awaiting_approval: "Needs Review",
  approved: "Approved",
  rejected: "Rejected",
  completed: "Done",
  failed: "Failed",
};

export function AssetSidebar({
  assets,
  stageId,
  selectedAssetId,
  onSelect,
}: AssetSidebarProps) {
  const assetsForStage = assets.filter(
    (a) => a.results[stageId] || a.current_step === stageId
  );

  if (assetsForStage.length === 0) return null;

  return (
    <aside className="w-64 bg-gray-800 border-r border-gray-700 overflow-y-auto flex-shrink-0">
      <div className="p-3">
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
          Assets ({assetsForStage.length})
        </h3>
        <div className="space-y-1">
          {assetsForStage.map((asset) => {
            const stepResult = asset.results[stageId];
            const stageStatus: AssetStatus = stepResult
              ? stepResult.status
              : asset.current_step === stageId
              ? "processing"
              : "pending";
            const isSelected = selectedAssetId === asset.id;

            let thumbnailUrl: string | undefined;
            if (stepResult?.variations?.length) {
              const selectedIdx = stepResult.selected_index ?? 0;
              const artifact = stepResult.variations[selectedIdx];
              if (
                (artifact.type === "image" || artifact.type === "sprite") &&
                artifact.path
              ) {
                thumbnailUrl = getFileUrl(artifact.path);
              }
            }

            return (
              <button
                key={asset.id}
                onClick={() => onSelect(asset.id)}
                className={`w-full text-left rounded-lg p-2 transition-colors flex gap-3 items-center ${
                  isSelected
                    ? "bg-blue-500/20 ring-1 ring-blue-500/50"
                    : "hover:bg-gray-700/50"
                }`}
              >
                <div className="w-10 h-10 bg-gray-700 rounded overflow-hidden flex-shrink-0">
                  {thumbnailUrl ? (
                    <img
                      src={thumbnailUrl}
                      alt=""
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-gray-500 text-sm">
                      {stageStatus === "processing" ? "..." : "—"}
                    </div>
                  )}
                </div>

                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium truncate">{asset.id}</div>
                  <div className="flex items-center gap-1.5 mt-0.5">
                    <span
                      className={`w-2 h-2 rounded-full flex-shrink-0 ${statusColors[stageStatus]}`}
                    />
                    <span className="text-xs text-gray-400">
                      {statusLabels[stageStatus]}
                    </span>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </aside>
  );
}
