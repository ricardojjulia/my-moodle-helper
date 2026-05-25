import { useEffect, useState } from 'react'
import {
  Stack, TextInput, PasswordInput, Button, Group,
  Title, Text, Alert, Badge, Paper, Loader,
  ActionIcon, Tooltip, ThemeIcon, SimpleGrid, Progress,
  Box, Divider, Select, Collapse, CopyButton, Code, Table,
} from '@mantine/core'
import { useForm } from '@mantine/form'
import { notifications } from '@mantine/notifications'
import {
  IconCheck, IconX, IconWifi, IconCloud, IconTrash,
  IconPlayerPlay, IconPlus, IconBook, IconCategory,
  IconUsers, IconUserCheck, IconUserOff, IconUserX,
  IconEyeOff, IconShield, IconDeviceMobile,
  IconApi, IconRefresh, IconSchool, IconRobot,
  IconBrain, IconServer, IconExternalLink,
  IconClock, IconCalendarEvent, IconLock, IconLockOpen, IconCopy,
  IconDownload,
} from '@tabler/icons-react'
import {
  api,
  type AdminAuditLog,
  type AdminPolicy,
  type AppSettings,
  type MoodleInstance,
  type MoodleWriteCapabilities,
  type ReviewSchedule,
  tokenStore,
} from '../api/client'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'

// ── LLM provider presets ──────────────────────────────────────────────────────

const LLM_PROVIDERS = [
  { id: 'local',      label: 'Local LLM',  url: '',                              needsKey: false, icon: <IconServer  size={14} />, color: 'gray'   },
  { id: 'openai',     label: 'OpenAI',     url: 'https://api.openai.com/v1',     needsKey: true,  icon: <IconBrain   size={14} />, color: 'green'  },
  { id: 'openrouter', label: 'OpenRouter', url: 'https://openrouter.ai/api/v1',  needsKey: true,  icon: <IconRobot   size={14} />, color: 'violet' },
  { id: 'anthropic',  label: 'Claude',     url: 'https://api.anthropic.com/v1',  needsKey: true,  icon: <IconBrain   size={14} />, color: 'orange' },
  { id: 'custom',     label: 'Custom',     url: '',                              needsKey: true,  icon: <IconApi     size={14} />, color: 'blue'   },
] as const

const PROVIDER_MODELS: Record<string, string[]> = {
  openai:     ['gpt-4o', 'gpt-4o-mini', 'o3-mini', 'gpt-4-turbo'],
  openrouter: ['anthropic/claude-opus-4-7', 'anthropic/claude-sonnet-4-6', 'openai/gpt-4o', 'google/gemini-2.5-pro', 'meta-llama/llama-3.3-70b-instruct'],
  anthropic:  ['claude-opus-4-7', 'claude-sonnet-4-6', 'claude-haiku-4-5-20251001'],
}

// ── Scheduled reviews section ─────────────────────────────────────────────────

const SCHED_AGENTS = [
  {
    id: 'theological-reviewer', label: 'Theological Reviewer', color: 'violet',
    context: `# Role: Evangelical Theological Course Reviewer\nYou are a senior academic auditor for a conservative Protestant/Evangelical theological college. Audit the course for biblical soundness, academic rigor, structural completeness (syllabus, glossary, bibliography, 5 modules, 30+ quiz questions, discussion forums), and Evangelical alignment.`,
  },
  {
    id: 'student-critic', label: 'Student Critic', color: 'orange',
    context: `# Role: Evangelical Student & Content Critic\nYou are a high-achieving, critical-thinking student at an Evangelical Theological College. Stress-test the course content for theological depth, modern relevance, practical application, and assignment fairness.`,
  },
]

