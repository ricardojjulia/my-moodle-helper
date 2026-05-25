import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Paper,
  ScrollArea,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
  ThemeIcon,
  Title,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import {
  IconAlertTriangle,
  IconBook2,
  IconRefresh,
  IconSearch,
  IconShieldCheck,
  IconUserCheck,
  IconUserOff,
  IconUsers,
} from '@tabler/icons-react'
import { useTranslation } from 'react-i18next'
import { api, type MoodleCourse, type MoodleEnrollmentUser, type MoodleUser } from '../api/client'

function MetricCard({
  title,
  value,
  description,
  color,
  icon,
}: {
  title: string
  value: string | number
  description: string
  color: string
  icon: React.ReactNode
}) {
  return (
    <Paper withBorder p="md" radius="md">
      <Group justify="space-between" align="flex-start" mb="sm">
        <div>
          <Text size="xs" fw={700} c="dimmed" tt="uppercase">{title}</Text>
          <Text size="xl" fw={700} c={color} mt={6}>{value}</Text>
        </div>
        <ThemeIcon size="lg" radius="md" color={color} variant="light">{icon}</ThemeIcon>
      </Group>
      <Text size="sm" c="dimmed">{description}</Text>
    </Paper>
  )
}

function formatLastAccess(value: number, t: (key: string, options?: Record<string, unknown>) => string) {
  if (!value) return t('app.enrollment_never_accessed')

  const date = new Date(value * 1000)
  const diffMs = Date.now() - date.getTime()
  if (!Number.isFinite(diffMs) || diffMs < 0) return date.toLocaleString()

  const mins = Math.floor(diffMs / 60000)
  if (mins < 1) return t('common.just_now')
  if (mins < 60) return t('common.ago_mins', { count: mins })

  const hours = Math.floor(mins / 60)
  if (hours < 24) return t('common.ago_hours', { count: hours })

  return t('common.ago_days', { count: Math.floor(hours / 24) })
}

