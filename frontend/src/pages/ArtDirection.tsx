import { useState } from "react";
import type { StyleConfig, PipelineStep } from "../types";
import { updateProjectConfig } from "../api/client";

interface ArtDirectionProps {
  pipeline: PipelineStep[];
  initialStyle?: StyleConfig;
  onNext: (style: StyleConfig, pipeline: PipelineStep[]) => void;
  onBack: () => void;
}

const DEFAULT_STYLE: StyleConfig = {
  global_prompt_prefix: "",
  global_prompt_suffix: "",
  negative_prompt: "",
  aspect_ratio: "1:1",
  image_size: "1K",
};

const STYLE_PRESETS: { name: string; style: Partial<StyleConfig> }[] = [
  {
    name: "Fantasy Illustration",
    style: {
      global_prompt_prefix: "Fantasy illustration style, rich colors, detailed textures, dramatic lighting, painterly quality.",
      global_prompt_suffix: "",
    },
  },
  {
    name: "Pixel Art",
    style: {
      global_prompt_prefix: "Pixel art style, 32-bit, retro game aesthetic, clean pixel edges.",
      global_prompt_suffix: "",
    },
  },
  {
    name: "Magic Card Art",
    style: {
      global_prompt_prefix: "Magic the Gathering card art style, epic fantasy, dynamic composition, professional illustration.",
      global_prompt_suffix: "",
    },
  },
  {
    name: "Anime Style",
    style: {
      global_prompt_prefix: "Anime style illustration, vibrant colors, clean lines, expressive characters.",
      global_prompt_suffix: "",
    },
  },
  {
    name: "Photorealistic",
    style: {
      global_prompt_prefix: "Photorealistic, high detail, professional photography, studio lighting.",
      global_prompt_suffix: "",
    },
  },
];

const ASPECT_RATIOS = ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"];
const IMAGE_SIZES = ["512", "1K", "2K", "4K"];

