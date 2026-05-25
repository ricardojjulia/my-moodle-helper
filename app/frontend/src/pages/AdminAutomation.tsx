import { useEffect, useState } from 'react'
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Collapse,
  Group,
  Loader,
  Paper,
  Select,
  Stack,
  Text,
  TextInput,
  ThemeIcon,
  Title,
  Tooltip,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconCalendarEvent, IconCheck, IconClock, IconPlayerPlay, IconPlus, IconTrash } from '@tabler/icons-react'
import { useTranslation } from 'react-i18next'
import { api, type ReviewSchedule } from '../api/client'

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

export default function AdminAutomationPage() {
  const { t } = useTranslation()
  const [schedules, setSchedules] = useState<ReviewSchedule[]>([])
  const [courses, setCourses] = useState<{ value: string; label: string }[]>([])
  const [loading, setLoading] = useState(false)
  const [running, setRunning] = useState(false)
  const [showForm, setShowForm] = useState(false)
  const [deleting, setDeleting] = useState<number | null>(null)
  const [newShort, setNewShort] = useState<string | null>(null)
  const [newAgent, setNewAgent] = useState<string>(SCHED_AGENTS[0].id)
  const [newFreq, setNewFreq] = useState<string>('weekly')
  const [newModel, setNewModel] = useState('')
  const [saving, setSaving] = useState(false)

  const load = () => {
    setLoading(true)
    Promise.all([api.schedules.list(), api.courses.list()])
      .then(([scheds, libCourses]) => {
        setSchedules(scheds)
        setCourses(libCourses.map(course => ({ value: course.shortname, label: `${course.shortname} — ${course.fullname}` })))
      })
      .catch((e: Error) => notifications.show({ title: 'Error', message: e.message, color: 'red' }))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const overdueCount = schedules.filter(schedule => schedule.enabled && new Date(`${schedule.next_run_at}Z`) <= new Date()).length

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
    } catch (e) {
      notifications.show({ title: 'Error', message: e instanceof Error ? e.message : String(e), color: 'red' })
    } finally {
      setRunning(false)
    }
  }

  const createSchedule = async () => {
    if (!newShort) return
    const agent = SCHED_AGENTS.find(item => item.id === newAgent)
    if (!agent) return

    setSaving(true)
    try {
      await api.schedules.create({
        shortname: newShort,
        agent_id: agent.id,
        agent_label: agent.label,
        agent_color: agent.color,
        agent_context: agent.context,
        model_id: newModel,
        frequency: newFreq,
      })
      notifications.show({
        title: t('cfg.notif_sched_created'),
        message: t('cfg.notif_sched_created_msg', { shortname: newShort, freq: newFreq }),
        color: 'green',
      })
      setShowForm(false)
      setNewShort(null)
      load()
    } catch (e) {
      notifications.show({ title: 'Error', message: e instanceof Error ? e.message : String(e), color: 'red' })
    } finally {
      setSaving(false)
    }
  }

  const removeSchedule = async (id: number) => {
    setDeleting(id)
    try {
      await api.schedules.delete(id)
      setSchedules(prev => prev.filter(schedule => schedule.id !== id))
    } catch (e) {
      notifications.show({ title: 'Error', message: e instanceof Error ? e.message : String(e), color: 'red' })
    } finally {
      setDeleting(null)
    }
  }

  const fmtDate = (iso: string | null) => {
    if (!iso) return '—'
    return new Date(`${iso}Z`).toLocaleDateString(undefined, {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    })
  }

  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-start">
        <div>
          <Title order={2}>{t('app.automation_title')}</Title>
          <Text c="dimmed" mt={6}>{t('app.automation_subtitle')}</Text>
        </div>
        <Group gap="xs">
          {overdueCount > 0 && (
            <Button
              color="orange"
              variant="light"
              leftSection={running ? <Loader size="xs" /> : <IconPlayerPlay size={14} />}
              onClick={runOverdue}
              disabled={running}
            >
              {t('cfg.sched_run_overdue', { count: overdueCount })}
            </Button>
          )}
          <Button variant="light" leftSection={<IconPlus size={14} />} onClick={() => setShowForm(value => !value)}>
            {showForm ? t('cfg.sched_cancel') : t('cfg.sched_add')}
          </Button>
        </Group>
      </Group>

      <Paper withBorder p="md" radius="md">
        <Group gap="sm" mb="sm">
          <ThemeIcon size="sm" color="violet" variant="light">
            <IconCalendarEvent size={12} />
          </ThemeIcon>
          <Title order={4}>{t('cfg.sched_title')}</Title>
          {overdueCount > 0 && <Badge size="xs" color="orange">{t('cfg.sched_overdue', { count: overdueCount })}</Badge>}
        </Group>

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
                  data={SCHED_AGENTS.map(agent => ({ value: agent.id, label: agent.label }))}
                  value={newAgent}
                  onChange={value => setNewAgent(value ?? SCHED_AGENTS[0].id)}
                  size="xs"
                />
              </Group>
              <Group grow gap="sm">
                <Select
                  label={t('cfg.sched_freq')}
                  data={[
                    { value: 'daily', label: t('cfg.sched_daily') },
                    { value: 'weekly', label: t('cfg.sched_weekly') },
                    { value: 'monthly', label: t('cfg.sched_monthly') },
                  ]}
                  value={newFreq}
                  onChange={value => setNewFreq(value ?? 'weekly')}
                  size="xs"
                />
                <TextInput
                  label={t('cfg.sched_model_id')}
                  placeholder={t('cfg.sched_model_ph')}
                  value={newModel}
                  onChange={event => setNewModel(event.currentTarget.value)}
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

        {loading && <Loader size="sm" />}
        {!loading && schedules.length === 0 && (
          <Text size="xs" c="dimmed" ta="center" py="md">
            {t('cfg.sched_empty')}
          </Text>
        )}
        {schedules.map(schedule => {
          const isOverdue = schedule.enabled === 1 && new Date(`${schedule.next_run_at}Z`) <= new Date()
          return (
            <Paper
              key={schedule.id}
              withBorder
              p="sm"
              radius="sm"
              mb="xs"
              style={{ borderColor: isOverdue ? 'var(--mantine-color-orange-4)' : undefined }}
            >
              <Group justify="space-between" wrap="nowrap">
                <Box>
                  <Group gap={6} mb={2}>
                    <Text size="sm" fw={600}>{schedule.shortname}</Text>
                    <Badge size="xs" color={SCHED_AGENTS.find(agent => agent.id === schedule.agent_id)?.color || 'gray'}>
                      {schedule.agent_label}
                    </Badge>
                    <Badge size="xs" variant="outline">{schedule.frequency}</Badge>
                    {isOverdue && <Badge size="xs" color="orange">{t('cfg.sched_overdue_badge')}</Badge>}
                  </Group>
                  <Group gap={8}>
                    <Group gap={4}>
                      <IconClock size={11} />
                      <Text size="xs" c="dimmed">{t('cfg.sched_next')} {fmtDate(schedule.next_run_at)}</Text>
                    </Group>
                    {schedule.last_run_at && (
                      <Text size="xs" c="dimmed">{t('cfg.sched_last')} {fmtDate(schedule.last_run_at)}</Text>
                    )}
                  </Group>
                </Box>
                <Tooltip label={t('cfg.sched_delete')} withArrow>
                  <ActionIcon
                    size="sm"
                    color="red"
                    variant="subtle"
                    loading={deleting === schedule.id}
                    onClick={() => removeSchedule(schedule.id)}
                  >
                    <IconTrash size={13} />
                  </ActionIcon>
                </Tooltip>
              </Group>
            </Paper>
          )
        })}
      </Paper>
    </Stack>
  )
}