export default function AdminEnrollmentPage() {
  const { t } = useTranslation()
  const [courses, setCourses] = useState<MoodleCourse[]>([])
  const [selectedCourseId, setSelectedCourseId] = useState<string | null>(null)
  const [roster, setRoster] = useState<MoodleEnrollmentUser[]>([])
  const [allUsers, setAllUsers] = useState<MoodleUser[]>([])
  const [loadingCourses, setLoadingCourses] = useState(true)
  const [loadingRoster, setLoadingRoster] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [actionLoading, setActionLoading] = useState(false)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [roleFilter, setRoleFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [enrollUserId, setEnrollUserId] = useState<string | null>(null)
  const [memberUserId, setMemberUserId] = useState<string | null>(null)
  const [roleId, setRoleId] = useState<string>('5')

  const loadCourses = async () => {
    setLoadingCourses(true)
    try {
      const [list, users] = await Promise.all([
        api.moodle.courses(),
        api.moodle.users(),
      ])
      setCourses(list)
      setAllUsers(users)
      if (!selectedCourseId && list.length > 0) setSelectedCourseId(String(list[0].id))
      setError('')
    } catch (e) {
      setCourses([])
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoadingCourses(false)
    }
  }

  const loadRoster = async (courseId: number, background = false) => {
    if (background) setRefreshing(true)
    else setLoadingRoster(true)

    try {
      const res = await api.moodle.enrollment(courseId)
      setRoster(res.users)
      setError('')
    } catch (e) {
      setRoster([])
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoadingRoster(false)
      setRefreshing(false)
    }
  }

  useEffect(() => {
    loadCourses()
  }, [])

  useEffect(() => {
    if (!selectedCourseId) return
    loadRoster(Number(selectedCourseId))
  }, [selectedCourseId])

  const courseOptions = useMemo(
    () => courses.map(course => ({ value: String(course.id), label: `${course.shortname} - ${course.fullname}` })),
    [courses],
  )

  const roleOptions = useMemo(() => {
    const roleMap = new Map<number, string>()
    roster.forEach(user => {
      user.role_details?.forEach(role => {
        roleMap.set(role.id, role.shortname || role.name || String(role.id))
      })
    })
    if (!roleMap.has(5)) roleMap.set(5, 'student')
    return [
      { value: 'all', label: t('app.enrollment_filter_role_all') },
      ...Array.from(roleMap.entries())
        .sort((left, right) => left[1].localeCompare(right[1]))
        .map(([id, name]) => ({ value: String(id), label: `${name} (${id})` })),
    ]
  }, [roster, t])

  const query = search.trim().toLowerCase()
  const filtered = roster.filter(user => {
    const matchesSearch = query.length === 0 || [user.fullname, user.username, user.email].join(' ').toLowerCase().includes(query)
    const matchesRole = roleFilter === 'all' || user.role_details?.some(role => String(role.id) === roleFilter)
    const matchesStatus = statusFilter === 'all'
      || (statusFilter === 'active' && !user.suspended)
      || (statusFilter === 'suspended' && user.suspended)
      || (statusFilter === 'never' && user.lastaccess === 0)

    return matchesSearch && matchesRole && matchesStatus
  })

  const activeCount = roster.filter(user => !user.suspended).length
  const suspendedCount = roster.filter(user => user.suspended).length
  const neverAccessed = roster.filter(user => user.lastaccess === 0).length

  const roleDistribution = useMemo(() => {
    const map: Record<string, number> = {}
    roster.forEach(user => {
      if (user.roles.length === 0) {
        map.none = (map.none || 0) + 1
        return
      }
      user.roles.forEach(role => {
        map[role] = (map[role] || 0) + 1
      })
    })
    return Object.entries(map).sort((a, b) => b[1] - a[1]).slice(0, 4)
  }, [roster])

  const enrollableOptions = useMemo(() => {
    const enrolledIds = new Set(roster.map(user => user.id))
    return allUsers
      .filter(user => !enrolledIds.has(user.id))
      .map(user => ({ value: String(user.id), label: `${user.fullname || user.username} (@${user.username})` }))
  }, [allUsers, roster])

  const memberOptions = useMemo(
    () => roster.map(user => ({ value: String(user.id), label: `${user.fullname || user.username} (@${user.username})` })),
    [roster],
  )

  const actionRoleOptions = roleOptions.filter(option => option.value !== 'all')

  const runAction = async (fn: () => Promise<unknown>, successMessage: string) => {
    if (!selectedCourseId) return
    setActionLoading(true)
    try {
      await fn()
      await loadRoster(Number(selectedCourseId), true)
      notifications.show({ title: t('common.saved'), message: successMessage, color: 'green' })
    } catch (e) {
      notifications.show({ title: t('common.error'), message: e instanceof Error ? e.message : String(e), color: 'red' })
    } finally {
      setActionLoading(false)
    }
  }

  const handleEnroll = async () => {
    if (!selectedCourseId || !enrollUserId || !roleId) return
    await runAction(
      () => api.moodle.enrollUser(Number(selectedCourseId), { user_id: Number(enrollUserId), role_id: Number(roleId) }),
      t('app.enrollment_action_enrolled'),
    )
    setEnrollUserId(null)
  }

  const handleUnenroll = async () => {
    if (!selectedCourseId || !memberUserId) return
    await runAction(
      () => api.moodle.unenrollUser(Number(selectedCourseId), Number(memberUserId)),
      t('app.enrollment_action_unenrolled'),
    )
  }

  const handleAssignRole = async () => {
    if (!selectedCourseId || !memberUserId || !roleId) return
    await runAction(
      () => api.moodle.assignRole(Number(selectedCourseId), { user_id: Number(memberUserId), role_id: Number(roleId) }),
      t('app.enrollment_action_role_assigned'),
    )
  }

  const handleUnassignRole = async () => {
    if (!selectedCourseId || !memberUserId || !roleId) return
    await runAction(
      () => api.moodle.unassignRole(Number(selectedCourseId), { user_id: Number(memberUserId), role_id: Number(roleId) }),
      t('app.enrollment_action_role_unassigned'),
    )
  }

  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-start">
        <div>
          <Title order={2}>{t('app.enrollment_title')}</Title>
          <Text c="dimmed" mt={6}>{t('app.enrollment_subtitle')}</Text>
        </div>
        <Button
          variant="light"
          leftSection={refreshing ? <Loader size={14} /> : <IconRefresh size={14} />}
          disabled={!selectedCourseId || refreshing || loadingRoster}
          onClick={() => selectedCourseId && loadRoster(Number(selectedCourseId), true)}
        >
          {t('common.refresh')}
        </Button>
      </Group>

      <Alert color="yellow" icon={<IconShieldCheck size={16} />}>
        {t('app.enrollment_write_notice')}
      </Alert>

      {error && (
        <Alert color="yellow" icon={<IconAlertTriangle size={16} />}>
          {error}
        </Alert>
      )}

      <Paper withBorder p="md" radius="md">
        <Group align="flex-end" grow>
          <Select
            label={t('app.enrollment_course_label')}
            placeholder={t('app.enrollment_course_placeholder')}
            data={courseOptions}
            value={selectedCourseId}
            onChange={setSelectedCourseId}
            searchable
            disabled={loadingCourses}
          />
        </Group>
      </Paper>

      <Paper withBorder p="md" radius="md">
        <Title order={4} mb="sm">{t('app.enrollment_actions_title')}</Title>
        <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
          <Stack gap="xs">
            <Text size="sm" fw={600}>{t('app.enrollment_actions_enroll')}</Text>
            <Select
              label={t('app.enrollment_actions_user')}
              data={enrollableOptions}
              value={enrollUserId}
              onChange={setEnrollUserId}
              searchable
              placeholder={t('app.enrollment_actions_user_enroll_ph')}
            />
            <Select
              label={t('app.enrollment_actions_role')}
              data={actionRoleOptions}
              value={roleId}
              onChange={value => setRoleId(value ?? '5')}
            />
            <Button
              variant="light"
              onClick={handleEnroll}
              disabled={!selectedCourseId || !enrollUserId || !roleId || actionLoading}
            >
              {t('app.enrollment_actions_enroll_btn')}
            </Button>
          </Stack>

          <Stack gap="xs">
            <Text size="sm" fw={600}>{t('app.enrollment_actions_member')}</Text>
            <Select
              label={t('app.enrollment_actions_user')}
              data={memberOptions}
              value={memberUserId}
              onChange={setMemberUserId}
              searchable
              placeholder={t('app.enrollment_actions_user_member_ph')}
            />
            <Select
              label={t('app.enrollment_actions_role')}
              data={actionRoleOptions}
              value={roleId}
              onChange={value => setRoleId(value ?? '5')}
            />
            <Group>
              <Button
                variant="light"
                onClick={handleAssignRole}
                disabled={!selectedCourseId || !memberUserId || !roleId || actionLoading}
              >
                {t('app.enrollment_actions_assign_btn')}
              </Button>
              <Button
                variant="light"
                color="orange"
                onClick={handleUnassignRole}
                disabled={!selectedCourseId || !memberUserId || !roleId || actionLoading}
              >
                {t('app.enrollment_actions_unassign_btn')}
              </Button>
              <Button
                color="red"
                variant="light"
                onClick={handleUnenroll}
                disabled={!selectedCourseId || !memberUserId || actionLoading}
              >
                {t('app.enrollment_actions_unenroll_btn')}
              </Button>
            </Group>
          </Stack>
        </SimpleGrid>
      </Paper>

      <SimpleGrid cols={{ base: 1, md: 4 }} spacing="md">
        <MetricCard
          title={t('app.enrollment_card_total')}
          value={roster.length}
          description={t('app.enrollment_card_total_desc')}
          color="blue"
          icon={<IconUsers size={18} />}
        />
        <MetricCard
          title={t('app.enrollment_card_active')}
          value={activeCount}
          description={t('app.enrollment_card_active_desc')}
          color="teal"
          icon={<IconUserCheck size={18} />}
        />
        <MetricCard
          title={t('app.enrollment_card_suspended')}
          value={suspendedCount}
          description={t('app.enrollment_card_suspended_desc')}
          color={suspendedCount > 0 ? 'orange' : 'gray'}
          icon={<IconUserOff size={18} />}
        />
        <MetricCard
          title={t('app.enrollment_card_never')}
          value={neverAccessed}
          description={t('app.enrollment_card_never_desc')}
          color={neverAccessed > 0 ? 'yellow' : 'gray'}
          icon={<IconBook2 size={18} />}
        />
      </SimpleGrid>

      <Paper withBorder p="md" radius="md">
        <Group justify="space-between" align="flex-end" mb="sm">
          <div>
            <Title order={4}>{t('app.enrollment_roster_title')}</Title>
            <Text size="sm" c="dimmed">{t('app.enrollment_roster_count', { shown: filtered.length, total: roster.length })}</Text>
          </div>
          <Group gap={6}>
            {roleDistribution.map(([role, count]) => (
              <Badge key={role} variant="light" color="gray">{role}: {count}</Badge>
            ))}
          </Group>
        </Group>

        <Group grow align="flex-end" mb="md">
          <TextInput
            label={t('app.enrollment_search_label')}
            placeholder={t('app.enrollment_search_placeholder')}
            value={search}
            onChange={event => setSearch(event.currentTarget.value)}
            leftSection={<IconSearch size={14} />}
          />
          <Select
            label={t('app.enrollment_filter_role')}
            data={roleOptions}
            value={roleFilter}
            onChange={value => setRoleFilter(value ?? 'all')}
          />
          <Select
            label={t('app.enrollment_filter_status')}
            data={[
              { value: 'all', label: t('app.enrollment_filter_status_all') },
              { value: 'active', label: t('app.enrollment_status_active') },
              { value: 'suspended', label: t('app.enrollment_status_suspended') },
              { value: 'never', label: t('app.enrollment_status_never') },
            ]}
            value={statusFilter}
            onChange={value => setStatusFilter(value ?? 'all')}
          />
        </Group>

        {loadingCourses || loadingRoster ? (
          <Group gap="sm"><Loader size="sm" /><Text size="sm">{t('app.enrollment_loading')}</Text></Group>
        ) : !selectedCourseId ? (
          <Text size="sm" c="dimmed">{t('app.enrollment_select_course')}</Text>
        ) : filtered.length === 0 ? (
          <Text size="sm" c="dimmed">{t('app.enrollment_empty')}</Text>
        ) : (
          <ScrollArea>
            <Table striped highlightOnHover withTableBorder>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t('app.enrollment_col_user')}</Table.Th>
                  <Table.Th>{t('app.enrollment_col_roles')}</Table.Th>
                  <Table.Th>{t('app.enrollment_col_status')}</Table.Th>
                  <Table.Th>{t('app.enrollment_col_last_access')}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {filtered.map(user => (
                  <Table.Tr key={user.id}>
                    <Table.Td>
                      <Stack gap={2}>
                        <Text fw={600} size="sm">{user.fullname || user.username}</Text>
                        <Text size="xs" c="dimmed">@{user.username}</Text>
                        <Text size="xs" c="dimmed">{user.email || '—'}</Text>
                      </Stack>
                    </Table.Td>
                    <Table.Td>
                      <Group gap={6}>
                        {user.roles.length > 0
                          ? user.roles.map(role => <Badge key={role} variant="outline">{role}</Badge>)
                          : <Badge color="gray" variant="light">none</Badge>}
                      </Group>
                    </Table.Td>
                    <Table.Td>
                      <Group gap={6}>
                        {user.suspended
                          ? <Badge color="orange">{t('app.enrollment_status_suspended')}</Badge>
                          : <Badge color="teal">{t('app.enrollment_status_active')}</Badge>}
                        {user.lastaccess === 0 && <Badge color="yellow" variant="outline">{t('app.enrollment_status_never')}</Badge>}
                      </Group>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{formatLastAccess(user.lastaccess, t)}</Text>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </ScrollArea>
        )}
      </Paper>
    </Stack>
  )
}
