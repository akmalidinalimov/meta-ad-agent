import { useEffect, useState, type FormEvent } from 'react'
import { ShieldCheck, Trash2, UserPlus, Users } from 'lucide-react'
import { PanelHeading } from '../shared/PanelHeading'
import {
  addMember,
  listMembers,
  memberKey,
  removeMember,
  setMemberRole,
  type Member,
} from '../../../services/members'

// Owner/admins manage who can use the agent and at what level. Mirrors the
// Telegram 👥 Team panel; both write through /api/members.
export function TeamPanel() {
  const [members, setMembers] = useState<Member[]>([])
  const [identifier, setIdentifier] = useState('')
  const [role, setRole] = useState<'admin' | 'viewer'>('viewer')
  const [message, setMessage] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = async () => {
    try {
      setMembers(await listMembers())
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not load the team.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    let cancelled = false
    void listMembers()
      .then((next) => {
        if (!cancelled) {
          setMembers(next)
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setMessage(error instanceof Error ? error.message : 'Could not load the team.')
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  const handleAdd = async (event: FormEvent) => {
    event.preventDefault()
    const value = identifier.trim()
    if (!value) {
      return
    }
    const input = /^\d+$/.test(value) ? { userId: value, role } : { username: value, role }
    setMessage('Adding…')
    try {
      await addMember(input)
      setIdentifier('')
      setMessage(`Added ${value} as ${role}.`)
      await refresh()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not add the member.')
    }
  }

  const handleRole = async (member: Member, nextRole: 'admin' | 'viewer') => {
    setMessage('Updating role…')
    try {
      await setMemberRole(memberKey(member), nextRole)
      await refresh()
      setMessage('Role updated.')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not change the role.')
    }
  }

  const handleRemove = async (member: Member) => {
    const label = member.username ? '@' + member.username : member.userId
    if (!window.confirm(`Remove ${label} from the team?`)) {
      return
    }
    setMessage('Removing…')
    try {
      await removeMember(memberKey(member))
      await refresh()
      setMessage('Removed.')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not remove the member.')
    }
  }

  return (
    <section className="team-panel">
      <article className="panel">
        <PanelHeading eyebrow="Access" title="Team & roles" icon={Users} />
        <p className="team-intro">
          Admins can see and change everything (same as the owner). Viewers can watch the dashboards
          but can't make changes. The owner can't be changed or removed.
        </p>

        <form className="team-add-form" onSubmit={handleAdd}>
          <input
            value={identifier}
            onChange={(event) => setIdentifier(event.target.value)}
            placeholder="@username or numeric Telegram ID"
            aria-label="New member username or id"
          />
          <select value={role} onChange={(event) => setRole(event.target.value as 'admin' | 'viewer')} aria-label="Role">
            <option value="viewer">Viewer</option>
            <option value="admin">Admin</option>
          </select>
          <button className="sync-button" type="submit">
            <UserPlus size={16} /> Add member
          </button>
        </form>

        {message && <small className="sync-message">{message}</small>}

        <div className="team-list">
          {loading && <small>Loading team…</small>}
          {!loading && members.map((member) => {
            const label = member.username ? '@' + member.username : member.userId
            const isOwner = member.role === 'owner'
            return (
              <div className={`team-row ${member.role}`} key={memberKey(member)}>
                <div className="team-row-id">
                  {isOwner ? <ShieldCheck size={16} /> : <Users size={16} />}
                  <strong>{label}</strong>
                  <span className="team-role-chip">{member.role}</span>
                </div>
                {!isOwner && (
                  <div className="team-row-actions">
                    <select
                      value={member.role}
                      onChange={(event) => void handleRole(member, event.target.value as 'admin' | 'viewer')}
                      aria-label={`Role for ${label}`}
                    >
                      <option value="viewer">Viewer</option>
                      <option value="admin">Admin</option>
                    </select>
                    <button
                      className="icon-button danger-button"
                      type="button"
                      onClick={() => void handleRemove(member)}
                      aria-label={`Remove ${label}`}
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </article>
    </section>
  )
}
