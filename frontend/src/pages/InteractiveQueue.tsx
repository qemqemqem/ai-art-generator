import { useState, useEffect, useCallback } from "react";
import type {
  ApprovalItem,
  GeneratedOption,
  QueueStatus,
  GeneratingItem,
} from "../types";
import {
  getInteractiveStatus,
  getNextApproval,
  getAllApprovals,
  getGeneratingItems,
  submitInteractiveApproval,
  skipApproval,
  regenerateItem,
  pauseInteractive,
  resumeInteractive,
  stopInteractive,
  getFileUrl,
} from "../api/client";
import { useWebSocket } from "../hooks/useWebSocket";

interface InteractiveQueueProps {
  onComplete?: () => void;
}

export function InteractiveQueue({ onComplete }: InteractiveQueueProps) {
  const [status, setStatus] = useState<QueueStatus | null>(null);
  const [currentItem, setCurrentItem] = useState<ApprovalItem | null>(null);
  const [pendingItems, setPendingItems] = useState<ApprovalItem[]>([]);
  const [generatingItems, setGeneratingItems] = useState<GeneratingItem[]>([]);
  const [selectedOption, setSelectedOption] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [zoomedImage, setZoomedImage] = useState<string | null>(null);
  const [showSidebar, setShowSidebar] = useState(true);

  // WebSocket for real-time updates
  const { connected: wsConnected, lastStatus } = useWebSocket({
    onStatusUpdate: (newStatus) => {
      setStatus(newStatus);
    },
    onNewApproval: (item) => {
      // Refresh the queue
      loadQueue();
    },
    onProgress: (assetId, stepId, progress) => {
      setGeneratingItems((prev) =>
        prev.map((item) =>
          item.asset_id === assetId && item.step_id === stepId
            ? { ...item, progress }
            : item
        )
      );
    },
  });

  // Load queue data
  const loadQueue = useCallback(async () => {
    try {
      const [statusRes, nextRes, allRes, genRes] = await Promise.all([
        getInteractiveStatus(),
        getNextApproval(),
        getAllApprovals(),
        getGeneratingItems(),
      ]);

      setStatus(statusRes as QueueStatus);
      setCurrentItem(nextRes.item as ApprovalItem | null);
      setPendingItems((allRes.items as ApprovalItem[]).slice(1)); // Skip current
      setGeneratingItems(genRes.items as GeneratingItem[]);

      // Auto-select first option if choose_one mode
      if (nextRes.item) {
        const item = nextRes.item as ApprovalItem;
        if (item.approval_type === "choose_one" && item.options.length > 0) {
          setSelectedOption(item.options[0].id);
        } else {
          setSelectedOption(null);
        }
      }
    } catch (e) {
      console.error("Failed to load queue:", e);
    }
  }, []);

  // Initial load
  useEffect(() => {
    loadQueue();
    const interval = setInterval(loadQueue, 5000);
    return () => clearInterval(interval);
  }, [loadQueue]);

  // Use WebSocket status when available
  useEffect(() => {
    if (lastStatus) {
      setStatus(lastStatus);
    }
  }, [lastStatus]);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!currentItem || loading) return;

      // Number keys for selection
      if (e.key >= "1" && e.key <= "9") {
        const index = parseInt(e.key) - 1;
        if (index < currentItem.options.length) {
          setSelectedOption(currentItem.options[index].id);
        }
        return;
      }

      switch (e.key.toLowerCase()) {
        case "y":
        case "enter":
          if (selectedOption || currentItem.approval_type === "accept_reject") {
            handleApprove();
          }
          break;
        case "n":
          handleReject();
          break;
        case "r":
          handleRegenerate();
          break;
        case "s":
          handleSkip();
          break;
        case "arrowleft":
          navigateOption(-1);
          break;
        case "arrowright":
          navigateOption(1);
          break;
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [currentItem, selectedOption, loading]);

  // Navigate between options
  const navigateOption = (direction: number) => {
    if (!currentItem || currentItem.options.length === 0) return;

    const currentIndex = selectedOption
      ? currentItem.options.findIndex((o) => o.id === selectedOption)
      : -1;
    let newIndex = currentIndex + direction;

    if (newIndex < 0) newIndex = currentItem.options.length - 1;
    if (newIndex >= currentItem.options.length) newIndex = 0;

    setSelectedOption(currentItem.options[newIndex].id);
  };

  // Approve current item
  const handleApprove = async () => {
    if (!currentItem) return;

    setLoading(true);
    try {
      await submitInteractiveApproval({
        item_id: currentItem.id,
        approved: true,
        selected_option_id: selectedOption || undefined,
      });
      await loadQueue();
    } catch (e) {
      console.error("Failed to approve:", e);
    } finally {
      setLoading(false);
    }
  };

  // Reject and regenerate
  const handleReject = async () => {
    if (!currentItem) return;

    setLoading(true);
    try {
      await submitInteractiveApproval({
        item_id: currentItem.id,
        approved: false,
        regenerate: true,
      });
      await loadQueue();
    } catch (e) {
      console.error("Failed to reject:", e);
    } finally {
      setLoading(false);
    }
  };

  // Request regeneration
  const handleRegenerate = async () => {
    if (!currentItem) return;

    setLoading(true);
    try {
      await regenerateItem(currentItem.id);
      await loadQueue();
    } catch (e) {
      console.error("Failed to regenerate:", e);
    } finally {
      setLoading(false);
    }
  };

  // Skip item
  const handleSkip = async () => {
    if (!currentItem) return;

    setLoading(true);
    try {
      await skipApproval(currentItem.id);
      await loadQueue();
    } catch (e) {
      console.error("Failed to skip:", e);
    } finally {
      setLoading(false);
    }
  };

  // Pause/resume generation
  const handlePauseResume = async () => {
    try {
      if (status?.is_paused) {
        await resumeInteractive();
      } else {
        await pauseInteractive();
      }
      await loadQueue();
    } catch (e) {
      console.error("Failed to pause/resume:", e);
    }
  };

  // Stop generation
  const handleStop = async () => {
    try {
      await stopInteractive();
      onComplete?.();
    } catch (e) {
      console.error("Failed to stop:", e);
    }
  };

  // Get image URL for an option
  const getImageUrl = (option: GeneratedOption) => {
    if (option.image_data_url) return option.image_data_url;
    if (option.image_path) return getFileUrl(option.image_path);
    return null;
  };

  // Render option card
  const renderOption = (option: GeneratedOption, index: number) => {
    const isSelected = selectedOption === option.id;
    const imageUrl = getImageUrl(option);

    return (
      <div
        key={option.id}
        onClick={() => setSelectedOption(option.id)}
        className={`relative cursor-pointer rounded-lg overflow-hidden transition-all ${
          isSelected
            ? "ring-2 ring-blue-500 scale-105"
            : "ring-1 ring-gray-700 hover:ring-gray-500"
        }`}
      >
        {option.type === "image" && imageUrl ? (
          <div className="aspect-square bg-gray-800">
            <img
              src={imageUrl}
              alt={`Option ${index + 1}`}
              className="w-full h-full object-cover"
              onClick={(e) => {
                e.stopPropagation();
                setZoomedImage(imageUrl);
              }}
            />
          </div>
        ) : (
          <div className="aspect-square bg-gray-800 p-4 flex items-center justify-center">
            <p className="text-sm text-gray-300 line-clamp-6">{option.text_content}</p>
          </div>
        )}

        {/* Selection indicator */}
        <div
          className={`absolute bottom-2 left-1/2 -translate-x-1/2 w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium ${
            isSelected ? "bg-blue-500 text-white" : "bg-gray-800/80 text-gray-400"
          }`}
        >
          {index + 1}
        </div>
      </div>
    );
  };

  // Progress bar component
  const ProgressBar = ({ value }: { value: number }) => (
    <div className="h-1 bg-gray-700 rounded-full overflow-hidden">
      <div
        className="h-full bg-blue-500 transition-all duration-300"
        style={{ width: `${Math.min(100, Math.max(0, value))}%` }}
      />
    </div>
  );

  return (
    <div className="flex h-screen bg-gray-900">
      {/* Main content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Header */}
        <header className="bg-gray-800 border-b border-gray-700 px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <h1 className="text-xl font-bold">Approval Queue</h1>
              {status && (
                <span className="text-gray-400">
                  {status.completed_assets}/{status.total_assets} complete
                </span>
              )}
            </div>

            <div className="flex items-center gap-4">
              {/* WebSocket status */}
              <div
                className={`w-2 h-2 rounded-full ${
                  wsConnected ? "bg-green-400" : "bg-yellow-400"
                }`}
                title={wsConnected ? "Real-time updates active" : "Polling mode"}
              />

              {/* Controls */}
              <button
                onClick={handlePauseResume}
                className="px-3 py-1 bg-gray-700 hover:bg-gray-600 rounded text-sm"
              >
                {status?.is_paused ? "▶ Resume" : "⏸ Pause"}
              </button>
              <button
                onClick={handleStop}
                className="px-3 py-1 bg-red-600/20 text-red-400 hover:bg-red-600/30 rounded text-sm"
              >
                Stop
              </button>
              <button
                onClick={() => setShowSidebar(!showSidebar)}
                className="px-3 py-1 bg-gray-700 hover:bg-gray-600 rounded text-sm"
              >
                {showSidebar ? "Hide Queue" : "Show Queue"}
              </button>
            </div>
          </div>

          {/* Overall progress */}
          {status && (
            <div className="mt-3">
              <ProgressBar
                value={(status.completed_assets / Math.max(1, status.total_assets)) * 100}
              />
            </div>
          )}
        </header>

        {/* Main area */}
        <main className="flex-1 overflow-auto p-6">
          {!currentItem ? (
            <div className="h-full flex items-center justify-center">
              <div className="text-center">
                {(() => {
                  // Calculate if there's outstanding work
                  const total = status?.total_assets || 0;
                  const done = (status?.completed_assets || 0) + (status?.failed_assets || 0);
                  const outstanding = total - done;
                  const isGenerating = status?.currently_generating || 0;
                  const isPending = status?.pending || 0;
                  const isAwaiting = status?.awaiting_approval || 0;
                  const isRunning = status?.is_running;
                  
                  // Show generating if there are items being generated
                  if (isGenerating > 0) {
                    return (
                      <>
                        <div className="text-6xl mb-4">⏳</div>
                        <h2 className="text-xl font-semibold mb-2">Generating...</h2>
                        <p className="text-gray-400">
                          {isGenerating} items in progress
                        </p>
                        <p className="text-gray-500 text-sm mt-2">
                          {outstanding} assets remaining
                        </p>
                      </>
                    );
                  }
                  
                  // Show waiting if there are pending items or queue is running with outstanding work
                  if (isPending > 0 || (isRunning && outstanding > 0)) {
                    return (
                      <>
                        <div className="text-6xl mb-4">🎯</div>
                        <h2 className="text-xl font-semibold mb-2">
                          {isPending > 0 ? "Processing queue..." : "Waiting for worker..."}
                        </h2>
                        <p className="text-gray-400">
                          {isPending > 0 ? `${isPending} items pending` : `${outstanding} assets need processing`}
                        </p>
                        {!isRunning && (
                          <p className="text-yellow-400 text-sm mt-2">
                            Worker not running - generation may be stuck
                          </p>
                        )}
                      </>
                    );
                  }
                  
                  // Show awaiting if there are items waiting for approval but not shown
                  if (isAwaiting > 0) {
                    return (
                      <>
                        <div className="text-6xl mb-4">👀</div>
                        <h2 className="text-xl font-semibold mb-2">Loading approval items...</h2>
                        <p className="text-gray-400">{isAwaiting} items awaiting review</p>
                      </>
                    );
                  }
                  
                  // Check if there's outstanding work that hasn't started
                  if (outstanding > 0) {
                    return (
                      <>
                        <div className="text-6xl mb-4">⚠️</div>
                        <h2 className="text-xl font-semibold mb-2">Work Outstanding</h2>
                        <p className="text-gray-400">
                          {outstanding} assets still need processing
                        </p>
                        <p className="text-gray-500 text-sm mt-2">
                          {done} of {total} complete
                        </p>
                        {!isRunning && (
                          <p className="text-yellow-400 text-sm mt-2">
                            Generation not running. Try restarting.
                          </p>
                        )}
                      </>
                    );
                  }
                  
                  // Only show "All done" if total > 0 and all are done
                  if (total > 0 && done >= total) {
                    return (
                      <>
                        <div className="text-6xl mb-4">✅</div>
                        <h2 className="text-xl font-semibold mb-2">All done!</h2>
                        <p className="text-gray-400">
                          {status?.completed_assets || 0} assets completed
                          {(status?.failed_assets || 0) > 0 && (
                            <span className="text-red-400 ml-2">
                              ({status?.failed_assets} failed)
                            </span>
                          )}
                        </p>
                        <button
                          onClick={onComplete}
                          className="mt-4 px-6 py-2 bg-green-600 hover:bg-green-500 rounded-lg"
                        >
                          View Results
                        </button>
                      </>
                    );
                  }
                  
                  // No assets loaded yet
                  return (
                    <>
                      <div className="text-6xl mb-4">📭</div>
                      <h2 className="text-xl font-semibold mb-2">No assets loaded</h2>
                      <p className="text-gray-400">
                        Add content in the wizard to start generating
                      </p>
                    </>
                  );
                })()}
              </div>
            </div>
          ) : (
            <div className="max-w-4xl mx-auto">
              {/* Current item info */}
              <div className="mb-6">
                <div className="flex items-center gap-2 text-sm text-gray-400 mb-2">
                  <span>
                    Step {currentItem.step_index + 1} of {currentItem.total_steps}
                  </span>
                  <span>•</span>
                  <span>{currentItem.step_name}</span>
                  {currentItem.attempt > 1 && (
                    <>
                      <span>•</span>
                      <span className="text-yellow-400">
                        Attempt {currentItem.attempt}/{currentItem.max_attempts}
                      </span>
                    </>
                  )}
                </div>
                <h2 className="text-2xl font-bold mb-2">{currentItem.asset_description}</h2>

                {/* Context from previous steps */}
                {Object.keys(currentItem.context).length > 1 && (
                  <div className="bg-gray-800 rounded-lg p-4 mt-4">
                    <h3 className="text-sm font-medium text-gray-400 mb-2">Context</h3>
                    <dl className="space-y-1 text-sm">
                      {Object.entries(currentItem.context)
                        .filter(([k]) => k !== "description" && k !== "id" && k !== "metadata")
                        .map(([key, value]) => (
                          <div key={key} className="flex gap-2">
                            <dt className="text-gray-500 capitalize">{key}:</dt>
                            <dd className="text-gray-300 truncate">{String(value)}</dd>
                          </div>
                        ))}
                    </dl>
                  </div>
                )}
              </div>

              {/* Options grid */}
              <div className="mb-6">
                <h3 className="text-sm font-medium text-gray-400 mb-3">
                  {currentItem.approval_type === "choose_one"
                    ? "Choose one:"
                    : "Accept or reject:"}
                </h3>

                <div
                  className={`grid gap-4 ${
                    currentItem.options.length === 1
                      ? "grid-cols-1 max-w-md mx-auto"
                      : currentItem.options.length === 2
                      ? "grid-cols-2"
                      : currentItem.options.length <= 4
                      ? "grid-cols-2 md:grid-cols-4"
                      : "grid-cols-2 md:grid-cols-3 lg:grid-cols-4"
                  }`}
                >
                  {currentItem.options.map((option, i) => renderOption(option, i))}
                </div>
              </div>

              {/* Action buttons */}
              <div className="flex items-center justify-center gap-4">
                {currentItem.approval_type === "choose_one" ? (
                  <>
                    <button
                      onClick={handleApprove}
                      disabled={!selectedOption || loading}
                      className="px-8 py-3 bg-green-600 hover:bg-green-500 disabled:bg-gray-600 disabled:cursor-not-allowed rounded-lg font-medium transition-colors"
                    >
                      ✓ Select ({selectedOption ? "Enter" : "pick one"})
                    </button>
                    <button
                      onClick={handleRegenerate}
                      disabled={loading}
                      className="px-6 py-3 bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors"
                    >
                      🔄 Regenerate (R)
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      onClick={handleApprove}
                      disabled={loading}
                      className="px-8 py-3 bg-green-600 hover:bg-green-500 disabled:bg-gray-600 rounded-lg font-medium transition-colors"
                    >
                      ✓ Accept (Y)
                    </button>
                    <button
                      onClick={handleReject}
                      disabled={loading}
                      className="px-8 py-3 bg-red-600/20 text-red-400 hover:bg-red-600/30 rounded-lg font-medium transition-colors"
                    >
                      ✗ Reject (N)
                    </button>
                  </>
                )}
                <button
                  onClick={handleSkip}
                  disabled={loading}
                  className="px-6 py-3 text-gray-400 hover:text-gray-200 transition-colors"
                >
                  Skip (S)
                </button>
              </div>

              {/* Keyboard hints */}
              <div className="mt-6 text-center text-gray-500 text-sm">
                <span className="inline-flex items-center gap-4">
                  <span>1-{currentItem.options.length} Select</span>
                  <span>←/→ Navigate</span>
                  <span>R Regenerate</span>
                  <span>S Skip</span>
                </span>
              </div>
            </div>
          )}
        </main>
      </div>

      {/* Sidebar */}
      {showSidebar && (
        <aside className="w-80 bg-gray-800 border-l border-gray-700 overflow-auto">
          <div className="p-4">
            <h2 className="font-semibold mb-4">Queue Status</h2>

            {/* Awaiting approval */}
            <div className="mb-6">
              <h3 className="text-sm text-gray-400 mb-2">
                ⏳ Awaiting Approval ({status?.awaiting_approval || 0})
              </h3>
              <div className="space-y-2">
                {currentItem && (
                  <div className="bg-blue-500/20 rounded p-2 text-sm">
                    <span className="text-blue-400">▶</span> {currentItem.asset_description}
                    <span className="text-gray-500 ml-1">({currentItem.step_name})</span>
                  </div>
                )}
                {pendingItems.slice(0, 5).map((item) => (
                  <div key={item.id} className="bg-gray-700/50 rounded p-2 text-sm truncate">
                    {item.asset_description}
                    <span className="text-gray-500 ml-1">({item.step_name})</span>
                  </div>
                ))}
                {pendingItems.length > 5 && (
                  <div className="text-gray-500 text-sm">
                    +{pendingItems.length - 5} more
                  </div>
                )}
              </div>
            </div>

            {/* Currently generating */}
            <div className="mb-6">
              <h3 className="text-sm text-gray-400 mb-2">
                ⚡ Generating ({status?.currently_generating || 0})
              </h3>
              <div className="space-y-2">
                {generatingItems.map((item) => (
                  <div key={item.id} className="bg-gray-700/50 rounded p-2">
                    <div className="text-sm truncate mb-1">{item.asset_description}</div>
                    <div className="flex items-center gap-2">
                      <ProgressBar value={item.progress} />
                      <span className="text-xs text-gray-500">
                        {Math.round(item.progress)}%
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Stats */}
            {status && (
              <div className="bg-gray-700/50 rounded p-3">
                <h3 className="text-sm text-gray-400 mb-2">Summary</h3>
                <dl className="space-y-1 text-sm">
                  <div className="flex justify-between">
                    <dt className="text-gray-500">Total</dt>
                    <dd>{status.total_assets}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-gray-500">Completed</dt>
                    <dd className="text-green-400">{status.completed_assets}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-gray-500">Failed</dt>
                    <dd className="text-red-400">{status.failed_assets}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-gray-500">Pending</dt>
                    <dd>{status.pending}</dd>
                  </div>
                </dl>
              </div>
            )}
          </div>
        </aside>
      )}

      {/* Image zoom modal */}
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
  );
}