export function ArtDirection({ pipeline, initialStyle, onNext, onBack }: ArtDirectionProps) {
  const [style, setStyle] = useState<StyleConfig>(initialStyle || DEFAULT_STYLE);
  const [updatedPipeline, setUpdatedPipeline] = useState<PipelineStep[]>(pipeline);
  const [loading, setLoading] = useState(false);
  const [expandedSteps, setExpandedSteps] = useState<Set<string>>(new Set());

  // Apply a style preset
  const applyPreset = (preset: typeof STYLE_PRESETS[0]) => {
    setStyle((prev) => ({
      ...prev,
      ...preset.style,
    }));
  };

  // Toggle step expansion
  const toggleStep = (stepId: string) => {
    setExpandedSteps((prev) => {
      const next = new Set(prev);
      if (next.has(stepId)) {
        next.delete(stepId);
      } else {
        next.add(stepId);
      }
      return next;
    });
  };

  // Update a step's prompt template
  const updateStepPrompt = (stepId: string, promptTemplate: string) => {
    setUpdatedPipeline((prev) =>
      prev.map((step) =>
        step.id === stepId ? { ...step, prompt_template: promptTemplate } : step
      )
    );
  };

  // Save and continue
  const handleSubmit = async () => {
    setLoading(true);
    try {
      // Save configuration to backend
      await updateProjectConfig({
        style,
        pipeline: updatedPipeline,
      });
      onNext(style, updatedPipeline);
    } catch (e) {
      console.error("Failed to save config:", e);
    } finally {
      setLoading(false);
    }
  };

  // Get steps that have images (need style settings)
  const imageSteps = updatedPipeline.filter((s) =>
    ["generate_image", "generate_sprite"].includes(s.type)
  );

  return (
    <div className="max-w-4xl mx-auto">
      <div className="mb-8">
        <h2 className="text-2xl font-bold mb-2">Art Direction</h2>
        <p className="text-gray-400">
          Configure the visual style and prompts for your generation.
        </p>
      </div>

      {/* Global Style */}
      <div className="bg-gray-800 rounded-lg p-6 mb-6">
        <h3 className="text-lg font-semibold mb-4">Global Style</h3>
        <p className="text-gray-400 text-sm mb-4">
          Applied to all image generation steps.
        </p>

        {/* Style presets */}
        <div className="mb-4">
          <label className="text-sm text-gray-400 block mb-2">Quick Presets</label>
          <div className="flex gap-2 flex-wrap">
            {STYLE_PRESETS.map((preset) => (
              <button
                key={preset.name}
                onClick={() => applyPreset(preset)}
                className="px-3 py-1 bg-gray-700 hover:bg-gray-600 rounded text-sm transition-colors"
              >
                {preset.name}
              </button>
            ))}
          </div>
        </div>

        {/* Style prompt prefix */}
        <div className="mb-4">
          <label className="text-sm text-gray-400 block mb-2">
            Style Prompt (prepended to all image prompts)
          </label>
          <textarea
            value={style.global_prompt_prefix}
            onChange={(e) =>
              setStyle((prev) => ({ ...prev, global_prompt_prefix: e.target.value }))
            }
            placeholder="e.g., Fantasy illustration style, rich colors, detailed textures..."
            className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-3 resize-none"
            rows={3}
          />
        </div>

        {/* Suffix */}
        <div className="mb-4">
          <label className="text-sm text-gray-400 block mb-2">
            Suffix (appended to all image prompts)
          </label>
          <textarea
            value={style.global_prompt_suffix}
            onChange={(e) =>
              setStyle((prev) => ({ ...prev, global_prompt_suffix: e.target.value }))
            }
            placeholder="e.g., high quality, 4k, detailed"
            className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-3 resize-none"
            rows={2}
          />
        </div>

        {/* Image settings */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-sm text-gray-400 block mb-2">Aspect Ratio</label>
            <select
              value={style.aspect_ratio}
              onChange={(e) =>
                setStyle((prev) => ({ ...prev, aspect_ratio: e.target.value }))
              }
              className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2"
            >
              {ASPECT_RATIOS.map((ratio) => (
                <option key={ratio} value={ratio}>
                  {ratio}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-sm text-gray-400 block mb-2">Image Size</label>
            <select
              value={style.image_size}
              onChange={(e) =>
                setStyle((prev) => ({ ...prev, image_size: e.target.value }))
              }
              className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2"
            >
              {IMAGE_SIZES.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Per-step configuration */}
      {imageSteps.length > 0 && (
        <div className="mb-6">
          <h3 className="text-lg font-semibold mb-4">Per-Step Configuration</h3>
          <div className="space-y-2">
            {updatedPipeline.map((step) => (
              <div key={step.id} className="bg-gray-800 rounded-lg overflow-hidden">
                <button
                  onClick={() => toggleStep(step.id)}
                  className="w-full px-4 py-3 flex items-center justify-between hover:bg-gray-700 transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-lg">
                      {step.type === "generate_image"
                        ? "🖼️"
                        : step.type === "generate_sprite"
                        ? "🎮"
                        : step.type === "generate_text"
                        ? "📝"
                        : step.type === "generate_name"
                        ? "✏️"
                        : "⚙️"}
                    </span>
                    <span>{step.id}</span>
                    <span className="text-gray-500 text-sm">({step.type})</span>
                  </div>
                  <span className="text-gray-400">
                    {expandedSteps.has(step.id) ? "▼" : "▶"}
                  </span>
                </button>

                {expandedSteps.has(step.id) && (
                  <div className="px-4 pb-4 border-t border-gray-700">
                    <div className="mt-4">
                      <label className="text-sm text-gray-400 block mb-2">
                        Prompt Template
                      </label>
                      <textarea
                        value={step.prompt_template || ""}
                        onChange={(e) => updateStepPrompt(step.id, e.target.value)}
                        placeholder="Use {description}, {research}, {name}, {global_style} as variables"
                        className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-3 resize-none font-mono text-sm"
                        rows={3}
                      />
                      <p className="text-gray-500 text-xs mt-1">
                        Available variables: {"{description}"}, {"{research}"}, {"{name}"},{" "}
                        {"{global_style}"}, {"{id}"}
                      </p>
                    </div>

                    <div className="mt-4 grid grid-cols-2 gap-4">
                      <div>
                        <label className="text-sm text-gray-400 block mb-2">
                          Variations
                        </label>
                        <input
                          type="number"
                          min={1}
                          max={10}
                          value={step.variations}
                          onChange={(e) => {
                            const val = parseInt(e.target.value) || 1;
                            setUpdatedPipeline((prev) =>
                              prev.map((s) =>
                                s.id === step.id ? { ...s, variations: val } : s
                              )
                            );
                          }}
                          className="w-24 bg-gray-700 border border-gray-600 rounded px-3 py-2"
                        />
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-sm text-gray-400">Approval Mode:</span>
                        <select
                          value={step.variations > 1 ? "choose" : "accept"}
                          onChange={(e) => {
                            const isChoose = e.target.value === "choose";
                            setUpdatedPipeline((prev) =>
                              prev.map((s) =>
                                s.id === step.id
                                  ? { ...s, variations: isChoose ? Math.max(2, s.variations) : 1 }
                                  : s
                              )
                            );
                          }}
                          className="bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm"
                        >
                          <option value="choose">Choose 1 of N</option>
                          <option value="accept">Accept/Reject</option>
                        </select>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Preview */}
      <div className="bg-gray-800 rounded-lg p-4 mb-6">
        <h3 className="text-sm font-medium text-gray-400 mb-2">Example Prompt Preview</h3>
        <p className="text-gray-300 font-mono text-sm">
          {style.global_prompt_prefix}{" "}
          <span className="text-blue-400">[your description here]</span>{" "}
          {style.global_prompt_suffix}
        </p>
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
          onClick={handleSubmit}
          disabled={loading}
          className="px-6 py-2 bg-green-600 hover:bg-green-500 disabled:bg-gray-600 disabled:cursor-not-allowed rounded-lg font-medium transition-colors"
        >
          {loading ? "Saving..." : "Start Generation →"}
        </button>
      </div>
    </div>
  );
}
