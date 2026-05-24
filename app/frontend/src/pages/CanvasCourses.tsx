import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Stack, Title, Text, Badge, Group, Button, Paper,
  Loader, Alert, Table, Collapse, Box, ThemeIcon,
  SimpleGrid, ScrollArea,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import {
  IconRefresh, IconCloud, IconCheck, IconX,
  IconChevronDown, IconChevronRight,
  IconBook2, IconUsers, IconClock, IconEye, IconEyeOff,
} from '@tabler/icons-react'
import {
  api, type CanvasCourse, type MoodleSection, type CanvasStats,
} from '../api/client'

// ── helpers ───────────────────────────────────────────────────────────────────

const ts2date = (ts: number) => ts ? new Date(ts * 1000).toISOString().slice(0, 10) : '—'

function StatCard({ icon, label, value, color }: {
  icon: React.ReactNode; label: string; value: React.ReactNode; color: string
}) {
  return (
    <Paper withBorder p="md" radius="md">
      <Group gap="sm" wrap="nowrap" align="flex-start">
        <ThemeIcon size="lg" variant="light" color={color} style={{ flexShrink: 0 }}>
          {icon}
        </ThemeIcon>
        <Box>
          <Text size="xs" c="dimmed" fw={500} tt="uppercase" lts={0.5}>{label}</Text>
          <Text fw={700} size="xl" lh={1.2}>{value}</Text>
        </Box>
      </Group>
    </Paper>
  )
}

// ── Module / section row ──────────────────────────────────────────────────────

