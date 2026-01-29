import type { Asset, AssetStatus } from "../types";
import { getFileUrl } from "../api/client";

interface AssetListProps {
  assets: Asset[];
  onSelectAsset?: (asset: Asset) => void;
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
  awaiting_approval: "Awaiting Approval",
  approved: "Approved",
  rejected: "Rejected",
  completed: "Completed",
  failed: "Failed",
};

export function AssetList({ assets, onSelectAsset }: AssetListProps) {
  if (assets.length === 0) {
    return (
      <div className="text-center py-8 text-gray-400">
        <p>No assets yet</p>
        <p className="text-sm mt-1">Add some input to get started</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {assets.map((asset) => {
        // Find the first completed image to show as thumbnail
        let thumbnailUrl: string | undefined;
        for (const result of Object.values(asset.results)) {
          if (result.status === "completed" && result.variations.length > 0) {
            const selectedIdx = result.selected_index ?? 0;
            const artifact = result.variations[selectedIdx];
            if ((artifact.type === "image" || artifact.type === "sprite") && artifact.path) {
              thumbnailUrl = getFileUrl(artifact.path);
              break;
            }
          }
        }

        return (
          <button
            key={asset.id}
            onClick={() => onSelectAsset?.(asset)}
            className="w-full text-left bg-gray-800 rounded-lg p-3 hover:bg-gray-700 transition-colors flex gap-4"
          >
            {/* Thumbnail */}
            <div className="w-16 h-16 bg-gray-700 rounded overflow-hidden flex-shrink-0">
              {thumbnailUrl ? (
                <img
                  src={thumbnailUrl}
                  alt=""
                  className="w-full h-full object-cover"
                />
              ) : (
                <div className="w-full h-full flex items-center justify-center text-gray-500 text-2xl">
                  🎨
                </div>
              )}
            </div>

            {/* Info */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-medium truncate">{asset.id}</span>
                <span
                  className={`px-2 py-0.5 rounded text-xs ${statusColors[asset.status]}`}
                >
                  {statusLabels[asset.status]}
                </span>
              </div>
              <p className="text-sm text-gray-400 mt-1 truncate">
                {asset.input_description}
              </p>
              {asset.current_step && (
                <p className="text-xs text-gray-500 mt-1">
                  Current step: {asset.current_step}
                </p>
              )}
            </div>
          </button>
        );
      })}
    </div>
  );
}
