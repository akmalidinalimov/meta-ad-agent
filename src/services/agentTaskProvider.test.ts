import { describe, expect, it, vi } from 'vitest'
import { createAgentTask, getAgentCommandCenter } from './agentTaskProvider'

describe('agentTaskProvider', () => {
  it('loads tasks and agents for the command center', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ tasks: [{ id: 'task_1', source: 'dashboard', status: 'planning' }] }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ agents: [{ id: 'orchestrator', name: 'Orchestrator Agent' }] }),
      })
    vi.stubGlobal('fetch', fetchMock)

    const result = await getAgentCommandCenter()

    expect(result.tasks).toHaveLength(1)
    expect(result.agents[0].id).toBe('orchestrator')
    expect(fetchMock).toHaveBeenCalledWith('/api/tasks')
    expect(fetchMock).toHaveBeenCalledWith('/api/agents')
  })

  it('creates a dashboard task with optional approval preparation', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, task: { id: 'task_2', status: 'needs_approval' } }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await createAgentTask({
      source: 'dashboard',
      command: 'Create a paused campaign',
      prepareApproval: true,
    })

    expect(result.task.status).toBe('needs_approval')
    expect(fetchMock).toHaveBeenCalledWith('/api/tasks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source: 'dashboard',
        command: 'Create a paused campaign',
        prepareApproval: true,
      }),
    })
  })
})