function ModuleRow({ section }: { section: MoodleSection }) {
  const [open, setOpen] = useState(false)
  const itemCount = section.activities.length

  return (
    <>
      <Table.Tr
        style={{ cursor: 'pointer' }}
        onClick={() => setOpen(v => !v)}
      >
        <Table.Td>
          <Group gap="xs" wrap="nowrap">
            {open
              ? <IconChevronDown size={14} style={{ flexShrink: 0 }} />
              : <IconChevronRight size={14} style={{ flexShrink: 0 }} />}
            <Text size="sm" fw={600}>{section.name}</Text>
          </Group>
        </Table.Td>
        <Table.Td>
          <Badge size="xs" variant="light" color="blue">{itemCount} items</Badge>
        </Table.Td>
      </Table.Tr>

      {open && itemCount > 0 && (
        <Table.Tr>
          <Table.Td colSpan={2} pl="xl">
            <Table withColumnBorders={false} striped="odd" highlightOnHover={false}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Title</Table.Th>
                  <Table.Th>Type</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {section.activities.map(a => (
                  <Table.Tr key={a.id}>
                    <Table.Td>
                      {a.url
                        ? <Text size="sm" component="a" href={a.url} target="_blank" rel="noopener noreferrer" c="blue">{a.name}</Text>
                        : <Text size="sm">{a.name}</Text>}
                    </Table.Td>
                    <Table.Td>
                      <Badge size="xs" variant="light" color="gray">{a.modname}</Badge>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.Td>
        </Table.Tr>
      )}
    </>
  )
}

// ── Course row ────────────────────────────────────────────────────────────────

function CourseRow({ course }: { course: CanvasCourse }) {
  const [open, setOpen]             = useState(false)
  const [sections, setSections]     = useState<MoodleSection[] | null>(null)
  const [loadingSec, setLoadingSec] = useState(false)

  const toggle = async () => {
    if (!open && sections === null) {
      setLoadingSec(true)
      try {
        const data = await api.canvas.contents(course.id)
        setSections(data)
      } catch (e: any) {
        notifications.show({ title: 'Error', message: e.message, color: 'red' })
      } finally {
        setLoadingSec(false)
      }
    }
    setOpen(v => !v)
  }

  const published = course.workflow_state !== 'unpublished'

  return (
    <>
      <Table.Tr style={{ cursor: 'pointer' }} onClick={toggle}>
        <Table.Td>
          <Group gap="xs" wrap="nowrap">
            {open
              ? <IconChevronDown size={14} style={{ flexShrink: 0 }} />
              : <IconChevronRight size={14} style={{ flexShrink: 0 }} />}
            <Box>
              <Text size="sm" fw={600}>{course.fullname}</Text>
              <Text size="xs" c="dimmed">{course.shortname}</Text>
            </Box>
          </Group>
        </Table.Td>
        <Table.Td>
          <Badge size="xs" color={published ? 'green' : 'orange'} variant="light"
            leftSection={published ? <IconEye size={10} /> : <IconEyeOff size={10} />}>
            {published ? 'Published' : 'Unpublished'}
          </Badge>
        </Table.Td>
        <Table.Td>
          <Text size="xs">{course.total_students ?? '—'}</Text>
        </Table.Td>
        <Table.Td>
          <Text size="xs">{ts2date(course.startdate)}</Text>
        </Table.Td>
        <Table.Td>
          <Text size="xs">{ts2date(course.enddate)}</Text>
        </Table.Td>
      </Table.Tr>

      {open && (
        <Table.Tr>
          <Table.Td colSpan={5} pl="xl" pb="md">
            {loadingSec && <Loader size="sm" />}
            {sections && sections.length === 0 && (
              <Text size="sm" c="dimmed">No modules found for this course.</Text>
            )}
            {sections && sections.length > 0 && (
              <Table withTableBorder={false} striped="odd">
                <Table.Tbody>
                  {sections.map(sec => <ModuleRow key={sec.id} section={sec} />)}
                </Table.Tbody>
              </Table>
            )}
          </Table.Td>
        </Table.Tr>
      )}
    </>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function CanvasCoursesPage() {
  const { t } = useTranslation()
  const [courses, setCourses]   = useState<CanvasCourse[] | null>(null)
  const [stats, setStats]       = useState<CanvasStats | null>(null)
  const [status, setStatus]     = useState<'idle' | 'loading' | 'ok' | 'error'>('idle')
  const [error, setError]       = useState('')
  const [pingInfo, setPingInfo] = useState<string>('')

  const load = async () => {
    setStatus('loading')
    setError('')
    try {
      const [ping, courseList, siteStats] = await Promise.all([
        api.canvas.ping().catch(() => null),
        api.canvas.courses(),
        api.canvas.stats().catch(() => null),
      ])
      if (ping) setPingInfo(`${ping.fullname} (${ping.username})`)
      setCourses(courseList)
      if (siteStats) setStats(siteStats)
      setStatus('ok')
    } catch (e: any) {
      setError(e.message)
      setStatus('error')
    }
  }

  useEffect(() => { load() }, [])

  return (
    <Stack p="md" gap="md">
      {/* Header */}
      <Group justify="space-between">
        <Group gap="xs">
          <ThemeIcon size="md" variant="light" color="orange">
            <IconCloud size={16} />
          </ThemeIcon>
          <Title order={3}>Canvas LMS</Title>
          {status === 'ok' && (
            <Badge color="green" leftSection={<IconCheck size={10} />} size="sm">Connected</Badge>
          )}
          {status === 'error' && (
            <Badge color="red" leftSection={<IconX size={10} />} size="sm">Error</Badge>
          )}
        </Group>
        <Button
          size="xs"
          variant="subtle"
          leftSection={status === 'loading' ? <Loader size={12} /> : <IconRefresh size={14} />}
          onClick={load}
          disabled={status === 'loading'}
        >
          Refresh
        </Button>
      </Group>

      {pingInfo && (
        <Text size="xs" c="dimmed">Connected as: <strong>{pingInfo}</strong></Text>
      )}

      {/* Stats */}
      {stats && (
        <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="sm">
          <StatCard icon={<IconBook2 size={16} />} label="Total courses" value={stats.total_courses ?? '—'} color="blue" />
          <StatCard icon={<IconEye size={16} />} label="Published" value={stats.visible_courses ?? '—'} color="green" />
          <StatCard icon={<IconEyeOff size={16} />} label="Unpublished" value={stats.hidden_courses ?? '—'} color="orange" />
          <StatCard icon={<IconUsers size={16} />} label="Site" value={stats.site_name ?? '—'} color="violet" />
        </SimpleGrid>
      )}

      {status === 'error' && (
        <Alert color="red" icon={<IconX size={16} />} title="Canvas connection failed">
          {error}
          <br />
          <Text size="xs" mt={4}>Make sure Canvas URL and token are configured in Settings.</Text>
        </Alert>
      )}

      {status === 'loading' && <Loader />}

      {/* Courses table */}
      {courses && courses.length === 0 && status === 'ok' && (
        <Text c="dimmed">No courses found for this Canvas account.</Text>
      )}

      {courses && courses.length > 0 && (
        <Paper withBorder radius="md">
          <ScrollArea>
            <Table highlightOnHover striped="odd">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Course</Table.Th>
                  <Table.Th>Status</Table.Th>
                  <Table.Th><Group gap={4}><IconUsers size={12} />Students</Group></Table.Th>
                  <Table.Th><Group gap={4}><IconClock size={12} />Start</Group></Table.Th>
                  <Table.Th><Group gap={4}><IconClock size={12} />End</Group></Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {courses.map(c => <CourseRow key={c.id} course={c} />)}
              </Table.Tbody>
            </Table>
          </ScrollArea>
        </Paper>
      )}
    </Stack>
  )
}
