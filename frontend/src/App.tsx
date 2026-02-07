import { useState, useEffect, useCallback } from "react";
import { ApprovalQueue } from "./components/ApprovalQueue";
import { AssetList } from "./components/AssetList";
import { InputUploader } from "./components/InputUploader";
import { ContentInput } from "./pages/ContentInput";
import { FlowSetup } from "./pages/FlowSetup";
import { ArtDirection } from "./pages/ArtDirection";
import { InteractiveQueue } from "./pages/InteractiveQueue";
import type { QueueItem, Asset, PipelineStep, StyleConfig, Project, FinInfo } from "./types";
import {
  getApprovalQueue,
  listAssets,
  getHealth,
  getProject,
  startInteractive,
  getFileUrl,
} from "./api/client";

type Mode = "classic" | "interactive";
type InteractiveStep = "content" | "flow" | "style" | "queue" | "results";
type ClassicTab = "queue" | "assets" | "input";

function App() {
  // Connection state
  const [connected, setConnected] = useState(false);
  const [project, setProject] = useState<Project | null>(null);

  // Mode selection
  const [mode, setMode] = useState<Mode | null>(null);

  // Interactive mode state
  const [interactiveStep, setInteractiveStep] = useState<InteractiveStep>("content");
  const [pipeline, setPipeline] = useState<PipelineStep[]>([]);
  const [style, setStyle] = useState<StyleConfig | null>(null);
  const [finInfo, setFinInfo] = useState<FinInfo | null>(null);

  // Classic mode state
  const [activeTab, setActiveTab] = useState<ClassicTab>("queue");
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [loading, setLoading] = useState(false);

  // Check backend connection
  useEffect(() => {
    const checkConnection = async () => {
      try {
        await getHealth();
        setConnected(true);

        const projectData = await getProject();
        setProject(projectData as unknown as Project);
      } catch {
        setConnected(false);
      }
    };
    checkConnection();
    const interval = setInterval(checkConnection, 5000);
    return () => clearInterval(interval);
  }, []);

  // Load classic mode data
  const loadProjectData = useCallback(async () => {
    if (!connected || mode !== "classic") return;

    setLoading(true);
    try {
      const [queueResult, assetsResult] = await Promise.all([
        getApprovalQueue(),
        listAssets(),
      ]);
      setQueue(queueResult.queue as unknown as QueueItem[]);
      setAssets(assetsResult.assets as unknown as Asset[]);
    } catch (error) {
      console.error("Failed to load project data:", error);
    } finally {
      setLoading(false);
    }
  }, [connected, mode]);

  // Load data in classic mode
  useEffect(() => {
    if (connected && mode === "classic") {
      loadProjectData();
      const interval = setInterval(loadProjectData, 3000);
      return () => clearInterval(interval);
    }
  }, [connected, mode, loadProjectData]);

  // Handle interactive mode flow
  const handleContentNext = () => {
    setInteractiveStep("flow");
  };

  const handleFlowNext = (newPipeline: PipelineStep[]) => {
    setPipeline(newPipeline);
    setInteractiveStep("style");
  };

  const handleStyleNext = async (newStyle: StyleConfig, finalPipeline: PipelineStep[]) => {
    setStyle(newStyle);
    setPipeline(finalPipeline);

    // Start generation
    try {
      await startInteractive();
      setInteractiveStep("queue");
    } catch (e) {
      console.error("Failed to start generation:", e);
    }
  };

  const handleInteractiveComplete = (finData?: FinInfo) => {
    if (finData) {
      setFinInfo(finData);
    }
    setInteractiveStep("results");
  };

  // Mode selection screen
  if (!connected) {
    return (
      <div className="min-h-screen bg-gray-900 text-gray-100 flex items-center justify-center">
        <div className="text-center py-16 text-gray-400">
          <div className="text-6xl mb-4">🔌</div>
          <h2 className="text-2xl font-semibold mb-2">Connecting to backend...</h2>
          <p>Make sure the server is running:</p>
          <pre className="mt-4 bg-gray-800 rounded p-4 text-sm text-left inline-block">
            cd your-project-dir{"\n"}
            uvicorn app.main:app --reload --port 8000
          </pre>
        </div>
      </div>
    );
  }

  if (mode === null) {
    return (
      <div className="min-h-screen bg-gray-900 text-gray-100">
        <div className="max-w-4xl mx-auto px-6 py-16">
          <div className="text-center mb-12">
            <h1 className="text-4xl font-bold mb-4">🎨 AI Art Generator</h1>
            {project && (
              <p className="text-gray-400">
                Project: <span className="text-gray-200">{project.name}</span>
              </p>
            )}
          </div>

          <div className="grid md:grid-cols-2 gap-6 max-w-2xl mx-auto">
            {/* Interactive Mode */}
            <button
              onClick={() => setMode("interactive")}
              className="bg-gray-800 hover:bg-gray-700 rounded-xl p-8 text-left transition-colors group"
            >
              <div className="text-4xl mb-4">🚀</div>
              <h2 className="text-xl font-bold mb-2 group-hover:text-blue-400 transition-colors">
                Interactive Mode
              </h2>
              <p className="text-gray-400 text-sm">
                Guided wizard to set up content, configure the pipeline, and work through
                an approval queue. Great for new projects.
              </p>
              <div className="mt-4 text-blue-400 text-sm font-medium">
                Start wizard →
              </div>
            </button>

            {/* Classic Mode */}
            <button
              onClick={() => setMode("classic")}
              className="bg-gray-800 hover:bg-gray-700 rounded-xl p-8 text-left transition-colors group"
            >
              <div className="text-4xl mb-4">⚙️</div>
              <h2 className="text-xl font-bold mb-2 group-hover:text-blue-400 transition-colors">
                Classic Mode
              </h2>
              <p className="text-gray-400 text-sm">
                Direct access to assets, queue, and processing. For power users or
                resuming existing work.
              </p>
              <div className="mt-4 text-blue-400 text-sm font-medium">
                Open dashboard →
              </div>
            </button>
          </div>

          {/* Quick stats */}
          {project && (
            <div className="mt-12 text-center text-gray-500 text-sm">
              {project.asset_count
                ? `${project.asset_count} assets in project`
                : "No assets yet"}
            </div>
          )}
        </div>
      </div>
    );
  }

  // Interactive mode
  if (mode === "interactive") {
    return (
      <div className="min-h-screen bg-gray-900 text-gray-100">
        {/* Progress header for wizard steps */}
        {interactiveStep !== "queue" && (
          <header className="bg-gray-800 border-b border-gray-700 px-6 py-4">
            <div className="max-w-4xl mx-auto">
              <div className="flex items-center justify-between mb-4">
                <button
                  onClick={() => setMode(null)}
                  className="text-gray-400 hover:text-gray-200 transition-colors"
                >
                  ← Back to menu
                </button>
                <span className="text-gray-400">{project?.name}</span>
              </div>

              {/* Step indicators */}
              <div className="flex items-center gap-2">
                {(["content", "flow", "style", "queue"] as const).map((step, i) => {
                  const steps = ["content", "flow", "style", "queue"];
                  const currentIdx = steps.indexOf(interactiveStep);
                  const stepIdx = i;
                  const isComplete = stepIdx < currentIdx;
                  const isCurrent = step === interactiveStep;

                  return (
                    <div key={step} className="flex items-center">
                      {i > 0 && (
                        <div
                          className={`w-8 h-px ${
                            isComplete ? "bg-blue-500" : "bg-gray-700"
                          }`}
                        />
                      )}
                      <div
                        className={`w-8 h-8 rounded-full flex items-center justify-center text-sm ${
                          isComplete
                            ? "bg-blue-500 text-white"
                            : isCurrent
                            ? "bg-blue-500/20 text-blue-400 ring-2 ring-blue-500"
                            : "bg-gray-700 text-gray-400"
                        }`}
                      >
                        {isComplete ? "✓" : i + 1}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </header>
        )}

        {/* Step content */}
        <main className={interactiveStep === "queue" ? "" : "py-8 px-6"}>
          {interactiveStep === "content" && (
            <ContentInput
              onNext={handleContentNext}
              onSkip={() => setInteractiveStep("flow")}
            />
          )}

          {interactiveStep === "flow" && (
            <FlowSetup
              initialPipeline={project?.config?.pipeline}
              onNext={handleFlowNext}
              onBack={() => setInteractiveStep("content")}
            />
          )}

          {interactiveStep === "style" && (
            <ArtDirection
              pipeline={pipeline}
              initialStyle={project?.config?.style}
              onNext={handleStyleNext}
              onBack={() => setInteractiveStep("flow")}
            />
          )}

          {interactiveStep === "queue" && (
            <InteractiveQueue onComplete={handleInteractiveComplete} />
          )}

          {interactiveStep === "results" && (
            <div className="max-w-6xl mx-auto px-6 py-8">
              {/* Header */}
              <div className="text-center mb-8">
                <div className="text-6xl mb-4">🎉</div>
                <h2 className="text-3xl font-bold mb-2">
                  {finInfo?.title || "Generation Complete!"}
                </h2>
                {finInfo?.message && (
                  <p className="text-gray-400 text-lg">{finInfo.message}</p>
                )}
              </div>

              {/* Display Items Gallery */}
              {finInfo?.display_items && finInfo.display_items.length > 0 ? (
                <div className="space-y-8">
                  {finInfo.display_items.map((displayItem, groupIndex) => (
                    <div key={groupIndex}>
                      <h3 className="text-xl font-semibold mb-4 text-gray-200">
                        {displayItem.label}
                      </h3>
                      
                      {displayItem.type === "images" && (
                        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                          {(displayItem.items as { path: string; asset_id?: string }[]).map((img, imgIndex) => (
                            <div
                              key={imgIndex}
                              className="relative group rounded-lg overflow-hidden bg-gray-800 aspect-[3/4]"
                            >
                              <img
                                src={getFileUrl(img.path)}
                                alt={img.asset_id || `Image ${imgIndex + 1}`}
                                className="w-full h-full object-cover transition-transform group-hover:scale-105"
                              />
                              {img.asset_id && (
                                <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 to-transparent p-3">
                                  <p className="text-sm text-white truncate">
                                    {img.asset_id}
                                  </p>
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                      
                      {displayItem.type === "text" && (
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                          {(displayItem.items as { content: string; asset_id?: string }[]).map((txt, txtIndex) => (
                            <div
                              key={txtIndex}
                              className="bg-gray-800 rounded-lg p-4"
                            >
                              {txt.asset_id && (
                                <p className="text-sm text-blue-400 mb-2">
                                  {txt.asset_id}
                                </p>
                              )}
                              <p className="text-gray-300">{txt.content}</p>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-center text-gray-400 mb-8">
                  Your assets have been generated. Check the outputs folder for results.
                </p>
              )}

              {/* Action Buttons */}
              <div className="flex gap-4 justify-center mt-12">
                <button
                  onClick={() => {
                    setMode("classic");
                    setActiveTab("assets");
                  }}
                  className="px-6 py-3 bg-blue-600 hover:bg-blue-500 rounded-lg font-medium"
                >
                  View All Assets
                </button>
                <button
                  onClick={() => setMode(null)}
                  className="px-6 py-3 bg-gray-700 hover:bg-gray-600 rounded-lg"
                >
                  Back to Menu
                </button>
              </div>
            </div>
          )}
        </main>
      </div>
    );
  }

  // Classic mode (original UI)
  const tabs: { id: ClassicTab; label: string; count?: number }[] = [
    { id: "queue", label: "Approval Queue", count: queue.length },
    { id: "assets", label: "All Assets", count: assets.length },
    { id: "input", label: "Add Input" },
  ];

  return (
    <div className="min-h-screen bg-gray-900 text-gray-100">
      {/* Header */}
      <header className="bg-gray-800 border-b border-gray-700 px-6 py-4">
        <div className="max-w-5xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button
              onClick={() => setMode(null)}
              className="text-gray-400 hover:text-gray-200 transition-colors"
            >
              ←
            </button>
            <h1 className="text-xl font-bold">🎨 AI Art Generator</h1>
            {project && <span className="text-gray-400">/ {project.name}</span>}
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2 text-sm text-green-400">
              <span className="w-2 h-2 rounded-full bg-green-400" />
              Connected
            </div>
          </div>
        </div>
      </header>

      <div className="max-w-5xl mx-auto px-6 py-8">
        {/* Tabs */}
        <div className="flex gap-1 mb-6 border-b border-gray-700">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-4 py-2 -mb-px border-b-2 transition-colors ${
                activeTab === tab.id
                  ? "border-blue-500 text-blue-400"
                  : "border-transparent text-gray-400 hover:text-gray-200"
              }`}
            >
              {tab.label}
              {tab.count !== undefined && (
                <span className="ml-2 px-2 py-0.5 rounded-full bg-gray-700 text-xs">
                  {tab.count}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Loading indicator */}
        {loading && <div className="text-center py-4 text-gray-400">Loading...</div>}

        {/* Tab Content */}
        {activeTab === "queue" && (
          <ApprovalQueue queue={queue} onRefresh={loadProjectData} />
        )}

        {activeTab === "assets" && <AssetList assets={assets} />}

        {activeTab === "input" && (
          <InputUploader
            onUploadComplete={() => {
              loadProjectData();
              setActiveTab("queue");
            }}
          />
        )}
      </div>
    </div>
  );
}

export default App;
