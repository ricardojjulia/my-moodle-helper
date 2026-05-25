import { Badge, Divider, Group, Loader, Paper, Progress, SimpleGrid, Stack, Text, ThemeIcon, Title } from '@mantine/core'
import {
  IconApi,
  IconBook,
  IconCategory,
  IconCloud,
  IconDeviceMobile,
  IconEyeOff,
  IconSchool,
  IconShield,
  IconUserCheck,
  IconUserOff,
  IconUserX,
  IconUsers,
} from '@tabler/icons-react'
import { useTranslation } from 'react-i18next'
import type { MoodleStats } from '../api/client'

function StatCard({ label, value, color = 'blue', icon }: {
  label: string
  value: number | string | undefined | null
  color?: string
  icon: React.ReactNode
}) {
  return (
    <Paper withBorder p="sm" radius="md" ta="center">
      <ThemeIcon size="lg" radius="md" color={color} variant="light" mx="auto" mb={6}>
        {icon}
      </ThemeIcon>
      <Text fw={700} size="xl" c={color} lh={1}>
        {value ?? '—'}
      </Text>
      <Text size="xs" c="dimmed" mt={4} lh={1.2}>{label}</Text>
    </Paper>
  )
}

export default function AdminSiteOverview({ stats, loading }: { stats: MoodleStats | null; loading: boolean }) {
  const { t } = useTranslation()
  if (loading) {
    return (
      <Paper withBorder p="md" radius="md">
        <Group gap="sm">
          <Loader size="sm" />
          <Text size="sm" fw={500}>{t('cfg.loading_metrics')}</Text>
        </Group>
      </Paper>
    )
  }

  if (!stats) return null

  const maxCourses = Math.max(...Object.values(stats.courses_per_category ?? {}), 1)

  return (
    <Paper withBorder p="md" radius="md">
      <Group justify="space-between" mb="sm" wrap="nowrap">
        <div>
          <Group gap="xs">
            <ThemeIcon size="sm" color="blue" variant="light"><IconCloud size={12} /></ThemeIcon>
            <Title order={5}>{stats.site_name || 'Site Overview'}</Title>
            {stats.current_user_is_admin && (
              <Badge size="xs" color="red" leftSection={<IconShield size={9} />}>Admin</Badge>
            )}
            {stats.mobile_service_enabled && (
              <Badge size="xs" color="teal" leftSection={<IconDeviceMobile size={9} />}>Mobile</Badge>
            )}
          </Group>
          <Text size="xs" c="dimmed" mt={2}>
            {stats.release}
            {stats.current_user_fullname ? ` · ${t('cfg.connected_as', { name: stats.current_user_fullname })}` : ''}
            {stats.api_functions_count ? ` · ${t('cfg.api_functions_count', { count: stats.api_functions_count })}` : ''}
          </Text>
        </div>
      </Group>

      <Divider mb="sm" />

      <Text size="xs" fw={600} c="dimmed" mb={6} tt="uppercase">{t('cfg.courses_section')}</Text>
      <SimpleGrid cols={4} spacing="xs" mb="md">
        <StatCard
          label={t('cfg.total_courses')}
          value={stats.total_courses}
          color="blue"
          icon={<IconBook size={16} />}
        />
        <StatCard
          label={t('cfg.visible')}
          value={stats.visible_courses}
          color="green"
          icon={<IconBook size={16} />}
        />
        <StatCard
          label={t('cfg.hidden')}
          value={stats.hidden_courses}
          color="orange"
          icon={<IconEyeOff size={16} />}
        />
        <StatCard
          label={t('cfg.categories')}
          value={stats.total_categories}
          color="teal"
          icon={<IconCategory size={16} />}
        />
      </SimpleGrid>

      <Text size="xs" fw={600} c="dimmed" mb={6} tt="uppercase">{t('cfg.users_section')}</Text>
      <SimpleGrid cols={4} spacing="xs" mb="md">
        <StatCard
          label={t('cfg.total_users')}
          value={stats.total_users}
          color="blue"
          icon={<IconUsers size={16} />}
        />
        <StatCard
          label={t('cfg.active_30')}
          value={stats.active_30d}
          color="green"
          icon={<IconUserCheck size={16} />}
        />
        <StatCard
          label={t('cfg.suspended')}
          value={stats.suspended_users}
          color="orange"
          icon={<IconUserX size={16} />}
        />
        <StatCard
          label={t('cfg.never_logged')}
          value={stats.never_logged_in}
          color="red"
          icon={<IconUserOff size={16} />}
        />
      </SimpleGrid>

      <SimpleGrid cols={4} spacing="xs" mb="md">
        <StatCard
          label={t('cfg.currently_active')}
          value={stats.active_courses ?? '—'}
          color="violet"
          icon={<IconSchool size={16} />}
        />
        <StatCard
          label={t('cfg.mobile_service')}
          value={stats.mobile_service_enabled ? t('cfg.enabled') : t('cfg.disabled')}
          color={stats.mobile_service_enabled ? 'teal' : 'gray'}
          icon={<IconDeviceMobile size={16} />}
        />
        <StatCard
          label={t('cfg.api_functions')}
          value={stats.api_functions_count}
          color="grape"
          icon={<IconApi size={16} />}
        />
        <StatCard
          label={t('cfg.activity_rate')}
          value={stats.total_users
            ? `${Math.round(((stats.active_30d ?? 0) / stats.total_users) * 100)}%`
            : '—'}
          color="cyan"
          icon={<IconUserCheck size={16} />}
        />
      </SimpleGrid>

      {stats.courses_per_category && Object.keys(stats.courses_per_category).length > 0 && (
        <>
          <Divider mb="sm" />
          <Text size="xs" fw={600} c="dimmed" mb={8} tt="uppercase">{t('cfg.courses_per_cat')}</Text>
          <Stack gap={8}>
            {Object.entries(stats.courses_per_category).map(([cat, count]) => (
              <div key={cat}>
                <Group justify="space-between" mb={2}>
                  <Text size="xs" lineClamp={1} style={{ flex: 1 }}>{cat}</Text>
                  <Badge size="xs" variant="outline" color="blue">{count}</Badge>
                </Group>
                <Progress
                  value={(count / maxCourses) * 100}
                  size="sm"
                  color="blue"
                  radius="xl"
                />
              </div>
            ))}
          </Stack>
        </>
      )}

      {stats.auth_methods && Object.keys(stats.auth_methods).length > 0 && (
        <>
          <Divider mt="sm" mb="sm" />
          <Text size="xs" fw={600} c="dimmed" mb={6} tt="uppercase">{t('cfg.auth_methods')}</Text>
          <Group gap={6} wrap="wrap">
            {Object.entries(stats.auth_methods).map(([method, count]) => (
              <Badge key={method} size="sm" variant="light" color="gray">
                {method}: {count}
              </Badge>
            ))}
          </Group>
        </>
      )}

      {(stats.site_error || stats.courses_error || stats.categories_error || stats.users_error) && (
        <>
          <Divider mt="sm" mb="xs" />
          <Text size="xs" c="dimmed">
            {t('cfg.metrics_unavail')}{' '}
            {[stats.site_error, stats.courses_error, stats.categories_error, stats.users_error]
              .filter(Boolean)
              .join(' · ')}
          </Text>
        </>
      )}
    </Paper>
  )
}