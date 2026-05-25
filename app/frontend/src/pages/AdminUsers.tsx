import { useEffect, useState } from 'react'
import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  PasswordInput,
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
import { IconAlertTriangle, IconMail, IconRefresh, IconSearch, IconShieldCheck, IconUserCheck, IconUserOff, IconUsers } from '@tabler/icons-react'
import { useTranslation } from 'react-i18next'
import { api, type MoodleUser } from '../api/client'

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
  if (!value) return t('app.users_never_accessed')

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

export default function AdminUsersPage() {
  const { t } = useTranslation()
  const [users, setUsers] = useState<MoodleUser[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [actionLoading, setActionLoading] = useState(false)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [authFilter, setAuthFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [actionUserId, setActionUserId] = useState<string | null>(null)
  const [deleteConfirm, setDeleteConfirm] = useState('')
  const [newUsername, setNewUsername] = useState('')
  const [newFirstName, setNewFirstName] = useState('')
  const [newLastName, setNewLastName] = useState('')
  const [newEmail, setNewEmail] = useState('')
  const [newPassword, setNewPassword] = useState('')

  const loadUsers = async (background = false) => {
    if (background) setRefreshing(true)
    else setLoading(true)

    try {
      const data = await api.moodle.users()
      setUsers(data)
      setError('')
    } catch (e) {
      setUsers([])
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => {
    loadUsers()
  }, [])

  const query = search.trim().toLowerCase()
  const authOptions = [
    { value: 'all', label: t('app.users_filter_auth_all') },
    ...Array.from(new Set(users.map(user => user.auth).filter(Boolean)))
      .sort((left, right) => left.localeCompare(right))
      .map(value => ({ value, label: value })),
  ]

  const filteredUsers = users.filter(user => {
    const matchesSearch = query.length === 0 || [user.fullname, user.username, user.email, user.city, user.country]
      .join(' ')
      .toLowerCase()
      .includes(query)

    const matchesAuth = authFilter === 'all' || user.auth === authFilter

    const matchesStatus = statusFilter === 'all'
      || (statusFilter === 'active' && !user.suspended && user.confirmed)
      || (statusFilter === 'suspended' && user.suspended)
      || (statusFilter === 'unconfirmed' && !user.confirmed)
      || (statusFilter === 'never' && user.lastaccess === 0)

    return matchesSearch && matchesAuth && matchesStatus
  })

  const activeUsers = users.filter(user => !user.suspended && user.confirmed).length
  const suspendedUsers = users.filter(user => user.suspended).length
  const neverAccessed = users.filter(user => user.lastaccess === 0).length
  const selectedUser = users.find(user => String(user.id) === actionUserId) ?? null

  const runAction = async (fn: () => Promise<unknown>, successMessage: string) => {
    setActionLoading(true)
    try {
      await fn()
      await loadUsers(true)
      notifications.show({ title: t('common.saved'), message: successMessage, color: 'green' })
    } catch (e) {
      notifications.show({ title: t('common.error'), message: e instanceof Error ? e.message : String(e), color: 'red' })
    } finally {
      setActionLoading(false)
    }
  }

  const handleCreateUser = async () => {
    if (!newUsername || !newFirstName || !newLastName || !newEmail || !newPassword) return
    await runAction(
      () => api.moodle.createUser({
        username: newUsername.trim(),
        firstname: newFirstName.trim(),
        lastname: newLastName.trim(),
        email: newEmail.trim(),
        password: newPassword,
      }),
      t('app.users_action_created'),
    )
    setNewUsername('')
    setNewFirstName('')
    setNewLastName('')
    setNewEmail('')
    setNewPassword('')
  }

  const handleSuspendToggle = async (suspended: boolean) => {
    if (!selectedUser) return
    await runAction(
      () => api.moodle.suspendUser(selectedUser.id, suspended),
      suspended ? t('app.users_action_suspended') : t('app.users_action_unsuspended'),
    )
  }

  const handleDeleteUser = async () => {
    if (!selectedUser) return
    if (deleteConfirm.trim() !== selectedUser.username) {
      notifications.show({ title: t('common.error'), message: t('app.users_action_delete_confirm_error'), color: 'red' })
      return
    }
    await runAction(
      () => api.moodle.deleteUser(selectedUser.id),
      t('app.users_action_deleted'),
    )
    setDeleteConfirm('')
    setActionUserId(null)
  }

  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-start">
        <div>
          <Title order={2}>{t('app.users_title')}</Title>
          <Text c="dimmed" mt={6}>{t('app.users_subtitle')}</Text>
        </div>
        <Button
          variant="light"
          leftSection={refreshing ? <Loader size={14} /> : <IconRefresh size={14} />}
          onClick={() => loadUsers(true)}
          disabled={refreshing}
        >
          {t('common.refresh')}
        </Button>
      </Group>

      <Alert color="yellow" icon={<IconShieldCheck size={16} />}>
        {t('app.users_write_notice')}
      </Alert>

      {error && (
        <Alert color="yellow" icon={<IconAlertTriangle size={16} />}>
          {error}
        </Alert>
      )}

      <SimpleGrid cols={{ base: 1, md: 3 }} spacing="md">
        <MetricCard
          title={t('app.users_card_total')}
          value={users.length}
          description={t('app.users_card_total_desc')}
          color="blue"
          icon={<IconUsers size={18} />}
        />
        <MetricCard
          title={t('app.users_card_active')}
          value={activeUsers}
          description={t('app.users_card_active_desc')}
          color="teal"
          icon={<IconUserCheck size={18} />}
        />
        <MetricCard
          title={t('app.users_card_attention')}
          value={suspendedUsers + neverAccessed}
          description={t('app.users_card_attention_desc', { suspended: suspendedUsers, never: neverAccessed })}
          color={(suspendedUsers + neverAccessed) > 0 ? 'orange' : 'gray'}
          icon={<IconUserOff size={18} />}
        />
      </SimpleGrid>

      <Paper withBorder p="md" radius="md">
        <Title order={4} mb="sm">{t('app.users_actions_title')}</Title>
        <SimpleGrid cols={{ base: 1, xl: 2 }} spacing="md">
          <Stack gap="xs">
            <Text size="sm" fw={600}>{t('app.users_actions_create')}</Text>
            <Group grow>
              <TextInput
                label={t('app.users_create_username')}
                value={newUsername}
                onChange={event => setNewUsername(event.currentTarget.value)}
              />
              <TextInput
                label={t('app.users_create_email')}
                value={newEmail}
                onChange={event => setNewEmail(event.currentTarget.value)}
              />
            </Group>
            <Group grow>
              <TextInput
                label={t('app.users_create_firstname')}
                value={newFirstName}
                onChange={event => setNewFirstName(event.currentTarget.value)}
              />
              <TextInput
                label={t('app.users_create_lastname')}
                value={newLastName}
                onChange={event => setNewLastName(event.currentTarget.value)}
              />
            </Group>
            <PasswordInput
              label={t('app.users_create_password')}
              value={newPassword}
              onChange={event => setNewPassword(event.currentTarget.value)}
            />
            <Button
              variant="light"
              onClick={handleCreateUser}
              disabled={actionLoading || !newUsername || !newFirstName || !newLastName || !newEmail || !newPassword}
            >
              {t('app.users_create_button')}
            </Button>
          </Stack>

          <Stack gap="xs">
            <Text size="sm" fw={600}>{t('app.users_actions_manage')}</Text>
            <Select
              label={t('app.users_manage_user')}
              data={users.map(user => ({ value: String(user.id), label: `${user.fullname || user.username} (@${user.username})` }))}
              value={actionUserId}
              onChange={setActionUserId}
              searchable
              placeholder={t('app.users_manage_user_placeholder')}
            />
            <Group>
              <Button
                variant="light"
                color="orange"
                onClick={() => handleSuspendToggle(true)}
                disabled={actionLoading || !selectedUser || selectedUser.suspended}
              >
                {t('app.users_suspend_button')}
              </Button>
              <Button
                variant="light"
                color="teal"
                onClick={() => handleSuspendToggle(false)}
                disabled={actionLoading || !selectedUser || !selectedUser.suspended}
              >
                {t('app.users_unsuspend_button')}
              </Button>
            </Group>
            <TextInput
              label={t('app.users_delete_confirm_label', { username: selectedUser?.username ?? '...' })}
              placeholder={t('app.users_delete_confirm_placeholder')}
              value={deleteConfirm}
              onChange={event => setDeleteConfirm(event.currentTarget.value)}
            />
            <Button
              color="red"
              variant="light"
              onClick={handleDeleteUser}
              disabled={actionLoading || !selectedUser}
            >
              {t('app.users_delete_button')}
            </Button>
          </Stack>
        </SimpleGrid>
      </Paper>

      <Paper withBorder p="md" radius="md">
        <Group justify="space-between" align="flex-end" mb="sm">
          <div>
            <Title order={4}>{t('app.users_directory_title')}</Title>
            <Text size="sm" c="dimmed">{t('app.users_directory_count', { shown: filteredUsers.length, total: users.length })}</Text>
          </div>
          <Badge variant="light" color="gray">{t('cfg.auth_methods')}: {authOptions.length - 1}</Badge>
        </Group>

        <Group grow align="flex-end" mb="md">
          <TextInput
            label={t('app.users_search_label')}
            placeholder={t('app.users_search_placeholder')}
            value={search}
            onChange={event => setSearch(event.currentTarget.value)}
            leftSection={<IconSearch size={14} />}
          />
          <Select
            label={t('app.users_filter_auth')}
            data={authOptions}
            value={authFilter}
            onChange={value => setAuthFilter(value ?? 'all')}
          />
          <Select
            label={t('app.users_filter_status')}
            data={[
              { value: 'all', label: t('app.users_filter_status_all') },
              { value: 'active', label: t('app.users_status_active') },
              { value: 'suspended', label: t('app.users_status_suspended') },
              { value: 'unconfirmed', label: t('app.users_status_unconfirmed') },
              { value: 'never', label: t('app.users_status_never') },
            ]}
            value={statusFilter}
            onChange={value => setStatusFilter(value ?? 'all')}
          />
        </Group>

        {loading ? (
          <Group gap="sm"><Loader size="sm" /><Text size="sm">{t('app.users_loading')}</Text></Group>
        ) : filteredUsers.length === 0 ? (
          <Text size="sm" c="dimmed">{t('app.users_empty')}</Text>
        ) : (
          <ScrollArea>
            <Table striped highlightOnHover withTableBorder>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t('app.users_col_identity')}</Table.Th>
                  <Table.Th>{t('app.users_col_status')}</Table.Th>
                  <Table.Th>{t('app.users_col_auth')}</Table.Th>
                  <Table.Th>{t('app.users_col_last_access')}</Table.Th>
                  <Table.Th>{t('app.users_col_location')}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {filteredUsers.map(user => (
                  <Table.Tr key={user.id}>
                    <Table.Td>
                      <Stack gap={2}>
                        <Text fw={600} size="sm">{user.fullname || user.username}</Text>
                        <Text size="xs" c="dimmed">@{user.username}</Text>
                        <Group gap={6}>
                          <IconMail size={12} />
                          <Text size="xs" c="dimmed">{user.email || '—'}</Text>
                        </Group>
                      </Stack>
                    </Table.Td>
                    <Table.Td>
                      <Group gap={6}>
                        {user.suspended ? (
                          <Badge color="orange">{t('app.users_status_suspended')}</Badge>
                        ) : user.confirmed ? (
                          <Badge color="teal">{t('app.users_status_active')}</Badge>
                        ) : (
                          <Badge color="yellow">{t('app.users_status_unconfirmed')}</Badge>
                        )}
                        {user.lastaccess === 0 && <Badge variant="outline">{t('app.users_status_never')}</Badge>}
                      </Group>
                    </Table.Td>
                    <Table.Td>
                      <Badge variant="light" color="gray">{user.auth || 'manual'}</Badge>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{formatLastAccess(user.lastaccess, t)}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{[user.city, user.country].filter(Boolean).join(', ') || '—'}</Text>
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