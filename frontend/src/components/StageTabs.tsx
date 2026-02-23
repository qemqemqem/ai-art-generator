import type { PipelineStep, Asset } from "../types";

interface StageTabsProps {
  stages: PipelineStep[];
  assets: Asset[];
  selectedStageId: string | null;
  onSelect: (stageId: string) => void;
}

function formatStepName(id: string): string {
  return id
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function StageTabs({
  stages,
  assets,
  selectedStageId,
  onSelect,
}: StageTabsProps) {
  return (
    <div className="flex gap-1 overflow-x-auto border-b border-gray-700 px-4">
      {stages.map((stage) => {
        const assetsAtStage = assets.filter(
          (a) => a.results[stage.id] || a.current_step === stage.id
        );
        const awaitingCount = assetsAtStage.filter(
          (a) => a.results[stage.id]?.status === "awaiting_approval"
        ).length;
        const isSelected = selectedStageId === stage.id;

        return (
          <button
            key={stage.id}
            onClick={() => onSelect(stage.id)}
            className={`relative flex items-center gap-2 px-4 py-3 -mb-px border-b-2 transition-colors whitespace-nowrap text-sm font-medium ${
              isSelected
                ? "border-blue-500 text-blue-400"
                : "border-transparent text-gray-400 hover:text-gray-200"
            }`}
          >
            <span>{formatStepName(stage.id)}</span>

            {assetsAtStage.length > 0 && (
              <span className="px-1.5 py-0.5 rounded-full bg-gray-700 text-xs text-gray-300">
                {assetsAtStage.length}
              </span>
            )}

            {awaitingCount > 0 && (
              <span className="px-1.5 py-0.5 rounded-full bg-yellow-500/20 text-yellow-400 text-xs font-semibold">
                {awaitingCount}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
