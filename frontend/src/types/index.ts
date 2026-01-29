// API Types matching backend models

export type AssetStatus =
  | "pending"
  | "processing"
  | "awaiting_approval"
  | "approved"
  | "rejected"
  | "completed"
  | "failed";

export interface StyleConfig {
  global_prompt_prefix: string;
  global_prompt_suffix: string;
  negative_prompt: string;
  aspect_ratio: string;
  image_size: string;
}

export interface PipelineStep {
  id: string;
  type: string;
  provider?: string;
  prompt_template?: string;
  requires_approval: boolean;
  variations: number;
  parallel_with?: string[];
  config: Record<string, unknown>;
}

export interface ProjectConfig {
  name: string;
  description: string;
  style: StyleConfig;
  pipeline: PipelineStep[];
  default_image_provider: string;
  default_text_provider: string;
  settings: Record<string, unknown>;
}

export interface GeneratedArtifact {
  type: string;
  path?: string;
  content?: string;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface StepResult {
  step_id: string;
  status: AssetStatus;
  variations: GeneratedArtifact[];
  selected_index?: number;
  approved: boolean;
  error?: string;
  started_at?: string;
  completed_at?: string;
}

export interface Asset {
  id: string;
  input_description: string;
  input_metadata: Record<string, unknown>;
  status: AssetStatus;
  current_step?: string;
  results: Record<string, StepResult>;
  created_at: string;
  updated_at: string;
}

export interface QueueItem {
  asset: Asset;
  step_id: string;
  step_result: StepResult;
  step_config?: PipelineStep;
}

export interface Project {
  name: string;
  path: string;
  config: ProjectConfig;
  asset_count?: number;
}

// Interactive Mode Types

export type ApprovalType = "choose_one" | "accept_reject";

export interface GeneratedOption {
  id: string;
  type: "image" | "text";
  image_path?: string;
  thumbnail_path?: string;
  image_data_url?: string;
  text_content?: string;
  prompt_used?: string;
  generation_params: Record<string, unknown>;
  created_at: string;
}

export interface ApprovalItem {
  id: string;
  asset_id: string;
  asset_description: string;
  step_id: string;
  step_name: string;
  step_index: number;
  total_steps: number;
  approval_type: ApprovalType;
  options: GeneratedOption[];
  context: Record<string, unknown>;
  attempt: number;
  max_attempts: number;
  created_at: string;
}

export interface GeneratingItem {
  id: string;
  asset_id: string;
  asset_description: string;
  step_id: string;
  step_name: string;
  progress: number;
  started_at: string;
}

export interface QueueStatus {
  total_assets: number;
  completed_assets: number;
  failed_assets: number;
  awaiting_approval: number;
  currently_generating: number;
  pending: number;
  is_running: boolean;
  is_paused: boolean;
}

export interface ApprovalDecision {
  item_id: string;
  approved: boolean;
  selected_option_id?: string;
  regenerate?: boolean;
}

// WebSocket message types
export type WSMessageType =
  | "connected"
  | "queue_update"
  | "new_approval"
  | "generation_progress"
  | "generation_complete"
  | "generation_error";

export interface WSMessage {
  type: WSMessageType;
  timestamp?: string;
  status?: QueueStatus;
  item?: ApprovalItem;
  asset_id?: string;
  step_id?: string;
  progress?: number;
  error?: string;
}
