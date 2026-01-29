import { useState, useCallback } from "react";
import type { PipelineStep } from "../types";

interface FlowSetupProps {
  initialPipeline?: PipelineStep[];
  onNext: (pipeline: PipelineStep[]) => void;
  onBack: () => void;
}

type StepType =
  | "research"
  | "generate_name"
  | "generate_text"
  | "generate_image"
  | "generate_sprite"
  | "remove_background";

interface StepTemplate {
  type: StepType;
  label: string;
  icon: string;
  description: string;
  defaultConfig: Partial<PipelineStep>;
}

const STEP_TEMPLATES: StepTemplate[] = [
  {
    type: "research",
    label: "AI Research",
    icon: "🔍",
    description: "Research the concept for richer context",
    defaultConfig: {
      requires_approval: false,
      variations: 1,
      provider: "tavily",
    },
  },
  {
    type: "generate_name",
    label: "Generate Name",
    icon: "✏️",
    description: "Generate a creative name for the concept",
    defaultConfig: {
      requires_approval: true,
      variations: 4,
      provider: "gemini",
      prompt_template: "Generate a creative name for: {description}",
    },
  },
  {
    type: "generate_image",
    label: "Generate Image",
    icon: "🖼️",
    description: "Generate main artwork",
    defaultConfig: {
      requires_approval: true,
      variations: 4,
      provider: "gemini",
      prompt_template: "{description}",
    },
  },
  {
    type: "generate_sprite",
    label: "Generate Sprite",
    icon: "🎮",
    description: "Generate pixel art sprite",
    defaultConfig: {
      requires_approval: true,
      variations: 4,
      provider: "gemini",
      prompt_template: "Pixel art sprite, 32-bit style. {description}. Front-facing, game asset, clean edges.",
    },
  },
  {
    type: "generate_text",
    label: "Generate Description",
    icon: "📝",
    description: "Generate a text description",
    defaultConfig: {
      requires_approval: true,
      variations: 2,
      provider: "gemini",
      prompt_template: "Write a detailed description for: {description}",
    },
  },
  {
    type: "remove_background",
    label: "Remove Background",
    icon: "✂️",
    description: "Remove background from the previous image",
    defaultConfig: {
      requires_approval: false,
      variations: 1,
    },
  },
];

const PRESETS: { name: string; pipeline: Partial<PipelineStep>[] }[] = [
  {
    name: "Magic Card",
    pipeline: [
      { type: "research" as StepType, id: "research" },
      { type: "generate_name" as StepType, id: "name", variations: 4 },
      { type: "generate_image" as StepType, id: "portrait", variations: 4 },
      { type: "generate_text" as StepType, id: "flavor", variations: 2, prompt_template: "Write flavor text for a magic card: {description}" },
    ],
  },
  {
    name: "Game Sprite",
    pipeline: [
      { type: "generate_sprite" as StepType, id: "sprite", variations: 4 },
      { type: "remove_background" as StepType, id: "sprite_nobg" },
    ],
  },
  {
    name: "Character Sheet",
    pipeline: [
      { type: "research" as StepType, id: "research" },
      { type: "generate_name" as StepType, id: "name", variations: 4 },
      { type: "generate_image" as StepType, id: "portrait", variations: 4 },
      { type: "generate_sprite" as StepType, id: "sprite", variations: 4 },
      { type: "remove_background" as StepType, id: "sprite_nobg" },
      { type: "generate_text" as StepType, id: "bio", variations: 2, prompt_template: "Write a character biography: {description}" },
    ],
  },
];