function ScheduledReviewsSection({ defaultModel }: { defaultModel: string }) {
  const { t } = useTranslation()
  const [schedules,   setSchedules]   = useState<ReviewSchedule[]>([])
  const [courses,     setCourses]     = useState<{ value: string; label: string }[]>([])
  const [loading,     setLoading]     = useState(false)
  const [running,     setRunning]     = useState(false)
  const [showForm,    setShowForm]    = useState(false)
  const [deleting,    setDeleting]    = useState<number | null>(null)
  const [newShort,    setNewShort]    = useState<string | null>(null)
  const [newAgent,    setNewAgent]    = useState<string>(SCHED_AGENTS[0].id)
  const [newFreq,     setNewFreq]     = useState<string>('weekly')
  const [newModel,    setNewModel]    = useState(defaultModel)
  const [saving,      setSaving]      = useState(false)

  const load = () => {
    setLoading(true)
    Promise.all([
      api.schedules.list(),
      api.courses.list(),
    ]).then(([scheds, libCourses]) => {
      setSchedules(scheds)
      setCourses(libCourses.map(c => ({ value: c.shortname, label: `${c.shortname} — ${c.fullname}` })))
    }).catch(e => notifications.show({ title: 'Error', message: e.message, color: 'red' }))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const overdueCount = schedules.filter(s =>
    s.enabled && new Date(s.next_run_at + 'Z') <= new Date()
  ).length

  const runOverdue = async () => {
    setRunning(true)
    try {
      const res = await api.schedules.runOverdue()
      notifications.show({
        title: t('cfg.notif_reviews_done', { count: res.triggered }),
        message: res.errors.length > 0 ? `Errors: ${res.errors.join(', ')}` : 'All scheduled reviews ran successfully.',
        color: res.errors.length > 0 ? 'orange' : 'green',
      })
      load()
    } catch (e: any) {
      notifications.show({ title: 'Error', message: e.message, color: 'red' })
    } finally {
      setRunning(false)
    }
  }

  const createSchedule = async () => {
    if (!newShort) return
    const agent = SCHED_AGENTS.find(a => a.id === newAgent)!
    setSaving(true)
    try {
      await api.schedules.create({
        shortname:     newShort,
        agent_id:      agent.id,
        agent_label:   agent.label,
        agent_color:   agent.color,
        agent_context: agent.context,
        model_id:      newModel,
        frequency:     newFreq,
      })
      notifications.show({ title: t('cfg.notif_sched_created'), message: t('cfg.notif_sched_created_msg', { shortname: newShort, freq: newFreq }), color: 'green' })
      setShowForm(false)
      load()
    } catch (e: any) {
      notifications.show({ title: 'Error', message: e.message, color: 'red' })
    } finally {
      setSaving(false)
    }
  }

  const removeSchedule = async (id: number) => {
    setDeleting(id)
    try {
      await api.schedules.delete(id)
      setSchedules(prev => prev.filter(s => s.id !== id))
    } catch (e: any) {
      notifications.show({ title: 'Error', message: e.message, color: 'red' })
    } finally {
      setDeleting(null)
    }
  }

  const fmtDate = (iso: string | null) => {
    if (!iso) return '—'
    return new Date(iso + 'Z').toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  }

  return (
    <Paper withBorder p="md" radius="md">
      <Group justify="space-between" mb="sm" wrap="nowrap">
        <Group gap="sm">
          <ThemeIcon size="sm" color="violet" variant="light">
            <IconCalendarEvent size={12} />
          </ThemeIcon>
          <Title order={5}>{t('cfg.sched_title')}</Title>
          {overdueCount > 0 && (
            <Badge size="xs" color="orange">{t('cfg.sched_overdue', { count: overdueCount })}</Badge>
          )}
        </Group>
        <Group gap="xs">
          {overdueCount > 0 && (
            <Button
              size="xs" color="orange" variant="light"
              leftSection={running ? <Loader size="xs" /> : <IconPlayerPlay size={14} />}
              onClick={runOverdue}
              disabled={running}
            >
              {t('cfg.sched_run_overdue', { count: overdueCount })}
            </Button>
          )}
          <Button
            size="xs" variant="light"
            leftSection={<IconPlus size={14} />}
            onClick={() => setShowForm(f => !f)}
          >
            {showForm ? t('cfg.sched_cancel') : t('cfg.sched_add')}
          </Button>
        </Group>
      </Group>

      {/* Add schedule form */}
      <Collapse in={showForm}>
        <Paper withBorder p="sm" radius="sm" mb="sm" bg="var(--mantine-color-gray-0)">
          <Stack gap="sm">
            <Group grow gap="sm">
              <Select
                label={t('cfg.sched_course')}
                placeholder={t('cfg.sched_course_ph')}
                data={courses}
                value={newShort}
                onChange={setNewShort}
                searchable
                size="xs"
              />
              <Select
                label={t('cfg.sched_agent')}
                data={SCHED_AGENTS.map(a => ({ value: a.id, label: a.label }))}
                value={newAgent}
                onChange={v => setNewAgent(v ?? SCHED_AGENTS[0].id)}
                size="xs"
              />
            </Group>
            <Group grow gap="sm">
              <Select
                label={t('cfg.sched_freq')}
                data={[
                  { value: 'daily',   label: t('cfg.sched_daily') },
                  { value: 'weekly',  label: t('cfg.sched_weekly') },
                  { value: 'monthly', label: t('cfg.sched_monthly') },
                ]}
                value={newFreq}
                onChange={v => setNewFreq(v ?? 'weekly')}
                size="xs"
              />
              <TextInput
                label={t('cfg.sched_model_id')}
                placeholder={t('cfg.sched_model_ph')}
                value={newModel}
                onChange={e => setNewModel(e.currentTarget.value)}
                size="xs"
              />
            </Group>
            <Group justify="flex-end">
              <Button
                size="xs"
                leftSection={saving ? <Loader size="xs" /> : <IconCheck size={14} />}
                onClick={createSchedule}
                disabled={!newShort || saving}
              >
                {t('cfg.sched_save')}
              </Button>
            </Group>
          </Stack>
        </Paper>
      </Collapse>

      {/* Schedule list */}
      {loading && <Loader size="sm" />}
      {!loading && schedules.length === 0 && (
        <Text size="xs" c="dimmed" ta="center" py="md">
          {t('cfg.sched_empty')}
        </Text>
      )}
      {schedules.map(s => {
        const isOverdue = s.enabled === 1 && new Date(s.next_run_at + 'Z') <= new Date()
        return (
          <Paper key={s.id} withBorder p="sm" radius="sm" mb="xs"
                 style={{ borderColor: isOverdue ? 'var(--mantine-color-orange-4)' : undefined }}>
            <Group justify="space-between" wrap="nowrap">
              <Box>
                <Group gap={6} mb={2}>
                  <Text size="sm" fw={600}>{s.shortname}</Text>
                  <Badge size="xs" color={SCHED_AGENTS.find(a => a.id === s.agent_id)?.color || 'gray'}>
                    {s.agent_label}
                  </Badge>
                  <Badge size="xs" variant="outline">{s.frequency}</Badge>
                  {isOverdue && <Badge size="xs" color="orange">{t('cfg.sched_overdue_badge')}</Badge>}
                </Group>
                <Group gap={8}>
                  <Group gap={4}>
                    <IconClock size={11} />
                    <Text size="xs" c="dimmed">{t('cfg.sched_next')} {fmtDate(s.next_run_at)}</Text>
                  </Group>
                  {s.last_run_at && (
                    <Text size="xs" c="dimmed">{t('cfg.sched_last')} {fmtDate(s.last_run_at)}</Text>
                  )}
                </Group>
              </Box>
              <Tooltip label={t('cfg.sched_delete')} withArrow>
                <ActionIcon
                  size="sm" color="red" variant="subtle"
                  loading={deleting === s.id}
                  onClick={() => removeSchedule(s.id)}
                >
                  <IconTrash size={13} />
                </ActionIcon>
              </Tooltip>
            </Group>
          </Paper>
        )
      })}
    </Paper>
  )
}

// ── Settings page ─────────────────────────────────────────────────────────────

// ── Canvas Settings Panel ─────────────────────────────────────────────────────

function CanvasSettingsPanel() {
  const [canvasUrl,   setCanvasUrl]   = useState('')
  const [canvasToken, setCanvasToken] = useState('')
  const [testing,     setTesting]     = useState(false)
  const [pingResult,  setPingResult]  = useState<{ ok: boolean; msg: string } | null>(null)
  const [saved,       setSaved]       = useState(false)

  useEffect(() => {
    api.settings.get().then(s => {
      setCanvasUrl((s as any).canvas_url || '')
    }).catch(() => {})
  }, [])

  const testCanvas = async () => {
    setTesting(true)
    setPingResult(null)
    try {
      await api.settings.save({ canvas_url: canvasUrl, canvas_token: canvasToken || undefined } as any)
      const res = await api.canvas.ping()
      setPingResult({ ok: true, msg: `Connected as ${res.fullname} (${res.username})` })
      setSaved(true)
    } catch (e: any) {
      setPingResult({ ok: false, msg: e.message })
    } finally {
      setTesting(false)
    }
  }

  return (
    <Paper withBorder p="md" radius="md">
      <Group gap="xs" mb="sm">
        <ThemeIcon size="sm" color="orange" variant="light">
          <IconCloud size={12} />
        </ThemeIcon>
        <Title order={5}>Canvas LMS</Title>
        {saved && <Badge size="xs" color="green">Configured</Badge>}
      </Group>
      <Stack gap="sm">
        <TextInput
          label="Canvas URL"
          placeholder="http://canvas.docker"
          value={canvasUrl}
          onChange={e => { setCanvasUrl(e.currentTarget.value); setSaved(false) }}
        />
        <PasswordInput
          label="API Token"
          description="Generate at: Canvas → Account → Settings → New Access Token"
          placeholder="Paste your Canvas access token"
          value={canvasToken}
          onChange={e => { setCanvasToken(e.currentTarget.value); setSaved(false) }}
        />
        <Group>
          <Button
            variant="light"
            color="orange"
            leftSection={testing ? <Loader size="xs" /> : <IconWifi size={16} />}
            onClick={testCanvas}
            disabled={testing || !canvasUrl}
          >
            Test & Save
          </Button>
        </Group>
        {pingResult && (
          <Alert color={pingResult.ok ? 'green' : 'red'} icon={pingResult.ok ? <IconCheck /> : <IconX />}>
            {pingResult.msg}
          </Alert>
        )}
      </Stack>
    </Paper>
  )
}

export default function SettingsPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [loading, setLoading]       = useState(true)
  const [testing, setTesting]       = useState(false)
  const [savingInst, setSavingInst] = useState(false)
  const [activating, setActivating] = useState<string | null>(null)
  const [deleting, setDeleting]     = useState<string | null>(null)
  const [instances, setInstances]   = useState<MoodleInstance[]>([])
  const [pingResult, setPing]       = useState<{
    ok: boolean; msg: string; siteName?: string
  } | null>(null)
  const [llmProvider, setLlmProvider]   = useState<string>('local')
  const [llmApiKey,   setLlmApiKey]     = useState('')
  const [llmKeyMask,  setLlmKeyMask]    = useState('')
  const [savingLlm,   setSavingLlm]     = useState(false)
  const [lastModel,   setLastModel]     = useState('')

  const form = useForm({
    initialValues: { moodle_url: '', moodle_token: '', llm_url: '' },
  })

  const loadAll = async () => {
    const [s, insts] = await Promise.all([
      api.settings.get(),
      api.settings.listInstances().catch(() => [] as MoodleInstance[]),
    ])
    form.setValues({ moodle_url: s.moodle_url, moodle_token: '', llm_url: s.llm_url })
    setLlmKeyMask(s.llm_api_key_masked || '')
    setLastModel(s.last_model || '')
    // Detect provider from saved URL
    const savedUrl = s.llm_url || ''
    const matched = LLM_PROVIDERS.find(p => p.id !== 'local' && p.id !== 'custom' && p.url && savedUrl.startsWith(p.url))
    if (matched) setLlmProvider(matched.id)
    else if (!savedUrl || savedUrl.includes('192.168') || savedUrl.includes('localhost') || savedUrl.includes('127.0')) setLlmProvider('local')
    else setLlmProvider('custom')
    setInstances(insts)
    setLoading(false)
  }

  useEffect(() => { loadAll() }, [])

  // ── Test current form values ────────────────────────────────────────────────
  const testMoodle = async () => {
    setTesting(true)
    setPing(null)
    try {
      await api.settings.save({
        moodle_url:   form.values.moodle_url,
        moodle_token: form.values.moodle_token || undefined,
        llm_url:      form.values.llm_url,
      } as any)
      const res = await api.moodle.ping()
      setPing({
        ok: true,
        msg: `Connected as ${res.fullname} · ${res.moodle_version}`,
        siteName: res.site_name,
      })
    } catch (e: any) {
      setPing({ ok: false, msg: e.message })
    } finally {
      setTesting(false)
    }
  }

  // ── Save as named instance (after successful ping) ──────────────────────────
  const saveAsInstance = async () => {
    if (!pingResult?.siteName) return
    setSavingInst(true)
    try {
      await api.settings.saveInstance({
        name:  pingResult.siteName,
        url:   form.values.moodle_url,
        token: form.values.moodle_token,
      })
      notifications.show({
        title: t('cfg.notif_instance_saved'),
        message: t('cfg.notif_instance_saved_msg', { name: pingResult.siteName }),
        color: 'green',
        icon: <IconCheck />,
      })
      const insts = await api.settings.listInstances()
      setInstances(insts)
    } catch (e: any) {
      notifications.show({ title: 'Error', message: e.message, color: 'red' })
    } finally {
      setSavingInst(false)
    }
  }

  // ── Activate a saved instance ───────────────────────────────────────────────
  const activateInstance = async (name: string) => {
    setActivating(name)
    try {
      await api.settings.activateInstance(name)
      const [s, insts] = await Promise.all([
        api.settings.get(),
        api.settings.listInstances(),
      ])
      form.setValues({ moodle_url: s.moodle_url, moodle_token: '', llm_url: form.values.llm_url })
      setInstances(insts)
      setPing(null)
      notifications.show({ title: t('common.activated'), message: t('cfg.notif_activated_msg', { name }), color: 'blue' })
    } catch (e: any) {
      notifications.show({ title: 'Error', message: e.message, color: 'red' })
    } finally {
      setActivating(null)
    }
  }

  // ── Delete a saved instance ─────────────────────────────────────────────────
  const deleteInstance = async (name: string) => {
    setDeleting(name)
    try {
      await api.settings.deleteInstance(name)
      setInstances(prev => prev.filter(i => i.name !== name))
    } catch (e: any) {
      notifications.show({ title: 'Error', message: e.message, color: 'red' })
    } finally {
      setDeleting(null)
    }
  }

  // ── Save LLM settings ───────────────────────────────────────────────────────
  const saveLlm = async () => {
    setSavingLlm(true)
    try {
      await api.settings.saveLlm(form.values.llm_url, llmApiKey)
      if (llmApiKey) setLlmKeyMask('••••' + llmApiKey.slice(-4))
      setLlmApiKey('')
      notifications.show({ title: t('common.saved'), message: t('cfg.notif_llm_saved'), color: 'green' })
    } catch (e: any) {
      notifications.show({ title: 'Error', message: e.message, color: 'red' })
    } finally {
      setSavingLlm(false)
    }
  }

  const selectProvider = (id: string) => {
    setLlmProvider(id)
    const p = LLM_PROVIDERS.find(p => p.id === id)
    if (p && p.url) form.setFieldValue('llm_url', p.url)
    else if (id === 'local') form.setFieldValue('llm_url', 'http://192.168.86.41:1234/v1')
  }

  if (loading) return <Loader />

  return (
    <Stack w={480} gap="sm" style={{ flexShrink: 0 }}>
        <Title order={3}>{t('cfg.title')}</Title>

        <Alert color="blue" icon={<IconCloud size={16} />}>
          <Group justify="space-between" wrap="nowrap" align="center">
            <div>
              <Text fw={600}>{t('cfg.overview_moved_title')}</Text>
              <Text size="sm" c="dimmed">{t('cfg.overview_moved_desc')}</Text>
            </div>
            <Button size="xs" variant="light" onClick={() => navigate('/admin/overview')}>
              {t('cfg.open_overview')}
            </Button>
          </Group>
        </Alert>

        <Divider label={t('cfg.section_moodle')} labelPosition="left" />

        {/* ── Saved Moodle Instances ─────────────────────────────────────── */}
        <Paper withBorder p="md" radius="md">
          <Group justify="space-between" mb="sm">
            <Title order={5}>{t('cfg.moodle_instances')}</Title>
            {instances.length === 0 && (
              <Text size="xs" c="dimmed">{t('cfg.no_saved')}</Text>
            )}
          </Group>

          {instances.length > 0 && (
            <Stack gap="xs">
              {instances.map(inst => (
                <Paper
                  key={inst.name}
                  withBorder p="sm" radius="sm"
                  style={{
                    background: inst.active ? 'var(--mantine-color-blue-0)' : undefined,
                    borderColor: inst.active ? 'var(--mantine-color-blue-4)' : undefined,
                  }}
                >
                  <Group justify="space-between" wrap="nowrap">
                    <Group gap="sm" wrap="nowrap">
                      <ThemeIcon size="sm" color={inst.active ? 'blue' : 'gray'} variant="light">
                        <IconCloud size={12} />
                      </ThemeIcon>
                      <div>
                        <Group gap={6}>
                          <Text size="sm" fw={600}>{inst.name}</Text>
                          {inst.active && <Badge size="xs" color="blue">{t('cfg.active_badge')}</Badge>}
                        </Group>
                        <Text size="xs" c="dimmed">{inst.url}</Text>
                        <Text size="xs" c="dimmed">{inst.token_masked}</Text>
                      </div>
                    </Group>
                    <Group gap={4} wrap="nowrap">
                      {inst.active && (
                        <Tooltip label={t('cfg.open_overview')}>
                          <ActionIcon
                            size="sm" variant="light" color="blue"
                            onClick={() => navigate('/admin/overview')}
                          >
                            <IconRefresh size={12} />
                          </ActionIcon>
                        </Tooltip>
                      )}
                      {!inst.active && (
                        <Tooltip label={t('cfg.use_connection')}>
                          <ActionIcon
                            size="sm" variant="light" color="blue"
                            loading={activating === inst.name}
                            onClick={() => activateInstance(inst.name)}
                          >
                            <IconPlayerPlay size={12} />
                          </ActionIcon>
                        </Tooltip>
                      )}
                      <Tooltip label={t('cfg.remove')}>
                        <ActionIcon
                          size="sm" variant="subtle" color="red"
                          loading={deleting === inst.name}
                          onClick={() => deleteInstance(inst.name)}
                        >
                          <IconTrash size={12} />
                        </ActionIcon>
                      </Tooltip>
                    </Group>
                  </Group>
                </Paper>
              ))}
            </Stack>
          )}
        </Paper>

        {/* ── Add / Test Connection ──────────────────────────────────────── */}
        <Paper withBorder p="md" radius="md">
          <Title order={5} mb="sm">
            {instances.length === 0 ? t('cfg.moodle_connection') : t('cfg.add_update')}
          </Title>
          <Stack gap="sm">
            <TextInput
              label={t('cfg.moodle_url')}
              placeholder={t('cfg.moodle_url_ph')}
              {...form.getInputProps('moodle_url')}
            />
            <PasswordInput
              label={t('cfg.token_label')}
              description={t('cfg.token_desc')}
              placeholder={t('cfg.token_ph')}
              {...form.getInputProps('moodle_token')}
            />
            <Group>
              <Button
                variant="light"
                leftSection={testing ? <Loader size="xs" /> : <IconWifi size={16} />}
                onClick={testMoodle}
                disabled={testing}
              >
                {t('common.test_conn')}
              </Button>
            </Group>

            {pingResult && (
              <Alert
                color={pingResult.ok ? 'green' : 'red'}
                icon={pingResult.ok ? <IconCheck /> : <IconX />}
              >
                <Group justify="space-between" wrap="nowrap">
                  <div>
                    {pingResult.siteName && (
                      <Text size="sm" fw={600}>{pingResult.siteName}</Text>
                    )}
                    <Text size="sm">{pingResult.msg}</Text>
                  </div>
                  {pingResult.ok && pingResult.siteName && (
                    <Button
                      size="xs" variant="light" color="green"
                      loading={savingInst}
                      leftSection={<IconPlus size={12} />}
                      onClick={saveAsInstance}
                    >
                      {t('cfg.save_connection')}
                    </Button>
                  )}
                </Group>
              </Alert>
            )}
          </Stack>
        </Paper>

        {/* ── Canvas LMS Connection ──────────────────────────────────────── */}
        <Divider label={t('cfg.section_integrations')} labelPosition="left" />
        <CanvasSettingsPanel />

        {/* ── LLM Provider ──────────────────────────────────────────────── */}
        <Divider label={t('cfg.section_ai')} labelPosition="left" />
        <Paper withBorder p="md" radius="md">
          <Title order={5} mb="xs">{t('cfg.llm_provider')}</Title>
          <Text size="xs" c="dimmed" mb="sm">
            {t('cfg.llm_provider_desc')}
          </Text>

          {/* Provider preset buttons */}
          <Group gap="xs" mb="sm" wrap="wrap">
            {LLM_PROVIDERS.map(p => (
              <Button
                key={p.id}
                size="xs"
                variant={llmProvider === p.id ? 'filled' : 'light'}
                color={p.color}
                leftSection={p.icon}
                onClick={() => selectProvider(p.id)}
              >
                {p.label}
              </Button>
            ))}
          </Group>

          <Stack gap="sm">
            <TextInput
              label={t('cfg.api_endpoint')}
              placeholder={t('cfg.api_endpoint')}
              {...form.getInputProps('llm_url')}
            />

            {llmProvider !== 'local' && (
              <PasswordInput
                label={t('cfg.api_key')}
                placeholder={llmKeyMask || 'Enter API key…'}
                description={
                  llmProvider === 'openrouter'
                    ? t('cfg.api_key_openrouter')
                    : llmProvider === 'openai'
                    ? t('cfg.api_key_openai')
                    : llmProvider === 'anthropic'
                    ? t('cfg.api_key_anthropic')
                    : t('cfg.api_key_custom')
                }
                value={llmApiKey}
                onChange={e => setLlmApiKey(e.currentTarget.value)}
                rightSection={
                  llmKeyMask ? (
                    <Tooltip label={t('cfg.key_saved')}>
                      <ThemeIcon size="xs" color="green" variant="subtle">
                        <IconCheck size={10} />
                      </ThemeIcon>
                    </Tooltip>
                  ) : null
                }
              />
            )}

            {/* Suggested models for selected provider */}
            {PROVIDER_MODELS[llmProvider] && (
              <Box>
                <Text size="xs" c="dimmed" mb={4}>{t('cfg.suggested_models')}</Text>
                <Group gap={4} wrap="wrap">
                  {PROVIDER_MODELS[llmProvider].map(m => (
                    <Badge key={m} size="xs" variant="outline" color="gray"
                           style={{ cursor: 'default', fontFamily: 'monospace' }}>
                      {m}
                    </Badge>
                  ))}
                </Group>
              </Box>
            )}

            {llmProvider === 'openrouter' && (
              <Alert color="violet" py="xs" icon={<IconExternalLink size={14} />}>
                <Text size="xs">{t('cfg.openrouter_note')}</Text>
              </Alert>
            )}

            <Group>
              <Button
                variant="light"
                leftSection={savingLlm ? <Loader size="xs" /> : <IconCheck size={16} />}
                onClick={saveLlm}
                disabled={savingLlm}
              >
                {t('cfg.save_llm')}
              </Button>
            </Group>
          </Stack>
        </Paper>

        <Divider label={t('cfg.section_automation')} labelPosition="left" />
        <ScheduledReviewsSection defaultModel={lastModel} />

        <Divider label={t('cfg.section_security')} labelPosition="left" />
        <SecuritySection />
    </Stack>
  )
}


