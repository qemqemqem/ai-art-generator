import { useEffect, useRef, useCallback, useState } from "react";
import { getWebSocketUrl } from "../api/client";
import type { WSMessage, QueueStatus, ApprovalItem } from "../types";

interface UseWebSocketOptions {
  onStatusUpdate?: (status: QueueStatus) => void;
  onNewApproval?: (item: ApprovalItem) => void;
  onProgress?: (assetId: string, stepId: string, progress: number) => void;
  onComplete?: (assetId: string, stepId: string) => void;
  onError?: (assetId: string, stepId: string, error: string) => void;
  reconnectInterval?: number;
}

export function useWebSocket(options: UseWebSocketOptions = {}) {
  const {
    onStatusUpdate,
    onNewApproval,
    onProgress,
    onComplete,
    onError,
    reconnectInterval = 3000,
  } = options;

  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [lastStatus, setLastStatus] = useState<QueueStatus | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    const ws = new WebSocket(getWebSocketUrl());

    ws.onopen = () => {
      setConnected(true);
      console.log("WebSocket connected");
    };

    ws.onclose = () => {
      setConnected(false);
      console.log("WebSocket disconnected");

      // Reconnect after delay
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      reconnectTimeoutRef.current = window.setTimeout(() => {
        connect();
      }, reconnectInterval);
    };

    ws.onerror = (error) => {
      console.error("WebSocket error:", error);
    };

    ws.onmessage = (event) => {
      try {
        const message: WSMessage = JSON.parse(event.data);

        switch (message.type) {
          case "connected":
          case "queue_update":
            if (message.status) {
              setLastStatus(message.status);
              onStatusUpdate?.(message.status);
            }
            break;

          case "new_approval":
            if (message.item) {
              onNewApproval?.(message.item);
            }
            break;

          case "generation_progress":
            if (message.asset_id && message.step_id && message.progress !== undefined) {
              onProgress?.(message.asset_id, message.step_id, message.progress);
            }
            break;

          case "generation_complete":
            if (message.asset_id && message.step_id) {
              onComplete?.(message.asset_id, message.step_id);
            }
            break;

          case "generation_error":
            if (message.asset_id && message.step_id && message.error) {
              onError?.(message.asset_id, message.step_id, message.error);
            }
            break;
        }
      } catch (e) {
        console.error("Failed to parse WebSocket message:", e);
      }
    };

    wsRef.current = ws;
  }, [onStatusUpdate, onNewApproval, onProgress, onComplete, onError, reconnectInterval]);

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  }, []);

  const sendPing = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send("ping");
    }
  }, []);

  // Connect on mount, disconnect on unmount
  // Note: Using empty deps to avoid reconnect loops from React Strict Mode
  useEffect(() => {
    connect();
    return () => {
      disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Periodic ping to keep connection alive
  useEffect(() => {
    const interval = setInterval(sendPing, 30000);
    return () => clearInterval(interval);
  }, [sendPing]);

  return {
    connected,
    lastStatus,
    reconnect: connect,
    disconnect,
  };
}
