export type Action = 'reply' | 'agree' | 'disagree' | 'ask' | 'new_topic' | 'summary'

export interface Member {
  id: string
  name: string
  cli: string
  model: string | null
  role: string
  color: string
  session_id: string | null
  enabled: boolean
  summary_only: boolean
}

export interface Message {
  id: string
  member_id: string
  member_name: string
  round: number
  action: Action
  target_id: string | null
  content: string
  citations: string[]
  timestamp: number
  status: 'done' | 'error'
  meta: {
    cli?: string
    model?: string | null
    session_id?: string | null
    tokens?: Record<string, number> | null
    cost?: number | null
    raw?: string
  }
}

export interface CliInfo {
  name: string
  installed: boolean
}

export interface WsEvent {
  type: 'init' | 'message' | 'typing' | 'round_start' | 'finished' | 'cleared' | 'error'
  message?: Message
  member_id?: string
  member_name?: string
  round?: number
  max_rounds?: number
  summary?: boolean
  running?: boolean
  question?: string
  messages?: Message[]
  stopped?: boolean
  error?: string
}
