import type { components } from "./schema";

type Schemas = components["schemas"];

export type LoginChannel = Schemas["ChallengeCreateRequest"]["target_channel"];
export type LoginChallenge = Schemas["ChallengeCreateResponse"];
export type ChallengeStatus = Schemas["ChallengeStatusResponse"];
export type SessionInfo = Schemas["SessionResponse"];
export type Capabilities = Schemas["CapabilitiesResponse"];

export type BatchSubmitInput = Schemas["BatchSaveRequest"];
export type BatchSubmitItem = Schemas["BatchItemResponse"];
export type BatchSubmitResponse = Schemas["BatchSaveResponse"];

export type Chapter = Schemas["ChapterResponse"];
export type LibraryItem = Schemas["LibraryItemResponse"];
export type LibraryLifecycle = LibraryItem["lifecycle"];
export type LibraryPageResponse = Schemas["LibraryPageResponse"];
export type LibraryItemSummary = Pick<
  LibraryItem,
  | "public_id"
  | "lifecycle"
  | "title"
  | "author"
  | "cover_url"
  | "duration_sec"
  | "saved_at"
  | "why_saved"
  | "url"
  | "error_code"
  | "available_actions"
>;

export type TranscriptBlock = Schemas["TranscriptBlockResponse"];
export type TranscriptPage = Schemas["TranscriptPageResponse"];
