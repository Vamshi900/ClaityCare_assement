export interface RuleNode {
  rule_id: string
  rule_text: string
  operator?: "AND" | "OR"
  rules?: RuleNode[]
}

export interface CriteriaTree {
  title: string
  insurance_name: string
  rules: RuleNode
}

export interface Policy {
  id: string
  title: string
  guideline_code: string | null
  version: string | null
  pdf_url: string
  source_page_url: string
  discovered_at: string
  status: string
  has_download: boolean
  has_structured_tree: boolean
}

export interface ExtractionVersion {
  version: number
  is_current: boolean
  structured_at: string
  llm_metadata: Record<string, any> | null
  validation_error: string | null
}

export interface PolicyDetail extends Policy {
  download_status: string | null
  structured_json: CriteriaTree | null
}

export interface Job {
  id: string
  type: string
  status: string
  source_url: string | null
  started_at: string | null
  finished_at: string | null
  metadata_: Record<string, any> | null
  error: string | null
  created_at: string
}

export interface Stats {
  total_policies: number
  total_downloaded: number
  total_structured: number
  total_failed_downloads: number
  total_validation_errors: number
}
