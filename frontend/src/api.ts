import type { FamilyInfo, Member, Message } from './types'

const json = async (res: Response) => {
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export const api = {
  getMembers: (): Promise<Member[]> => fetch('/api/members').then(json),

  addMember: (body: Partial<Member>): Promise<Member> =>
    fetch('/api/members', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(json),

  updateMember: (id: string, body: Partial<Member>): Promise<Member> =>
    fetch(`/api/members/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(json),

  deleteMember: (id: string): Promise<{ ok: boolean; error?: string }> =>
    fetch(`/api/members/${id}`, { method: 'DELETE' }).then(json),

  getFamilies: (): Promise<FamilyInfo[]> => fetch('/api/families').then(json),

  getModels: (cli: string, family: string): Promise<{ models: string[]; error?: string }> =>
    fetch(`/api/models?cli=${encodeURIComponent(cli)}&family=${encodeURIComponent(family)}`)
      .then(json),

  discuss: (
    question: string,
    maxRounds: number,
    skipTriage = false,
  ): Promise<{ ok: boolean; error?: string }> =>
    fetch('/api/discuss', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, max_rounds: maxRounds, skip_triage: skipTriage }),
    }).then(json),

  stop: (): Promise<{ ok: boolean }> => fetch('/api/stop', { method: 'POST' }).then(json),

  interject: (content: string): Promise<{ ok: boolean; error?: string }> =>
    fetch('/api/interject', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    }).then(json),

  clear: (): Promise<{ ok: boolean; error?: string }> =>
    fetch('/api/clear', { method: 'POST' }).then(json),

  getMessages: (): Promise<Message[]> => fetch('/api/messages').then(json),
}
