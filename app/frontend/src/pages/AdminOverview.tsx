import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Paper,
  SimpleGrid,
  Stack,
  Text,
  ThemeIcon,
  Title,
} from '@mantine/core'
import {
  IconAlertTriangle,
  IconArrowRight,
  IconClock,
  IconRefresh,
  IconRoute,
  IconShieldCheck,
} from '@tabler/icons-react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import AdminSiteOverview from '../components/AdminSiteOverview'
import { api, type MoodleStats, type PersistedReview, type ReviewSchedule } from '../api/client'

function formatRelativeTime(value: string, t: (key: string, options?: Record<string, unknown>) => string) {
  const date = new Date(value.endsWith('Z') ? value : `${value}Z`)
  const diffMs = Date.now() - date.getTime()
  if (!Number.isFinite(diffMs) || diffMs < 0) return value

  const mins = Math.floor(diffMs / 60000)
  if (mins < 1) return t('common.just_now')
  if (mins < 60) return t('common.ago_mins', { count: mins })

  const hours = Math.floor(mins / 60)
  if (hours < 24) return t('common.ago_hours', { count: hours })

  return t('common.ago_days', { count: Math.floor(hours / 24) })
}

function OverviewCard({
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

export default function AdminOverviewPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [stats, setStats] = useState<MoodleStats | null>(null)
  const [schedules, setSchedules] = useState<ReviewSchedule[]>([])
  const [recentReviews, setRecentReviews] = useState<PersistedReview[]>([])
  const [errors, setErrors] = useState<string[]>([])

  const loadOverview = async (background = false) => {
    if (background) setRefreshing(true)
    else setLoading(true)

    const [statsRes, schedulesRes, reviewsRes] = await Promise.allSettled([
      api.moodle.stats(),
      api.schedules.list(),
      api.reviews.recent(5),
    ])

    const nextErrors: string[] = []

    if (statsRes.status === 'fulfilled') setStats(statsRes.value)
    else {
      setStats(null)
      nextErrors.push(t('app.overview_error_stats'))
    }

    if (schedulesRes.status === 'fulfilled') setSchedules(schedulesRes.value)
    else {
      setSchedules([])
      nextErrors.push(t('app.overview_error_schedules'))
    }

    if (reviewsRes.status === 'fulfilled') setRecentReviews(reviewsRes.value)
    else {
      setRecentReviews([])
      nextErrors.push(t('app.overview_error_reviews'))
    }

    setErrors(nextErrors)
    setLoading(false)
    setRefreshing(false)
  }

  useEffect(() => {
    loadOverview()
  }, [])

  const overdueCount = useMemo(
    () => schedules.filter(s => s.enabled === 1 && new Date(`${s.next_run_at}Z`) <= new Date()).length,
    [schedules],
  )

  const enabledSchedules = useMemo(
    () => schedules.filter(s => s.enabled === 1).length,
    [schedules],
  )

  const avgRecentScore = useMemo(() => {
    if (!recentReviews.length) return '—'
    return Math.round(recentReviews.reduce((sum, review) => sum + review.score, 0) / recentReviews.length)
  }, [recentReviews])

  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-start">
        <div>
          <Title order={2}>{t('app.overview_title')}</Title>
          <Text c="dimmed" mt={6}>{t('app.overview_subtitle')}</Text>
        </div>
        <Button
          variant="light"
          leftSection={refreshing ? <Loader size={14} /> : <IconRefresh size={14} />}
          onClick={() => loadOverview(true)}
          disabled={refreshing}
        >
          {t('common.refresh')}
        </Button>
      </Group>

      {errors.length > 0 && (
        <Alert color="yellow" icon={<IconAlertTriangle size={16} />}>
          {errors.join(' · ')}
        </Alert>
      )}

      <SimpleGrid cols={{ base: 1, md: 3 }} spacing="md">
        <OverviewCard
          title={t('app.overview_card_jobs')}
          value={enabledSchedules}
          description={overdueCount > 0
            ? t('app.overview_card_jobs_overdue', { count: overdueCount })
            : t('app.overview_card_jobs_clear')}
          color={overdueCount > 0 ? 'orange' : 'teal'}
          icon={<IconClock size={18} />}
        />
        <OverviewCard
          title={t('app.overview_card_reviews')}
          value={recentReviews.length}
          description={recentReviews.length > 0
            ? t('app.overview_card_reviews_avg', { score: avgRecentScore })
            : t('app.overview_card_reviews_empty')}
          color="violet"
          icon={<IconShieldCheck size={18} />}
        />
        <OverviewCard
          title={t('app.overview_card_routes')}
          value={t('app.overview_card_routes_value')}
          description={t('app.overview_card_routes_desc')}
          color="blue"
          icon={<IconRoute size={18} />}
        />
      </SimpleGrid>

      <AdminSiteOverview stats={stats} loading={loading} />

      <SimpleGrid cols={{ base: 1, xl: 2 }} spacing="md">
        <Paper withBorder p="md" radius="md">
          <Title order={4} mb="sm">{t('app.overview_quick_actions')}</Title>
          <Stack gap="xs">
            <Button justify="space-between" variant="light" rightSection={<IconArrowRight size={14} />} onClick={() => navigate('/admin/courses')}>
              {t('app.overview_go_courses')}
            </Button>
            <Button justify="space-between" variant="light" rightSection={<IconArrowRight size={14} />} onClick={() => navigate('/admin/settings')}>
              {t('app.overview_go_settings')}
            </Button>
            <Button justify="space-between" variant="light" rightSection={<IconArrowRight size={14} />} onClick={() => navigate('/studio/review')}>
              {t('app.overview_go_review')}
            </Button>
          </Stack>
        </Paper>

        <Paper withBorder p="md" radius="md">
          <Group justify="space-between" mb="sm">
            <Title order={4}>{t('app.overview_recent_reviews')}</Title>
            <Badge variant="light" color="gray">{recentReviews.length}</Badge>
          </Group>
          {loading ? (
            <Group gap="sm"><Loader size="sm" /><Text size="sm">{t('app.overview_loading_reviews')}</Text></Group>
          ) : recentReviews.length === 0 ? (
            <Text c="dimmed" size="sm">{t('app.overview_no_reviews')}</Text>
          ) : (
            <Stack gap="sm">
              {recentReviews.map(review => (
                <Paper key={review.id} withBorder p="sm" radius="sm">
                  <Group justify="space-between" align="flex-start" wrap="nowrap">
                    <div>
                      <Text fw={600} size="sm">{review.shortname}</Text>
                      <Text size="xs" c="dimmed">
                        {review.agent_label} · {formatRelativeTime(review.run_at, t)}
                      </Text>
                    </div>
                    <Badge color={review.score >= 80 ? 'green' : review.score >= 60 ? 'yellow' : 'red'}>
                      {review.score}/100
                    </Badge>
                  </Group>
                </Paper>
              ))}
            </Stack>
          )}
        </Paper>
      </SimpleGrid>

      <Paper withBorder p="md" radius="md">
        <Group justify="space-between" mb="xs">
          <Title order={4}>{t('app.overview_scheduler_health')}</Title>
          {overdueCount > 0 ? <Badge color="orange">{t('cfg.sched_overdue', { count: overdueCount })}</Badge> : <Badge color="teal">{t('common.all_caught_up')}</Badge>}
        </Group>
        {schedules.length === 0 ? (
          <Text c="dimmed" size="sm">{t('cfg.sched_empty')}</Text>
        ) : (
          <Stack gap="xs">
            {schedules.slice(0, 5).map(schedule => {
              const overdue = schedule.enabled === 1 && new Date(`${schedule.next_run_at}Z`) <= new Date()
              return (
                <Group key={schedule.id} justify="space-between" wrap="nowrap">
                  <div>
                    <Text size="sm" fw={600}>{schedule.shortname}</Text>
                    <Text size="xs" c="dimmed">
                      {schedule.agent_label} · {schedule.frequency} · {t('cfg.sched_next')} {formatRelativeTime(schedule.next_run_at, t)}
                    </Text>
                  </div>
                  {overdue ? <Badge color="orange">{t('cfg.sched_overdue_badge')}</Badge> : <Badge color="gray">{t('app.overview_status_scheduled')}</Badge>}
                </Group>
              )
            })}
          </Stack>
        )}
      </Paper>
    </Stack>
  )
}