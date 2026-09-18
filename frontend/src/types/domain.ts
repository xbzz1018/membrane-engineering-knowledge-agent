export type Role = 'admin' | 'design_engineer' | 'material_procurement' | 'reviewer'

export interface Principal {
  user_id: string
  username: string
  tenant_id: string
  role: Role
}

export interface Project {
  id: string
  name: string
  status: string
  lock_version?: number
}

export interface SourceRef {
  source_id: string
  title: string
  source_type: string
  location?: string
  excerpt?: string
  date?: string
  version?: string
  url?: string
}

export interface DocumentItem {
  id: string
  document_id?: string
  filename: string
  content_type: string
  status: string
  parser: string
  parser_version?: string
  parse_method: string
  data_classification: string
  version: number
  sha256: string
  embedding_model?: string
  created_at?: string
  updated_at?: string
  error_type?: string
}

export interface ReviewIssue {
  issue_id: string
  domain: string
  issue_type: string
  summary: string
  severity: 'info' | 'warning' | 'conflict'
  actual_value?: string
  expected_value?: string
  recommendation?: string
  status: string
  evidence_refs?: Array<{ evidence_id: string; filename: string; location: string; version: string }>
}

export interface ReviewItem {
  review_id: string
  project_id: string
  question?: string
  status: string
  engine: string
  review_mode?: 'full' | 'focused'
  report?: string
  conflict_count?: number
  issue_count?: number
  lock_version: number
  review_plan?: Record<string, any>
  worker_results?: Record<string, any>
  issues?: ReviewIssue[]
  sources?: SourceRef[]
  created_at?: string
  workflow?: Record<string, any> | null
}

export interface PageResult<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface CatalogItem {
  spec_id?: string
  price_id?: string
  manufacturer?: string
  material: string
  product_reference?: string
  specification: string
  application?: string
  project_id?: string
  unit?: string
  min_price?: number
  max_price?: number
  currency?: string
  region?: string
  effective_date?: string
  source_url: string
  source_version: string
  source_page?: number
  source_page_count?: number
  license: string
  retrieved_at: string
  source_sha256: string
  visibility: string
  synthetic: boolean
  disclaimer?: string
  status: string
  lock_version: number
}
