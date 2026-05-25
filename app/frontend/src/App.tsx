import { useState, useCallback, useEffect, type ElementType } from 'react'
import {
  AppShell, Title, Group, Text, Loader, Badge, Box,
  Modal, PasswordInput, Button, Stack, Alert, TextInput, Stepper, Anchor,
  SegmentedControl, NavLink, Select, Burger, Divider,
} from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import {
  IconBooks, IconWand, IconCloud, IconSettings, IconShieldCheck, IconMap2, IconLock,
  IconCheck, IconPlugConnected, IconRocket, IconLayoutDashboard, IconUsers,
  IconUserPlus, IconBook2, IconChartBar, IconClock, IconTool, IconRefresh,
} from '@tabler/icons-react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import i18n from './i18n/config'
import LibraryPage          from './pages/Library'
import NewCoursePage        from './pages/NewCourse'
import MoodlePage           from './pages/MoodleCourses'
import CanvasPage           from './pages/CanvasCourses'
import SettingsPage         from './pages/Settings'
import AutonomousReviewPage from './pages/AutonomousReview'
import CurriculumPage       from './pages/Curriculum'
import AdminOverviewPage    from './pages/AdminOverview'
import AdminAnalyticsPage   from './pages/AdminAnalytics'
import AdminAutomationPage  from './pages/AdminAutomation'
import AdminUsersPage       from './pages/AdminUsers'
import AdminEnrollmentPage  from './pages/AdminEnrollment'
import { api, tokenStore, type MoodleInstance }  from './api/client'

type NavStatus = 'live' | 'partial' | 'planned'

type NavItem = {
  to: string
  label: string
  icon: ElementType
  status?: NavStatus
  match?: (pathname: string) => boolean
}

function PlaceholderPage({
  title,
  description,
  status,
}: {
  title: string
  description: string
  status: NavStatus
}) {
  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-start">
        <div>
          <Title order={2}>{title}</Title>
          <Text c="dimmed" mt={6}>{description}</Text>
        </div>
        <StatusBadge status={status} />
      </Group>
      <Alert color={status === 'planned' ? 'gray' : 'yellow'}>
        This workspace is scaffolded in Slice 1 so routing and navigation are stable. The functional UI for this area lands in the next execution slices.
      </Alert>
    </Stack>
  )
}

function StatusBadge({ status }: { status: NavStatus }) {
  if (status === 'live') return <Badge color="green">Live</Badge>
  if (status === 'partial') return <Badge color="yellow">Partial</Badge>
  return <Badge color="gray">Planned</Badge>
}

function inferEnvironment(instanceName: string) {
  const normalized = instanceName.trim().toLowerCase()
  if (!normalized) return 'Custom'
  if (normalized.includes('prod')) return 'Prod'
  if (normalized.includes('stag')) return 'Staging'
  if (normalized.includes('dev') || normalized.includes('local') || normalized.includes('test')) return 'Dev'
  return 'Custom'
}