export function FlowSetup({ initialPipeline, onNext, onBack }: FlowSetupProps) {
  const [pipeline, setPipeline] = useState<PipelineStep[]>(
    initialPipeline || []
  );
  const [draggedIndex, setDraggedIndex] = useState<number | null>(null);

  // Add a step to the pipeline
  const addStep = useCallback((template: StepTemplate) => {
    const newStep: PipelineStep = {
      id: `${template.type}_${Date.now()}`,
      type: template.type,
      requires_approval: template.defaultConfig.requires_approval || false,
      variations: template.defaultConfig.variations || 1,
      provider: template.defaultConfig.provider,
      prompt_template: template.defaultConfig.prompt_template,
      config: {},
    };
    setPipeline((prev) => [...prev, newStep]);
  }, []);

  // Remove a step
  const removeStep = useCallback((index: number) => {
    setPipeline((prev) => prev.filter((_, i) => i !== index));
  }, []);

  // Update a step
  const updateStep = useCallback((index: number, updates: Partial<PipelineStep>) => {
    setPipeline((prev) =>
      prev.map((step, i) => (i === index ? { ...step, ...updates } : step))
    );
  }, []);

  // Handle drag and drop reordering
  const handleDragStart = (index: number) => {
    setDraggedIndex(index);
  };

  const handleDragOver = (e: React.DragEvent, index: number) => {
    e.preventDefault();
    if (draggedIndex === null || draggedIndex === index) return;

    const newPipeline = [...pipeline];
    const [removed] = newPipeline.splice(draggedIndex, 1);
    newPipeline.splice(index, 0, removed);
    setPipeline(newPipeline);
    setDraggedIndex(index);
  };

  const handleDragEnd = () => {
    setDraggedIndex(null);
  };

  // Apply preset
  const applyPreset = (preset: typeof PRESETS[0]) => {
    const newPipeline = preset.pipeline.map((step, i) => {
      const template = STEP_TEMPLATES.find((t) => t.type === step.type);
      return {
        id: step.id || `${step.type}_${i}`,
        type: step.type as string,
        requires_approval: step.requires_approval ?? template?.defaultConfig.requires_approval ?? false,
        variations: step.variations ?? template?.defaultConfig.variations ?? 1,
        provider: step.provider ?? template?.defaultConfig.provider,
        prompt_template: step.prompt_template ?? template?.defaultConfig.prompt_template,
        config: {},
      } as PipelineStep;
    });
    setPipeline(newPipeline);
  };

  const getStepIcon = (type: string) => {
    return STEP_TEMPLATES.find((t) => t.type === type)?.icon || "⚙️";
  };

  const getStepLabel = (type: string) => {
    return STEP_TEMPLATES.find((t) => t.type === type)?.label || type;
  };

  return (
    <div className="max-w-4xl mx-auto">
      <div className="mb-8">
        <h2 className="text-2xl font-bold mb-2">Flow Setup</h2>
        <p className="text-gray-400">
          Configure the generation pipeline. Drag to reorder steps.
        </p>
      </div>

      {/* Presets */}
      <div className="mb-8">
        <h3 className="text-sm font-medium text-gray-400 mb-3">Quick Start Presets</h3>
        <div className="flex gap-2 flex-wrap">
          {PRESETS.map((preset) => (
            <button
              key={preset.name}
              onClick={() => applyPreset(preset)}
              className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm transition-colors"
            >
              {preset.name}
            </button>
          ))}
        </div>
      </div>

      {/* Current pipeline */}
      <div className="mb-8">
        <h3 className="text-sm font-medium text-gray-400 mb-3">
          Pipeline Steps ({pipeline.length})
        </h3>

        {pipeline.length === 0 ? (
          <div className="bg-gray-800 rounded-lg p-8 text-center text-gray-400">
            <p className="mb-2">No steps configured yet.</p>
            <p className="text-sm">Add steps from the list below, or choose a preset above.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {pipeline.map((step, index) => (
              <div
                key={step.id}
                draggable
                onDragStart={() => handleDragStart(index)}
                onDragOver={(e) => handleDragOver(e, index)}
                onDragEnd={handleDragEnd}
                className={`bg-gray-800 rounded-lg p-4 cursor-move ${
                  draggedIndex === index ? "opacity-50" : ""
                }`}
              >
                <div className="flex items-start gap-4">
                  {/* Drag handle and number */}
                  <div className="flex items-center gap-2 text-gray-400">
                    <span className="text-lg">⋮⋮</span>
                    <span className="w-6 h-6 flex items-center justify-center bg-gray-700 rounded-full text-sm">
                      {index + 1}
                    </span>
                  </div>

                  {/* Step info */}
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="text-xl">{getStepIcon(step.type)}</span>
                      <span className="font-medium">{getStepLabel(step.type)}</span>
                      <span className="text-gray-500 text-sm font-mono">({step.id})</span>
                    </div>

                    {/* Step config */}
                    <div className="grid grid-cols-2 gap-4 text-sm">
                      <div>
                        <label className="text-gray-400 block mb-1">Variations</label>
                        <input
                          type="number"
                          min={1}
                          max={10}
                          value={step.variations}
                          onChange={(e) =>
                            updateStep(index, { variations: parseInt(e.target.value) || 1 })
                          }
                          className="w-20 bg-gray-700 border border-gray-600 rounded px-2 py-1"
                        />
                      </div>
                      <div className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          id={`approval_${step.id}`}
                          checked={step.requires_approval}
                          onChange={(e) =>
                            updateStep(index, { requires_approval: e.target.checked })
                          }
                          className="rounded bg-gray-700 border-gray-600"
                        />
                        <label htmlFor={`approval_${step.id}`} className="text-gray-400">
                          Requires approval
                        </label>
                      </div>
                    </div>

                    {/* Prompt template (for applicable steps) */}
                    {step.prompt_template !== undefined && (
                      <div className="mt-3">
                        <label className="text-gray-400 text-sm block mb-1">
                          Prompt Template
                        </label>
                        <textarea
                          value={step.prompt_template || ""}
                          onChange={(e) =>
                            updateStep(index, { prompt_template: e.target.value })
                          }
                          className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm resize-none"
                          rows={2}
                        />
                      </div>
                    )}
                  </div>

                  {/* Remove button */}
                  <button
                    onClick={() => removeStep(index)}
                    className="text-gray-400 hover:text-red-400 transition-colors p-1"
                    title="Remove step"
                  >
                    ✕
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Add step buttons */}
      <div className="mb-8">
        <h3 className="text-sm font-medium text-gray-400 mb-3">Add Step</h3>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
          {STEP_TEMPLATES.map((template) => (
            <button
              key={template.type}
              onClick={() => addStep(template)}
              className="bg-gray-800 hover:bg-gray-700 rounded-lg p-4 text-left transition-colors"
            >
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xl">{template.icon}</span>
                <span className="font-medium">{template.label}</span>
              </div>
              <p className="text-gray-400 text-sm">{template.description}</p>
            </button>
          ))}
        </div>
      </div>

      {/* Actions */}
      <div className="flex justify-between items-center">
        <button
          onClick={onBack}
          className="px-4 py-2 text-gray-400 hover:text-gray-200 transition-colors"
        >
          ← Back
        </button>

        <button
          onClick={() => onNext(pipeline)}
          disabled={pipeline.length === 0}
          className="px-6 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-600 disabled:cursor-not-allowed rounded-lg font-medium transition-colors"
        >
          Continue →
        </button>
      </div>
    </div>
  );
}
