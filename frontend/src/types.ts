export interface KnowledgeBase { id: string; name: string; description: string; created_at?: string }
export interface DocumentRow { id: string; knowledge_base_id: string; name: string; file_type: string; size: number; status: string; progress: number; chunk_count: number; error_code?: string | null; created_at?: string }
export interface ChatSession { id: string; knowledge_base_id: string; title: string; created_at?: string }
export interface Citation { source_id: number; chunk_id: string; document_id: string; source_name: string; text: string; source_location: { format?: string; page?: number; section?: string } }
export interface ChatMessage { id: string; role: 'user' | 'assistant'; content: string; citations: Citation[]; created_at?: string }