// ── Security Section ──────────────────────────────────────────────────────────

function SecuritySection() {
  const { t } = useTranslation()
  const [enabled, setEnabled]         = useState(false)
  const [loading, setLoading]         = useState(true)
  const [newToken, setNewToken]       = useState<string | null>(null)
  const [busy, setBusy]               = useState(false)
  const [customToken, setCustomToken] = useState('')
  const [showCustom, setShowCustom]   = useState(false)
  const [diagLoading, setDiagLoading] = useState(false)
  const [diagError, setDiagError] = useState('')
  const [caps, setCaps] = useState<MoodleWriteCapabilities | null>(null)
  const [auditLogs, setAuditLogs] = useState<AdminAuditLog[]>([])
  const [auditTotal, setAuditTotal] = useState(0)
  const [auditOffset, setAuditOffset] = useState(0)
  const [auditLimit] = useState(20)
  const [auditQuery, setAuditQuery] = useState('')
  const [auditArea, setAuditArea] = useState('')
  const [auditStatus, setAuditStatus] = useState('')
  const [operatorName, setOperatorName] = useState('')
  const [rolePolicy, setRolePolicy] = useState<AdminPolicy | null>(null)
  const [roleIdsInput, setRoleIdsInput] = useState('')

  useEffect(() => {
    api.auth.status()
      .then(s => setEnabled(s.enabled))
      .catch(() => {})
      .finally(() => setLoading(false))
    api.auth.getOperator()
      .then(r => setOperatorName(r.name || ''))
      .catch(() => {})
  }, [])

  const saveOperator = async () => {
    setBusy(true)
    try {
      const res = await api.auth.setOperator(operatorName)
      setOperatorName(res.name)
      notifications.show({ color: 'green', message: t('cfg.security_operator_saved') })
    } catch (e: unknown) {
      notifications.show({ color: 'red', message: String(e) })
    } finally {
      setBusy(false)
    }
  }

  const saveRolePolicy = async () => {
    setBusy(true)
    try {
      const res = await api.settings.setAdminPolicy(roleIdsInput)
      setRolePolicy(res)
      setRoleIdsInput(res.allowed_role_ids)
      notifications.show({ color: 'green', message: t('cfg.security_roles_saved') })
    } catch (e: unknown) {
      notifications.show({ color: 'red', message: String(e) })
    } finally {
      setBusy(false)
    }
  }

  const exportAuditCsv = async () => {
    try {
      const csv = await api.settings.exportAuditLogs(1000)
      const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      const ts = new Date().toISOString().replace(/[:.]/g, '-')
      link.href = url
      link.download = `admin-audit-${ts}.csv`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(url)
    } catch (e: unknown) {
      notifications.show({ color: 'red', message: String(e) })
    }
  }

  const loadDiagnostics = async () => {
    setDiagLoading(true)
    try {
      const [capRes, logRes, policyRes] = await Promise.all([
        api.moodle.writeCapabilities(),
        api.settings.auditLogs({
          limit: auditLimit,
          offset: auditOffset,
          area: auditArea,
          status: auditStatus,
          q: auditQuery.trim(),
        }),
        api.settings.getAdminPolicy(),
      ])
      setCaps(capRes)
      setAuditLogs(logRes.items)
      setAuditTotal(logRes.total)
      setRolePolicy(policyRes)
      setRoleIdsInput(policyRes.allowed_role_ids)
      setDiagError('')
    } catch (e: unknown) {
      setDiagError(String(e))
      setCaps(null)
      setAuditLogs([])
      setAuditTotal(0)
    } finally {
      setDiagLoading(false)
    }
  }

  useEffect(() => {
    loadDiagnostics()
  }, [auditLimit, auditOffset, auditArea, auditStatus])

  const generate = async () => {
    setBusy(true)
    try {
      const r = await api.auth.generate()
      setNewToken(r.token)
      tokenStore.set(r.token)
      setEnabled(true)
      notifications.show({ color: 'green', message: t('cfg.notif_token_generated') })
    } catch (e: unknown) {
      notifications.show({ color: 'red', message: String(e) })
    } finally {
      setBusy(false)
    }
  }

  const saveCustom = async () => {
    if (!customToken.trim()) return
    setBusy(true)
    try {
      await api.auth.setToken(customToken.trim())
      tokenStore.set(customToken.trim())
      setEnabled(true)
      setShowCustom(false)
      setCustomToken('')
      notifications.show({ color: 'green', message: t('cfg.notif_token_saved') })
    } catch (e: unknown) {
      notifications.show({ color: 'red', message: String(e) })
    } finally {
      setBusy(false)
    }
  }

  const disableAuth = async () => {
    setBusy(true)
    try {
      await api.auth.clear()
      tokenStore.clear()
      setEnabled(false)
      setNewToken(null)
      notifications.show({ color: 'yellow', message: t('cfg.notif_auth_disabled') })
    } catch (e: unknown) {
      notifications.show({ color: 'red', message: String(e) })
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <Loader size="xs" />

  return (
    <Paper withBorder p="md" radius="md">
      <Group mb="sm" gap="xs">
        {enabled ? <IconLock size={16} color="var(--mantine-color-green-6)" /> : <IconLockOpen size={16} color="var(--mantine-color-gray-5)" />}
        <Title order={5}>{t('cfg.security_title')}</Title>
        <Badge color={enabled ? 'green' : 'gray'} variant="light" size="sm">
          {enabled ? t('cfg.auth_enabled') : t('cfg.no_auth')}
        </Badge>
      </Group>

      <Text size="xs" c="dimmed" mb="md">
        {t('cfg.auth_desc')}
      </Text>

      <Stack gap="sm">
        {newToken && (
          <Alert color="green" icon={<IconCheck size={14} />} title={t('cfg.new_token_title')}>
            <Code block style={{ wordBreak: 'break-all', fontSize: 12 }}>{newToken}</Code>
            <CopyButton value={newToken}>
              {({ copied, copy }) => (
                <Button
                  mt="xs" size="xs" leftSection={<IconCopy size={12} />}
                  color={copied ? 'teal' : 'green'} variant="light"
                  onClick={copy}
                >
                  {copied ? t('cfg.copied') : t('cfg.copy_token')}
                </Button>
              )}
            </CopyButton>
          </Alert>
        )}

        <Group>
          <Button
            size="xs" leftSection={busy ? <Loader size="xs" /> : <IconRefresh size={14} />}
            onClick={generate} loading={busy} variant="filled" color="blue"
          >
            {enabled ? t('cfg.rotate_token') : t('cfg.enable_auth')}
          </Button>

          <Button
            size="xs" variant="light" color="gray"
            leftSection={<IconApi size={14} />}
            onClick={() => setShowCustom(v => !v)}
          >
            {t('cfg.set_custom')}
          </Button>

          {enabled && (
            <Button
              size="xs" variant="subtle" color="red"
              leftSection={<IconLockOpen size={14} />}
              onClick={disableAuth} loading={busy}
            >
              {t('cfg.disable_auth')}
            </Button>
          )}
        </Group>

        {showCustom && (
          <Group align="flex-end">
            <PasswordInput
              style={{ flex: 1 }}
              label={t('cfg.custom_token')}
              placeholder={t('cfg.custom_token_ph')}
              value={customToken}
              onChange={e => setCustomToken(e.currentTarget.value)}
            />
            <Button size="sm" onClick={saveCustom} loading={busy} disabled={!customToken.trim()}>
              {t('common.save')}
            </Button>
          </Group>
        )}

        <Group align="flex-end">
          <TextInput
            style={{ flex: 1 }}
            label={t('cfg.security_operator_label')}
            placeholder={t('cfg.security_operator_ph')}
            value={operatorName}
            onChange={e => setOperatorName(e.currentTarget.value)}
          />
          <Button size="sm" onClick={saveOperator} loading={busy}>
            {t('common.save')}
          </Button>
        </Group>

        <Group align="flex-end">
          <TextInput
            style={{ flex: 1 }}
            label={t('cfg.security_roles_label')}
            placeholder={t('cfg.security_roles_ph')}
            description={t('cfg.security_roles_desc')}
            value={roleIdsInput}
            onChange={e => setRoleIdsInput(e.currentTarget.value)}
          />
          <Button size="sm" onClick={saveRolePolicy} loading={busy}>
            {t('common.save')}
          </Button>
        </Group>
        {rolePolicy && (
          <Group gap={6}>
            <Text size="xs" c="dimmed">{t('cfg.security_roles_effective')}</Text>
            {rolePolicy.parsed_role_ids.map(roleId => (
              <Badge key={roleId} size="xs" variant="light" color="gray">{roleId}</Badge>
            ))}
          </Group>
        )}

        <Divider my="xs" />

        <Group justify="space-between" align="center">
          <Title order={6}>{t('cfg.security_diag_title')}</Title>
          <Group gap="xs">
            <Button
              size="xs"
              variant="light"
              leftSection={<IconDownload size={12} />}
              onClick={exportAuditCsv}
            >
              {t('cfg.security_export_csv')}
            </Button>
            <Button
              size="xs"
              variant="light"
              leftSection={diagLoading ? <Loader size="xs" /> : <IconRefresh size={12} />}
              onClick={loadDiagnostics}
              disabled={diagLoading}
            >
              {t('common.refresh')}
            </Button>
          </Group>
        </Group>

        {diagError && (
          <Alert color="yellow">{diagError}</Alert>
        )}

        <Paper withBorder p="sm" radius="sm">
          <Group justify="space-between" mb="xs">
            <Text size="sm" fw={600}>{t('cfg.security_diag_caps')}</Text>
            <Badge size="xs" color={caps?.ok ? 'teal' : 'orange'}>
              {caps?.ok ? t('cfg.security_diag_ready') : t('cfg.security_diag_missing')}
            </Badge>
          </Group>
          {diagLoading && !caps ? (
            <Loader size="xs" />
          ) : !caps ? (
            <Text size="xs" c="dimmed">{t('cfg.security_diag_unavailable')}</Text>
          ) : (
            <Stack gap={6}>
              {caps.checks.map(check => (
                <Group key={check.key} justify="space-between" align="flex-start" wrap="nowrap">
                  <div>
                    <Text size="xs" fw={600}>{check.key}</Text>
                    {!check.ok && (
                      <Text size="xs" c="dimmed">
                        {t('cfg.security_diag_missing_fns')} {check.missing.join(', ')}
                      </Text>
                    )}
                  </div>
                  <Badge size="xs" color={check.ok ? 'teal' : 'orange'}>
                    {check.ok ? t('cfg.security_diag_ok') : t('cfg.security_diag_missing_short')}
                  </Badge>
                </Group>
              ))}
            </Stack>
          )}
        </Paper>

        <Paper withBorder p="sm" radius="sm">
          <Text size="sm" fw={600} mb="xs">{t('cfg.security_diag_audit')}</Text>
          <Group grow mb="xs" align="flex-end">
            <TextInput
              label={t('cfg.security_diag_filter_query')}
              placeholder={t('cfg.security_diag_filter_query_ph')}
              value={auditQuery}
              onChange={e => setAuditQuery(e.currentTarget.value)}
            />
            <Select
              label={t('cfg.security_diag_filter_area')}
              data={[
                { value: '', label: t('cfg.security_diag_filter_all') },
                { value: 'users', label: 'users' },
                { value: 'enrollment', label: 'enrollment' },
              ]}
              value={auditArea}
              onChange={v => { setAuditArea(v ?? ''); setAuditOffset(0) }}
            />
            <Select
              label={t('cfg.security_diag_filter_status')}
              data={[
                { value: '', label: t('cfg.security_diag_filter_all') },
                { value: 'ok', label: 'ok' },
              ]}
              value={auditStatus}
              onChange={v => { setAuditStatus(v ?? ''); setAuditOffset(0) }}
            />
            <Button variant="light" onClick={() => { setAuditOffset(0); loadDiagnostics() }}>
              {t('cfg.security_diag_apply_filters')}
            </Button>
          </Group>
          {diagLoading && auditLogs.length === 0 ? (
            <Loader size="xs" />
          ) : auditLogs.length === 0 ? (
            <Text size="xs" c="dimmed">{t('cfg.security_diag_no_audit')}</Text>
          ) : (
            <>
            <Table withTableBorder striped>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t('cfg.security_diag_col_time')}</Table.Th>
                  <Table.Th>{t('cfg.security_diag_col_actor')}</Table.Th>
                  <Table.Th>{t('cfg.security_diag_col_action')}</Table.Th>
                  <Table.Th>{t('cfg.security_diag_col_target')}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {auditLogs.map(row => (
                  <Table.Tr key={row.id}>
                    <Table.Td>
                      <Text size="xs">{new Date(`${row.created_at}Z`).toLocaleString()}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs" c="dimmed">{row.actor || '—'}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs" fw={600}>{row.area}.{row.action}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs" c="dimmed">{row.target_type}:{row.target_id}</Text>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
            <Group justify="space-between" mt="xs">
              <Text size="xs" c="dimmed">
                {t('cfg.security_diag_page_info', {
                  from: auditTotal === 0 ? 0 : auditOffset + 1,
                  to: Math.min(auditOffset + auditLogs.length, auditTotal),
                  total: auditTotal,
                })}
              </Text>
              <Group gap="xs">
                <Button
                  size="xs"
                  variant="light"
                  disabled={auditOffset <= 0}
                  onClick={() => setAuditOffset(v => Math.max(0, v - auditLimit))}
                >
                  {t('cfg.security_diag_prev')}
                </Button>
                <Button
                  size="xs"
                  variant="light"
                  disabled={auditOffset + auditLimit >= auditTotal}
                  onClick={() => setAuditOffset(v => v + auditLimit)}
                >
                  {t('cfg.security_diag_next')}
                </Button>
              </Group>
            </Group>
            </>
          )}
        </Paper>
      </Stack>
    </Paper>
  )
}
