export type MemberRole = 'owner' | 'admin' | 'viewer'

export interface Member {
  userId: string | null
  username: string | null
  role: MemberRole
  addedBy?: string
  addedAt?: string
}

export function memberKey(member: Member): string {
  return member.userId ?? 'u:' + member.username
}

export async function listMembers(): Promise<Member[]> {
  const response = await fetch('/api/members')
  if (!response.ok) {
    throw new Error('Not authorized to view the team.')
  }
  const json = (await response.json()) as { members?: Member[] }
  return json.members ?? []
}

export async function addMember(input: { username?: string; userId?: string; role: 'admin' | 'viewer' }): Promise<void> {
  const response = await fetch('/api/members', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!response.ok) {
    const json = (await response.json().catch(() => ({}))) as { detail?: string }
    throw new Error(json.detail ?? 'Could not add the member.')
  }
}

export async function setMemberRole(key: string, role: 'admin' | 'viewer'): Promise<void> {
  const response = await fetch(`/api/members/${encodeURIComponent(key)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role }),
  })
  if (!response.ok) {
    const json = (await response.json().catch(() => ({}))) as { detail?: string }
    throw new Error(json.detail ?? 'Could not change the role.')
  }
}

export async function removeMember(key: string): Promise<void> {
  const response = await fetch(`/api/members/${encodeURIComponent(key)}`, { method: 'DELETE' })
  if (!response.ok) {
    const json = (await response.json().catch(() => ({}))) as { detail?: string }
    throw new Error(json.detail ?? 'Could not remove the member.')
  }
}