export default function App() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const location = useLocation()
  const [navOpened, { toggle: toggleNav, close: closeNav }] = useDisclosure(false)
  const [generating, setGenerating] = useState(false)
  const [genLabel, setGenLabel]     = useState<string>('')
  const [jumpCourse, setJumpCourse] = useState<string | null>(null)
  const [loginOpen, setLoginOpen]   = useState(false)
  const [loginToken, setLoginToken] = useState('')
  const [loginError, setLoginError] = useState('')
  const [loginBusy, setLoginBusy]   = useState(false)

  // First-run wizard
  const [wizardOpen,  setWizardOpen]  = useState(false)
  const [wizardStep,  setWizardStep]  = useState(0)
  const [wizardUrl,   setWizardUrl]   = useState('')
  const [wizardTesting, setWizardTesting] = useState(false)
  const [wizardError, setWizardError]   = useState('')
  const [wizardOk,    setWizardOk]    = useState(false)
  const [instances, setInstances] = useState<MoodleInstance[]>([])
  const [activeInstance, setActiveInstance] = useState('')
  const [switchingInstance, setSwitchingInstance] = useState(false)

  // On mount: check if auth is enabled and our stored token is valid
  useEffect(() => {
    api.auth.status().then(({ enabled }) => {
      if (!enabled) return
      const stored = tokenStore.get()
      if (!stored) { setLoginOpen(true); return }
      api.auth.verify().catch(() => {
        tokenStore.clear()
        setLoginOpen(true)
      })
    }).catch(() => {})
  }, [])

  // On mount: show wizard if no LLM URL is configured
  useEffect(() => {
    api.settings.get().then(s => {
      if (!s.llm_url) setWizardOpen(true)
    }).catch(() => {})
  }, [])

  const refreshInstances = useCallback(async () => {
    try {
      const [settings, list] = await Promise.all([
        api.settings.get(),
        api.settings.listInstances(),
      ])
      setActiveInstance(settings.active_instance || '')
      setInstances(list)
    } catch {
      setInstances([])
      setActiveInstance('')
    }
  }, [])

  useEffect(() => {
    refreshInstances()
  }, [refreshInstances])

  const wizardTestConnection = async () => {
    if (!wizardUrl.trim()) { setWizardError(t('app.wizard_url_required')); return }
    setWizardTesting(true)
    setWizardError('')
    setWizardOk(false)
    try {
      await api.settings.save({ llm_url: wizardUrl.trim() } as never)
      await api.llm.models(wizardUrl.trim())
      setWizardOk(true)
      setWizardError('')
    } catch {
      setWizardError(t('app.wizard_url_error'))
      setWizardOk(false)
    } finally {
      setWizardTesting(false)
    }
  }

  // Intercept 401s from any tab and prompt re-login
  useEffect(() => {
    const handler = (e: PromiseRejectionEvent) => {
      if ((e.reason as { status?: number })?.status === 401) {
        tokenStore.clear()
        setLoginOpen(true)
        e.preventDefault()
      }
    }
    window.addEventListener('unhandledrejection', handler)
    return () => window.removeEventListener('unhandledrejection', handler)
  }, [])

  const handleLogin = async () => {
    setLoginBusy(true)
    setLoginError('')
    tokenStore.set(loginToken.trim())
    try {
      await api.auth.verify()
      setLoginOpen(false)
      setLoginToken('')
    } catch {
      tokenStore.clear()
      setLoginError(t('app.auth_invalid'))
    } finally {
      setLoginBusy(false)
    }
  }

  const handleGeneratingChange = useCallback((v: boolean, label?: string) => {
    setGenerating(v)
    if (label) setGenLabel(label)
    else if (!v) setGenLabel('')
  }, [])

  const handleCreated = useCallback(() => navigate('/studio/library'), [navigate])

  const handleInstanceChange = useCallback(async (name: string | null) => {
    if (!name || name === activeInstance) return
    setSwitchingInstance(true)
    try {
      await api.settings.activateInstance(name)
      await refreshInstances()
      window.location.reload()
    } finally {
      setSwitchingInstance(false)
    }
  }, [activeInstance, refreshInstances])

  const primaryNavItems: NavItem[] = [
    {
      to: '/admin/overview',
      label: t('app.nav_overview'),
      icon: IconLayoutDashboard,
      status: 'live',
    },
    {
      to: '/admin/users',
      label: t('app.nav_users'),
      icon: IconUsers,
      status: 'live',
    },
    {
      to: '/admin/enrollment',
      label: t('app.nav_enrollment'),
      icon: IconUserPlus,
      status: 'live',
    },
    {
      to: '/admin/courses',
      label: t('app.nav_courses'),
      icon: IconBook2,
      status: 'live',
      match: (pathname: string) => pathname === '/admin/courses' || pathname === '/admin/canvas',
    },
    {
      to: '/admin/analytics',
      label: t('app.nav_analytics'),
      icon: IconChartBar,
      status: 'live',
    },
    {
      to: '/admin/automation',
      label: t('app.nav_automation'),
      icon: IconClock,
      status: 'live',
    },
    {
      to: '/admin/settings',
      label: t('app.nav_settings'),
      icon: IconSettings,
      status: 'live',
    },
  ]

  const studioNavItems: NavItem[] = [
    {
      to: '/studio/library',
      label: t('app.tab_library'),
      icon: IconBooks,
      status: 'live',
    },
    {
      to: '/studio/new',
      label: t('app.tab_studio'),
      icon: IconWand,
      status: 'live',
    },
    {
      to: '/studio/review',
      label: t('app.tab_review'),
      icon: IconShieldCheck,
      status: 'live',
    },
    {
      to: '/studio/curriculum',
      label: t('app.tab_curriculum'),
      icon: IconMap2,
      status: 'live',
    },
  ]

  const pathname = location.pathname
  const isStudioNew = pathname === '/studio/new'

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{ width: 300, breakpoint: 'sm', collapsed: { mobile: !navOpened } }}
      padding="md"
    >
      {/* ── First-run wizard ────────────────────────────────────────────────── */}
      <Modal
        opened={wizardOpen && !loginOpen}
        onClose={() => setWizardOpen(false)}
        title={<Group gap="xs"><IconRocket size={18} /><Text fw={600}>{t('app.wizard_title')}</Text></Group>}
        size="md"
        centered
      >
        <Stepper active={wizardStep} onStepClick={setWizardStep} size="sm" mb="md">
          <Stepper.Step label={t('app.wizard_step_connect')} description={t('app.wizard_step_connect_desc')} icon={<IconPlugConnected size={16} />} />
          <Stepper.Step label={t('app.wizard_step_ready')} description={t('app.wizard_step_ready_desc')} icon={<IconCheck size={16} />} />
        </Stepper>

        {wizardStep === 0 && (
          <Stack gap="sm">
            <Text size="sm">{t('app.wizard_enter_url')}</Text>
            <TextInput
              label={t('app.wizard_llm_endpoint')}
              placeholder="http://localhost:1234/v1"
              value={wizardUrl}
              onChange={e => { setWizardUrl(e.currentTarget.value); setWizardOk(false) }}
              onKeyDown={e => e.key === 'Enter' && wizardTestConnection()}
            />
            <Text size="xs" c="dimmed">
              {t('app.wizard_lm_studio')} <code>http://localhost:1234/v1</code>
              &nbsp;·&nbsp;
              {t('app.wizard_ollama')} <code>http://localhost:11434/v1</code>
            </Text>
            {wizardError && <Alert color="red">{wizardError}</Alert>}
            {wizardOk && <Alert color="green" icon={<IconCheck size={14} />}>{t('app.wizard_connected')}</Alert>}
            <Group>
              <Button
                variant="light" loading={wizardTesting}
                leftSection={<IconPlugConnected size={14} />}
                onClick={wizardTestConnection}
              >
                {t('common.test_conn')}
              </Button>
              <Button
                disabled={!wizardOk}
                rightSection={<IconCheck size={14} />}
                onClick={() => setWizardStep(1)}
              >
                {t('common.next')}
              </Button>
            </Group>
            <Text size="xs" c="dimmed">
              {t('app.wizard_cloud_provider')}{' '}
              <Anchor
                size="xs"
                href="/admin/settings"
                onClick={(event) => {
                  event.preventDefault()
                  setWizardOpen(false)
                  navigate('/admin/settings')
                }}
              >
                {t('app.wizard_cloud_settings')}
              </Anchor>
            </Text>
          </Stack>
        )}

        {wizardStep === 1 && (
          <Stack gap="sm">
            <Alert color="green" icon={<IconCheck size={14} />} title={t('app.wizard_all_set_title')}>
              {t('app.wizard_all_set_desc')}
            </Alert>
            <Text size="sm" c="dimmed">
              {t('app.wizard_tip')}
            </Text>
            <Group>
              <Button
                onClick={() => { setWizardOpen(false); navigate('/studio/new') }}
                leftSection={<IconWand size={14} />}
              >
                {t('app.wizard_open_studio')}
              </Button>
              <Button variant="subtle" onClick={() => setWizardOpen(false)}>
                {t('common.dismiss')}
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>

      <Modal
        opened={loginOpen}
        onClose={() => {}}
        withCloseButton={false}
        closeOnClickOutside={false}
        closeOnEscape={false}
        title={<Group gap="xs"><IconLock size={18} /><Text fw={600}>{t('app.auth_required')}</Text></Group>}
        centered
      >
        <Stack gap="sm">
          <Text size="sm" c="dimmed">{t('app.auth_enter_token')}</Text>
          {loginError && <Alert color="red">{loginError}</Alert>}
          <PasswordInput
            placeholder={t('app.auth_placeholder')}
            value={loginToken}
            onChange={e => setLoginToken(e.currentTarget.value)}
            onKeyDown={e => e.key === 'Enter' && handleLogin()}
            autoFocus
          />
          <Button onClick={handleLogin} loading={loginBusy} disabled={!loginToken.trim()}>
            {t('app.auth_sign_in')}
          </Button>
        </Stack>
      </Modal>

      <AppShell.Header px="md" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <Burger opened={navOpened} onClick={toggleNav} hiddenFrom="sm" size="sm" />
        <Group gap="xs" style={{ flex: 1 }}>
          <IconBooks size={24} color="#1c7ed6" />
          <div>
            <Title order={5} style={{ lineHeight: 1 }}>{t('app.title')}</Title>
            <Text size="xs" c="dimmed" style={{ lineHeight: 1 }}>{t('app.subtitle')}</Text>
          </div>
        </Group>
        <Select
          size="xs"
          w={180}
          placeholder={t('app.instance_label')}
          data={instances.map((instance) => ({ value: instance.name, label: instance.name }))}
          value={activeInstance || null}
          onChange={handleInstanceChange}
          disabled={switchingInstance || instances.length === 0}
          searchable
        />
        <Badge variant="light" color="blue">
          {inferEnvironment(activeInstance)}
        </Badge>
        <Button
          size="xs"
          variant="subtle"
          leftSection={<IconRefresh size={14} />}
          onClick={() => window.location.reload()}
        >
          {t('common.refresh')}
        </Button>
        <SegmentedControl
          size="xs"
          value={i18n.language.startsWith('es') ? 'es' : 'en'}
          onChange={v => i18n.changeLanguage(v)}
          data={[{ label: 'EN', value: 'en' }, { label: 'ES', value: 'es' }]}
        />
      </AppShell.Header>

      <AppShell.Navbar p="sm">
        <Stack gap="xs">
          <Text size="xs" fw={700} c="dimmed" tt="uppercase">{t('app.nav_admin')}</Text>
          {primaryNavItems.map((item) => {
            const Icon = item.icon
            const active = item.match ? item.match(pathname) : pathname === item.to
            return (
              <NavLink
                key={item.to}
                component={Link}
                to={item.to}
                label={item.label}
                leftSection={<Icon size={18} />}
                rightSection={item.status ? <StatusBadge status={item.status} /> : null}
                active={active}
                onClick={() => closeNav()}
              />
            )
          })}

          <Divider my="xs" />
          <Group gap="xs">
            <IconTool size={16} />
            <Text size="xs" fw={700} c="dimmed" tt="uppercase">{t('app.nav_workspace')}</Text>
            {generating && (
              <Badge size="xs" color="blue" variant="filled">
                {genLabel || t('common.generating')}
              </Badge>
            )}
          </Group>
          {studioNavItems.map((item) => {
            const Icon = item.icon
            return (
              <NavLink
                key={item.to}
                component={Link}
                to={item.to}
                label={item.label}
                leftSection={<Icon size={18} />}
                rightSection={item.status ? <StatusBadge status={item.status} /> : null}
                active={pathname === item.to}
                onClick={() => closeNav()}
              />
            )
          })}
        </Stack>
      </AppShell.Navbar>

      <AppShell.Main>
        {!isStudioNew && (
          <Routes>
            <Route path="/" element={<Navigate to="/admin/overview" replace />} />
            <Route path="/library" element={<Navigate to="/studio/library" replace />} />
            <Route path="/new" element={<Navigate to="/studio/new" replace />} />
            <Route path="/moodle" element={<Navigate to="/admin/courses" replace />} />
            <Route path="/review" element={<Navigate to="/studio/review" replace />} />
            <Route path="/curriculum" element={<Navigate to="/studio/curriculum" replace />} />
            <Route path="/settings" element={<Navigate to="/admin/settings" replace />} />
            <Route path="/canvas" element={<Navigate to="/admin/canvas" replace />} />

            <Route path="/admin/overview" element={<AdminOverviewPage />} />
            <Route path="/admin/users" element={<AdminUsersPage />} />
            <Route path="/admin/enrollment" element={<AdminEnrollmentPage />} />
            <Route path="/admin/courses" element={<MoodlePage />} />
            <Route path="/admin/canvas" element={<CanvasPage />} />
            <Route path="/admin/analytics" element={<AdminAnalyticsPage />} />
            <Route path="/admin/automation" element={<AdminAutomationPage />} />
            <Route path="/admin/settings" element={<SettingsPage />} />

            <Route path="/studio/library" element={<LibraryPage initialShortname={jumpCourse} onJumped={() => setJumpCourse(null)} />} />
            <Route path="/studio/review" element={<AutonomousReviewPage onLoadCourse={sn => { setJumpCourse(sn); navigate('/studio/library') }} />} />
            <Route path="/studio/curriculum" element={<CurriculumPage />} />
            <Route path="*" element={<Navigate to="/admin/overview" replace />} />
          </Routes>
        )}

        {/* Always mounted so generation survives route switches */}
        <Box style={{ display: isStudioNew ? 'block' : 'none' }}>
          <NewCoursePage
            onCreated={handleCreated}
            onGeneratingChange={handleGeneratingChange}
          />
        </Box>
      </AppShell.Main>
    </AppShell>
  )
}
