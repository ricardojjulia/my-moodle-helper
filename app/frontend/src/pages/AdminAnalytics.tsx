import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Badge,
  Box,
  Group,
  Loader,
  Paper,
  Progress,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  ThemeIcon,
  Title,
} from '@mantine/core'
import {
  IconAlertTriangle,
  IconBook2,
  IconChartBar,
  IconRefresh,
  IconSchool,
  IconUserCheck,
  IconUserOff,
  IconUsers,
} from '@tabler/icons-react'
import { useTranslation } from 'react-i18next'
import { api, type CourseAnalytics, type MoodleCourse, type MoodleStats } from '../api/client'

function StatCard({ icon, label, value, color, sub }: {
  icon: React.ReactNode
  label: string
  value: React.ReactNode
  color: string
  sub?: string
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
          {sub && <Text size="xs" c="dimmed" mt={2}>{sub}</Text>}
        </Box>
      </Group>
    </Paper>
  )
}

function CourseAnalyticsPanel({ courseId, shortname }: { courseId: number; shortname: string }) {
  const { t } = useTranslation()
  const [data, setData] = useState<CourseAnalytics | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    api.moodle.analytics(courseId)
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [courseId])

  if (loading) return <Stack align="center" py="xl"><Loader /><Text size="sm" c="dimmed">{t('moodle.analytics_loading')}</Text></Stack>
  if (error) return <Alert color="red" title={t('moodle.analytics_error')} icon={<IconAlertTriangle size={14} />}>{error}</Alert>
  if (!data) return null

  const enrollment = data.enrollment
  const dist = data.grade_distribution
  const total = Object.values(dist).reduce((a, b) => a + b, 0)
  const weakQuizzes = (data.quizzes || []).filter(q => q.pass_rate !== null && q.pass_rate < 70)
  const gradeColors: Record<string, string> = { A: 'green', B: 'teal', C: 'blue', D: 'yellow', F: 'red' }

  return (
    <Stack gap="md">
      <SimpleGrid cols={{ base: 1, md: 2, xl: 4 }} spacing="sm">
        <StatCard
          icon={<IconUsers size={16} />}
          label={t('moodle.enrolled')}
          value={enrollment.total}
          color="blue"
        />
        <StatCard
          icon={<IconUserCheck size={16} />}
          label={t('moodle.active_30d')}
          value={enrollment.active_30d}
          color="green"
          sub={enrollment.total > 0 ? `${Math.round(enrollment.active_30d / enrollment.total * 100)}%` : undefined}
        />
        <StatCard
          icon={<IconChartBar size={16} />}
          label={t('moodle.pass_rate')}
          value={data.pass_rate !== null ? `${data.pass_rate}%` : '—'}
          color={data.pass_rate !== null && data.pass_rate >= 70 ? 'green' : 'red'}
          sub={data.avg_grade !== null ? t('moodle.avg_pct', { n: data.avg_grade }) : undefined}
        />
        <StatCard
          icon={<IconUserOff size={16} />}
          label={t('moodle.never_accessed')}
          value={enrollment.never_accessed}
          color={enrollment.never_accessed > 0 ? 'orange' : 'gray'}
        />
      </SimpleGrid>

      {total > 0 && (
        <Paper withBorder p="md" radius="md">
          <Text size="sm" fw={600} mb="sm">{t('moodle.grade_dist', { count: data.student_count })}</Text>
          <Stack gap={6}>
            {(['A', 'B', 'C', 'D', 'F'] as const).map(letter => {
              const count = dist[letter]
              const pct = total > 0 ? Math.round(count / total * 100) : 0
              return (
                <Group key={letter} gap="sm" wrap="nowrap">
                  <Badge size="sm" color={gradeColors[letter]} w={28} ta="center">{letter}</Badge>
                  <Box style={{ flex: 1 }}>
                    <Progress value={pct} color={gradeColors[letter]} size="md" />
                  </Box>
                  <Text size="xs" w={60} ta="right">{count} ({pct}%)</Text>
                </Group>
              )
            })}
          </Stack>
        </Paper>
      )}

      {data.grades_error && (
        <Alert color="orange" title={t('moodle.grades_unavail')} py="xs">{data.grades_error}</Alert>
      )}

      {(data.quizzes || []).length > 0 && (
        <Paper withBorder p="md" radius="md">
          <Text size="sm" fw={600} mb="sm">{t('moodle.quiz_perf')}</Text>
          <Table withTableBorder highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t('moodle.quiz_name')}</Table.Th>
                <Table.Th style={{ textAlign: 'center' }}>{t('moodle.quiz_attempts')}</Table.Th>
                <Table.Th style={{ textAlign: 'center' }}>{t('moodle.quiz_avg_grade')}</Table.Th>
                <Table.Th style={{ textAlign: 'center' }}>{t('moodle.quiz_pass_rate')}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {data.quizzes.map(quiz => (
                <Table.Tr key={quiz.id}>
                  <Table.Td><Text size="xs">{quiz.name}</Text></Table.Td>
                  <Table.Td style={{ textAlign: 'center' }}><Text size="xs">{quiz.attempt_count}</Text></Table.Td>
                  <Table.Td style={{ textAlign: 'center' }}>
                    <Badge size="sm" color={quiz.avg_grade !== null && quiz.avg_grade >= 70 ? 'green' : 'red'} variant="light">
                      {quiz.avg_grade !== null ? `${quiz.avg_grade}%` : '—'}
                    </Badge>
                  </Table.Td>
                  <Table.Td style={{ textAlign: 'center' }}>
                    <Badge size="sm" color={quiz.pass_rate !== null && quiz.pass_rate >= 70 ? 'green' : 'orange'} variant="light">
                      {quiz.pass_rate !== null ? `${quiz.pass_rate}%` : '—'}
                    </Badge>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Paper>
      )}

      {weakQuizzes.length > 0 && (
        <Alert color="orange" title={t('moodle.weak_areas', { count: weakQuizzes.length })} icon={<IconAlertTriangle size={14} />}>
          <Text size="xs">
            {t('moodle.weak_desc')} {weakQuizzes.map(q => q.name).join(', ')}
          </Text>
          {shortname && <Text size="xs" mt={4} c="dimmed">{t('moodle.weak_regen')}</Text>}
        </Alert>
      )}

      {data.enrollment_error && <Alert color="orange" title={t('moodle.enrollment_unavail')} py="xs">{data.enrollment_error}</Alert>}
      {data.quizzes_error && <Alert color="orange" title={t('moodle.quiz_unavail')} py="xs">{data.quizzes_error}</Alert>}
    </Stack>
  )
}

export default function AdminAnalyticsPage() {
  const { t } = useTranslation()
  const [courses, setCourses] = useState<MoodleCourse[]>([])
  const [stats, setStats] = useState<MoodleStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [category, setCategory] = useState<string | null>(null)
  const [selectedCourseId, setSelectedCourseId] = useState<string | null>(null)

  const loadData = async (background = false) => {
    if (background) setRefreshing(true)
    else setLoading(true)
    setError(null)

    try {
      const [statsResult, coursesResult] = await Promise.all([
        api.moodle.stats(),
        api.moodle.courses(),
      ])
      setStats(statsResult)
      setCourses(coursesResult)
      setSelectedCourseId((current) => current ?? (coursesResult[0] ? String(coursesResult[0].id) : null))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  const categoryOptions = useMemo(() => {
    const values = Array.from(new Set(courses.map(course => course.category_name || t('app.analytics_uncategorized'))))
    return values.map(value => ({ value, label: value }))
  }, [courses, t])

  const filteredCourses = useMemo(() => {
    if (!category) return courses
    return courses.filter(course => (course.category_name || t('app.analytics_uncategorized')) === category)
  }, [category, courses, t])

  useEffect(() => {
    if (!filteredCourses.some(course => String(course.id) === selectedCourseId)) {
      setSelectedCourseId(filteredCourses[0] ? String(filteredCourses[0].id) : null)
    }
  }, [filteredCourses, selectedCourseId])

  const selectedCourse = filteredCourses.find(course => String(course.id) === selectedCourseId) ?? null

  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-start">
        <div>
          <Title order={2}>{t('app.analytics_title')}</Title>
          <Text c="dimmed" mt={6}>{t('app.analytics_subtitle')}</Text>
        </div>
        <Group>
          <Select
            size="sm"
            clearable
            placeholder={t('app.analytics_filter_category')}
            data={categoryOptions}
            value={category}
            onChange={setCategory}
            w={220}
          />
          <Select
            size="sm"
            placeholder={t('app.analytics_select_course')}
            data={filteredCourses.map(course => ({ value: String(course.id), label: `${course.shortname} · ${course.fullname}` }))}
            value={selectedCourseId}
            onChange={setSelectedCourseId}
            w={340}
            searchable
          />
          <ThemeIcon size="lg" variant="light" color="blue" style={{ cursor: 'pointer' }} onClick={() => loadData(true)}>
            {refreshing ? <Loader size={16} /> : <IconRefresh size={16} />}
          </ThemeIcon>
        </Group>
      </Group>

      {error && <Alert color="red" title={t('common.error')}>{error}</Alert>}

      {loading ? (
        <Group gap="sm"><Loader size="sm" /><Text size="sm" c="dimmed">{t('app.analytics_loading')}</Text></Group>
      ) : (
        <>
          <SimpleGrid cols={{ base: 1, md: 2, xl: 4 }} spacing="sm">
            <StatCard
              icon={<IconBook2 size={16} />}
              label={t('cfg.total_courses')}
              value={stats?.total_courses ?? '—'}
              color="blue"
              sub={category ? t('app.analytics_filtered_courses', { count: filteredCourses.length }) : undefined}
            />
            <StatCard
              icon={<IconUsers size={16} />}
              label={t('cfg.total_users')}
              value={stats?.total_users ?? '—'}
              color="teal"
              sub={stats?.active_30d !== undefined ? t('moodle.dash_active_30', { n: stats.active_30d }) : undefined}
            />
            <StatCard
              icon={<IconSchool size={16} />}
              label={t('cfg.currently_active')}
              value={stats?.active_courses ?? '—'}
              color="violet"
            />
            <StatCard
              icon={<IconChartBar size={16} />}
              label={t('app.analytics_selected_course')}
              value={selectedCourse ? selectedCourse.shortname : '—'}
              color="orange"
              sub={selectedCourse?.category_name || t('app.analytics_uncategorized')}
            />
          </SimpleGrid>

          {!selectedCourse ? (
            <Paper withBorder p="lg" radius="md">
              <Text c="dimmed">{t('app.analytics_no_course')}</Text>
            </Paper>
          ) : (
            <CourseAnalyticsPanel courseId={selectedCourse.id} shortname={selectedCourse.shortname} />
          )}
        </>
      )}
    </Stack>
  )
}