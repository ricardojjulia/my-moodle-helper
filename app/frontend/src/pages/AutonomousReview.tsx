import { useEffect, useState, useMemo, useRef } from 'react'
import {
  Stack, Title, Text, Button, Group, Paper, Switch,
  Textarea, Badge, Loader, ScrollArea,
  SimpleGrid, ThemeIcon, Autocomplete, Select,
  Collapse, Box, MultiSelect, Divider, ActionIcon, Table, Tooltip,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import {
  IconShieldCheck, IconChevronDown, IconChevronRight,
  IconSparkles, IconSchool, IconWand,
  IconCheck, IconX, IconCircle, IconTrash, IconHistory, IconFolderOpen, IconReload,
} from '@tabler/icons-react'
import {
  api, type Course, type CourseReviewResult, type CourseVersion,
  type LlmModel, type PersistedReview,
} from '../api/client'
import { useTranslation } from 'react-i18next'

// ── Agent defaults ────────────────────────────────────────────────────────────

const DEFAULT_REVIEWER = `# Role: Evangelical Theological Course Reviewer
You are a senior academic auditor for a conservative Protestant/Evangelical theological college. Your goal is to ensure all course content is biblically sound, academically rigorous, and adheres strictly to Evangelical standards.

## 1. Theological Guardrails
- **Confessional Stand:** Strictly Evangelical and Protestant.
- **Exclusion:** Flag and remove any specific Roman Catholic references or traditionalist doctrines that contradict Sola Scriptura.
- **Requirements:**
    - Enforce the integration of Bible references in all lessons.
    - Ensure proper usage of Biblical Hermeneutics and Systematic Theology.
    - Challenge the author to include modern, practical examples to ground theological concepts.

## 2. Structural Requirements (5-Week Format)
You must verify the presence of the following:
- **Syllabus:** Must be comprehensive and clearly outline the 5-week progression.
- **Dictionary of Terms:** A glossary of theological and technical terms used in the course.
- **Referential Resources:** A bibliography of Evangelical-approved sources and further reading.
- **Course Quality:** Evaluate the clarity, tone, and formatting of all Markdown/text content.

## 3. Assessment & Engagement Standards
- **Assignments:** Minimum of 2 distinct graded assignments.
- **Testing:** Mandatory final test. Must have a minimum of 30 questions (up to 50 allowed). Flag if the count is <30.
- **Discussion Boards:** Evaluate if a discussion board is pedagogically necessary for the topic. If missing, suggest where a "peer-to-peer" reflection would add value.

## 4. Review Process
For every course unit provided, you will:
1. **Audit** against the Theological Guardrails.
2. **Checklist** the Structural Requirements.
3. **Analyze** the Assessments (count questions and assignments).
4. **Output** a "Course Audit Report" highlighting "Passed," "Needs Revision," or "Missing."`

const DEFAULT_STUDENT = `# Role: Evangelical Student & Content Critic
You are a high-achieving, critical-thinking student at an Evangelical Theological College. Your job is to "stress test" the course content provided by the Review Agent. You are not a passive learner; you look for gaps in logic, lack of practical application, and academic weaknesses.

## 1. Critical Lens
- **Theological Depth:** Does this content actually use Hermeneutics, or is it just "proof-texting" (using isolated verses out of context)?
- **Modern Relevance:** Does this feel like it was written in 1950? Challenge the content if it fails to address how these truths apply to current culture or digital-age ministry.
- **Ecumenical Blindspots:** While respecting the Protestant stand, point out if the lack of "other" views makes the argument weak or defensive.
- **The "So What?" Factor:** Critique sections that are too "dry" or academic without explaining the impact on the believer's life.

## 2. Structural Critique
- **Assignment Load:** Is the workload realistic for a 5-week course, or is it "busy work"?
- **Test Fairness:** Look at the 30-50 question test. Are the questions clear, or are they "trick" questions?
- **Resource Accessibility:** Check if the dictionary and references are helpful or just fluff.

## 3. Interaction Protocol
For every module reviewed, you must provide:
1. **The Critique:** Point out specifically what is confusing, outdated, or academically "thin."
2. **The Improvement Suggestion:** Propose a specific change (e.g., "Add a case study about [X]" or "Rewrite this section to better explain the Greek root word").
3. **The Verdict:** State whether you feel "equipped" by this content or merely "burdened" by it.`

// ── Types ─────────────────────────────────────────────────────────────────────

interface AgentConfig {
  id:          string
  label:       string
  color:       string
  description: string
  prompt:      string
  enabled:     boolean
  _default:    string
}

interface ReviewRun extends CourseReviewResult {
  agent_label: string
  agent_color: string
}

interface FixFinding {
  id: string
  line: string
}

interface ProgressStep {
  id:     string
  label:  string
  status: 'pending' | 'running' | 'done' | 'error'
}

// ── Step list component ───────────────────────────────────────────────────────

const STEP_STYLES: Record<ProgressStep['status'], { bg: string; border: string; textColor: string }> = {
  pending: { bg: 'rgba(255,255,255,0.04)', border: 'transparent',                          textColor: 'dimmed'  },
  running: { bg: 'rgba(167,139,250,0.18)', border: 'var(--mantine-color-violet-5)',         textColor: 'inherit' },
  done:    { bg: 'rgba(74,222,128,0.13)',  border: 'var(--mantine-color-green-5)',          textColor: 'green'   },
  error:   { bg: 'rgba(248,113,113,0.15)', border: 'var(--mantine-color-red-5)',            textColor: 'red'     },
}

function StepList({ steps }: { steps: ProgressStep[] }) {
  return (
    <ScrollArea mah={280} offsetScrollbars>
      <Stack gap={3} py={2}>
        {steps.map(step => {
          const s = STEP_STYLES[step.status]
          return (
            <Group
              key={step.id} gap="xs" wrap="nowrap"
              style={{
                padding: '5px 10px',
                borderRadius: 6,
                background: s.bg,
                borderLeft: `3px solid ${s.border}`,
              }}
            >
              {step.status === 'done' && (
                <ThemeIcon size={16} color="green" variant="filled" radius="xl" style={{ flexShrink: 0 }}>
                  <IconCheck size={10} />
                </ThemeIcon>
              )}
              {step.status === 'running' && (
                <Loader size={16} color="violet" style={{ flexShrink: 0 }} />
              )}
              {step.status === 'error' && (
                <ThemeIcon size={16} color="red" variant="filled" radius="xl" style={{ flexShrink: 0 }}>
                  <IconX size={10} />
                </ThemeIcon>
              )}
              {step.status === 'pending' && (
                <Box w={16} h={16} style={{ flexShrink: 0, borderRadius: '50%', border: '1.5px solid var(--mantine-color-gray-6)' }} />
              )}
              <Text
                size="xs"
                fw={step.status === 'running' ? 700 : 400}
                c={s.textColor as any}
              >
                {step.label}
              </Text>
            </Group>
          )
        })}
      </Stack>
    </ScrollArea>
  )
}

// ── Build improvement instructions from review results ────────────────────────

function buildInstructions(courseResults: ReviewRun[]): string {
  const failing = collectFindings(courseResults).map(f => f.line)
  if (!failing.length) return ''
  return buildInstructionsFromLines(failing)
}

function buildInstructionsFromLines(failing: string[]): string {
  return (
    'Apply ALL of the following improvements identified by expert reviewers:\n\n'
    + failing.map(f => `- ${f}`).join('\n')
    + '\n\nEnsure every revision item above is directly addressed. '
    + 'Where content is flagged as Missing, add it in full. '
    + 'Where content Needs Revision, rewrite it to meet the standard described. '
    + 'Maintain the existing course structure and module titles.'
  )
}

function collectFindings(courseResults: ReviewRun[]): FixFinding[] {
  return courseResults
    .filter(r => !r.error)
    .flatMap(r => (r.sections ?? []).flatMap(s =>
      s.items
        .filter(i => i.status === 'Needs Revision' || i.status === 'Missing')
        .map(i => {
          const line = `[${r.agent_label} · ${s.title}] ${i.label}: ${i.note}`
          return {
            id: `${r.agent_label}::${s.title}::${i.label}::${i.note}`,
            line,
          }
        })
    ))
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const overallColor = (o: string) =>
  o === 'Passed' ? 'green' : o === 'Needs Revision' ? 'orange' : 'red'

const statusColor = (s: string) =>
  s === 'Passed' ? 'green' : s === 'Needs Revision' ? 'orange' : 'red'

const scoreColor = (n: number) => n >= 80 ? 'green' : n >= 60 ? 'yellow' : 'red'

// ── Agent config card ─────────────────────────────────────────────────────────

function AgentCard({
  config, onChange,
}: {
  config: AgentConfig
  onChange: (patch: Partial<AgentConfig>) => void
}) {
  const { t } = useTranslation()
  const [editOpen, setEditOpen] = useState(false)
  const Icon = config.id === 'reviewer' ? IconShieldCheck : IconSchool

  return (
    <Paper
      withBorder p="md" radius="md"
      style={{
        borderLeft: `3px solid var(--mantine-color-${config.color}-5)`,
        opacity: config.enabled ? 1 : 0.55,
        transition: 'opacity 0.15s',
      }}
    >
      <Group justify="space-between" mb={4}>
        <Group gap="xs">
          <ThemeIcon size="sm" color={config.color} variant="light">
            <Icon size={14} />
          </ThemeIcon>
          <Text size="sm" fw={600} c={config.color}>{config.label}</Text>
        </Group>
        <Switch
          checked={config.enabled}
          onChange={e => onChange({ enabled: e.currentTarget.checked })}
          size="sm"
        />
      </Group>

      <Text size="xs" c="dimmed" mb="xs">{config.description}</Text>

      <Group gap="xs">
        <Button
          size="xs" variant="subtle" px={0}
          rightSection={editOpen ? <IconChevronDown size={11} /> : <IconChevronRight size={11} />}
          onClick={() => setEditOpen(o => !o)}
          color={config.color}
        >
          {editOpen ? t('rev.hide_prompt') : t('rev.edit_prompt')}
        </Button>
        {editOpen && (
          <Button
            size="xs" variant="subtle" color="gray"
            onClick={() => onChange({ prompt: config._default })}
          >
            {t('rev.reset')}
          </Button>
        )}
      </Group>

      <Collapse in={editOpen}>
        <Textarea
          mt="xs"
          minRows={8}
          autosize
          value={config.prompt}
          onChange={e => onChange({ prompt: e.currentTarget.value })}
          styles={{ input: { fontFamily: 'monospace', fontSize: 11 } }}
        />
      </Collapse>
    </Paper>
  )
}

// ── Result card ───────────────────────────────────────────────────────────────

function ResultCard({ result }: { result: ReviewRun }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)

  const allItems    = result.sections?.flatMap(s => s.items) ?? []
  const passedCount = allItems.filter(i => i.status === 'Passed').length
  const borderColor = result.error ? 'red' : overallColor(result.overall ?? '')

  return (
    <Paper
      withBorder p="md" radius="md"
      style={{ borderLeft: `3px solid var(--mantine-color-${borderColor}-5)` }}
    >
      {result.error ? (
        <Group gap="xs">
          <Text fw={600} size="sm">{result.shortname}</Text>
          <Badge size="xs" color="red">Error</Badge>
          <Badge size="xs" color={result.agent_color} variant="outline">{result.agent_label}</Badge>
          <Text size="xs" c="dimmed" ml="xs">{result.error}</Text>
        </Group>
      ) : (
        <>
          <Group justify="space-between" mb="xs" wrap="nowrap">
            <Stack gap={2}>
              <Group gap="xs">
                <Text fw={700} size="sm">{result.shortname}</Text>
                <Badge size="xs" color={result.agent_color} variant="dot">{result.agent_label}</Badge>
              </Group>
              {result.version_num && <Text size="xs" c="dimmed">v{result.version_num}</Text>}
            </Stack>
            <Group gap="xs" style={{ flexShrink: 0 }}>
              <Badge size="sm" color={overallColor(result.overall)} variant="filled">
                {result.overall}
              </Badge>
              <Badge size="sm" color={scoreColor(result.score)} variant="light">
                {result.score}/100
              </Badge>
            </Group>
          </Group>

          <Text size="xs" c="dimmed" mb="sm">{result.summary}</Text>

          <Group gap="xs" mb="xs">
            <Text size="xs" c="dimmed">{t('rev.checks_passed', { passed: passedCount, total: allItems.length })}</Text>
          </Group>

          <Button
            variant="subtle" size="xs" px={0}
            rightSection={open ? <IconChevronDown size={12} /> : <IconChevronRight size={12} />}
            onClick={() => setOpen(o => !o)}
          >
            {open ? t('rev.hide_audit') : t('rev.view_audit')}
          </Button>

          <Collapse in={open}>
            <Stack gap="md" mt="sm">
              {result.sections?.map(section => {
                const sectionPassed = section.items.filter(i => i.status === 'Passed').length
                return (
                  <Box key={section.title}>
                    <Group gap="xs" mb={6}>
                      <Text size="xs" fw={700} tt="uppercase" lts={0.5} c="dimmed">
                        {section.title}
                      </Text>
                      <Badge size="xs" variant="outline" color={sectionPassed === section.items.length ? 'green' : 'orange'}>
                        {sectionPassed}/{section.items.length}
                      </Badge>
                    </Group>
                    <Stack gap={6}>
                      {section.items.map((item, i) => (
                        <Group key={i} gap="xs" wrap="nowrap" align="flex-start">
                          <Badge
                            size="xs"
                            color={statusColor(item.status)}
                            variant="light"
                            style={{ flexShrink: 0, minWidth: 100 }}
                          >
                            {item.status}
                          </Badge>
                          <Box>
                            <Text size="xs" fw={500}>{item.label}</Text>
                            {item.note && <Text size="xs" c="dimmed">{item.note}</Text>}
                          </Box>
                        </Group>
                      ))}
                    </Stack>
                  </Box>
                )
              })}
            </Stack>
          </Collapse>
        </>
      )}
    </Paper>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

const INITIAL_AGENTS: AgentConfig[] = [
  {
    id:          'reviewer',
    label:       'Course Reviewer',
    color:       'violet',
    description: 'Senior academic auditor — checks theology, structure, assessments, and course quality.',
    prompt:      DEFAULT_REVIEWER,
    enabled:     true,
    _default:    DEFAULT_REVIEWER,
  },
  {
    id:          'student',
    label:       'Student Critic',
    color:       'teal',
    description: 'Critical student perspective — stress-tests depth, relevance, fairness, and the "So What?" factor.',
    prompt:      DEFAULT_STUDENT,
    enabled:     true,
    _default:    DEFAULT_STUDENT,
  },
]

export default function AutonomousReviewPage({ onLoadCourse }: { onLoadCourse?: (shortname: string) => void } = {}) {
  const { t } = useTranslation()
  const topRef = useRef<HTMLDivElement>(null)
  const [courses,          setCourses]          = useState<Course[]>([])
  const [agents,           setAgents]           = useState<AgentConfig[]>(INITIAL_AGENTS)
  const [filterCat,        setFilterCat]        = useState<string | null>(null)
  const [selectedSns,      setSelectedSns]      = useState<string[]>([])
  const [versionMap,       setVersionMap]       = useState<Record<string, CourseVersion[]>>({})
  const [selectedVersions, setSelectedVersions] = useState<Record<string, number>>({})
  const [modelId,          setModelId]          = useState('')
  const [modelOptions,     setModelOptions]     = useState<string[]>([])
  const [running,          setRunning]          = useState(false)
  const [results,          setResults]          = useState<ReviewRun[]>([])
  const [configOpen,       setConfigOpen]       = useState(true)
  const [reviewSteps,      setReviewSteps]      = useState<ProgressStep[]>([])
  const [regenerating,     setRegenerating]     = useState<Record<string, boolean>>({})
  const [regenSteps,       setRegenSteps]       = useState<Record<string, ProgressStep[]>>({})
  const [regenDone,        setRegenDone]        = useState<Record<string, CourseVersion>>({})
  const [selectedFindings, setSelectedFindings] = useState<Record<string, string[]>>({})
  const [history,          setHistory]          = useState<PersistedReview[]>([])
  const [historyOpen,      setHistoryOpen]      = useState(false)

  const loadHistory = () =>
    api.reviews.recent().then(setHistory).catch(() => {})

  useEffect(() => {
    loadHistory()
    api.courses.list().then(cs => {
      setCourses(cs)
    }).catch(() => {})

    api.llm.evaluationCache().then(cache => {
      if (cache.results.length) {
        setModelOptions(cache.results.map(m => m.id))
        setModelId(cache.results[0].id)
      }
    }).catch(() => {
      api.llm.models().then(ms => {
        setModelOptions(ms.map((m: LlmModel) => m.id))
        if (ms.length) setModelId(ms[0].id)
      }).catch(() => {})
    })
  }, [])

  // Load versions for newly-selected courses
  useEffect(() => {
    const unloaded = selectedSns.filter(sn => !(sn in versionMap))
    if (!unloaded.length) return
    for (const sn of unloaded) {
      setVersionMap(prev => ({ ...prev, [sn]: [] })) // mark as loading
      api.courses.versions(sn).then(vers => {
        setVersionMap(prev => ({ ...prev, [sn]: vers }))
        if (vers.length) {
          setSelectedVersions(prev => ({ ...prev, [sn]: vers[0].id }))
        }
      }).catch(() => {})
    }
  }, [selectedSns])

  const patchAgent = (id: string, patch: Partial<AgentConfig>) =>
    setAgents(prev => prev.map(a => a.id === id ? { ...a, ...patch } : a))

  const allCategories = useMemo(() => {
    const cats = [...new Set(courses.map(c => c.category).filter(Boolean))]
    return cats.sort().map(c => ({ value: c, label: c }))
  }, [courses])

  const filteredCourses = useMemo(() =>
    filterCat ? courses.filter(c => c.category === filterCat) : courses,
    [courses, filterCat]
  )

  const courseOptions = filteredCourses.map(c => ({
    value: c.shortname,
    label: `${c.shortname} — ${c.fullname}`,
  }))

  const enabledAgents = agents.filter(a => a.enabled)

  const groupedResults = useMemo(() => {
    const map = new Map<string, ReviewRun[]>()
    for (const r of results) {
      if (!map.has(r.shortname)) map.set(r.shortname, [])
      map.get(r.shortname)!.push(r)
    }
    return [...map.entries()]
  }, [results])

  const setRegenStep = (sn: string, id: string, status: ProgressStep['status']) =>
    setRegenSteps(prev => ({
      ...prev,
      [sn]: (prev[sn] ?? []).map(s => s.id === id ? { ...s, status } : s),
    }))

  const applyFeedback = async (shortname: string, courseResults: ReviewRun[], onlyIds?: string[]) => {
    const validResults = courseResults.filter(r => !r.error && r.sections?.length)
    if (!validResults.length) return

    const allFindings = collectFindings(validResults)
    const targetLines = onlyIds?.length
      ? allFindings.filter(f => onlyIds.includes(f.id)).map(f => f.line)
      : allFindings.map(f => f.line)

    if (onlyIds && targetLines.length === 0) {
      notifications.show({ title: t('rev.notif_pick_findings'), message: t('rev.notif_pick_findings_msg'), color: 'orange' })
      return
    }

    const instructions = targetLines.length ? buildInstructionsFromLines(targetLines) : buildInstructions(validResults)
    if (!instructions) {
      notifications.show({ title: t('rev.notif_nothing'), message: t('rev.notif_all_passed'), color: 'green' })
      return
    }

    // Fetch latest version to discover modules
    const versions = await api.courses.versions(shortname).catch(() => [])
    if (!versions.length) return
    const latestVer = await api.courses.version(shortname, versions[0].id).catch(() => null)
    if (!latestVer) return

    const modules: Array<{ number: number; title: string }> =
      ((latestVer.content?.course_structure as any)?.modules ?? [])

    // Build step list
    const steps: ProgressStep[] = [
      { id: 'fork',     label: 'Fork current version',  status: 'pending' },
      ...modules.map(m => ({
        id:     `mod-${m.number}`,
        label:  `Module ${m.number}: ${m.title}`,
        status: 'pending' as const,
      })),
      { id: 'finalize', label: 'Quiz & Syllabus',        status: 'pending' },
    ]
    setRegenSteps(prev => ({ ...prev, [shortname]: steps }))
    setRegenerating(prev => ({ ...prev, [shortname]: true }))

    try {
      // Fork
      setRegenStep(shortname, 'fork', 'running')
      const forked = await api.courses.fork(shortname, latestVer.id)
      setRegenStep(shortname, 'fork', 'done')

      // Regenerate each module
      for (const mod of modules) {
        setRegenStep(shortname, `mod-${mod.number}`, 'running')
        await api.courses.regenerateModule(shortname, forked.id, mod.number, {
          instructions,
          model_id: modelId,
        })
        setRegenStep(shortname, `mod-${mod.number}`, 'done')
      }

      // Finalize: quiz + syllabus
      setRegenStep(shortname, 'finalize', 'running')
      const finalVer = await api.courses.finalizeReview(shortname, forked.id, {
        reviews:  validResults as CourseReviewResult[],
        model_id: modelId,
      })
      setRegenStep(shortname, 'finalize', 'done')

      setRegenDone(prev => ({ ...prev, [shortname]: finalVer }))
      setSelectedFindings(prev => ({ ...prev, [shortname]: [] }))
      notifications.show({
        title:   t('rev.notif_regen_done'),
        message: t('rev.notif_regen_msg', { shortname, n: finalVer.version_num }),
        color:   'green',
        icon:    <IconWand size={16} />,
      })
    } catch (e: any) {
      notifications.show({
        title:   t('rev.notif_regen_failed'),
        message: e.message ?? t('common.error'),
        color:   'red',
      })
    } finally {
      setRegenerating(prev => ({ ...prev, [shortname]: false }))
    }
  }

  const updateReviewStep = (id: string, status: ProgressStep['status']) =>
    setReviewSteps(prev => prev.map(s => s.id === id ? { ...s, status } : s))

  const startReview = async () => {
    if (enabledAgents.length === 0) {
      notifications.show({ title: t('rev.notif_no_agents'), message: t('rev.notif_no_agents_msg'), color: 'orange' })
      return
    }
    setResults([])
    setRunning(true)
    setConfigOpen(false)

    const toReview = courses.filter(c => selectedSns.includes(c.shortname))

    // Build full step list upfront
    const steps: ProgressStep[] = toReview.flatMap(course =>
      enabledAgents.map(agent => ({
        id:     `${course.shortname}::${agent.id}`,
        label:  `${course.shortname} · ${agent.label}`,
        status: 'pending' as const,
      }))
    )
    setReviewSteps(steps)

    let completed = 0

    for (const course of toReview) {
      for (const agent of enabledAgents) {
        const stepId = `${course.shortname}::${agent.id}`
        updateReviewStep(stepId, 'running')

        try {
          const result = await api.courses.review(course.shortname, {
            agent_context: agent.prompt,
            model_id:      modelId,
            version_id:    selectedVersions[course.shortname],
            agent_id:      agent.id,
            agent_label:   agent.label,
            agent_color:   agent.color,
          })
          setResults(prev => [...prev, { ...result, agent_label: agent.label, agent_color: agent.color }])
          updateReviewStep(stepId, 'done')
        } catch (e: any) {
          setResults(prev => [...prev, {
            shortname:   course.shortname,
            version_num: null,
            overall:     'Incomplete' as const,
            score:       0,
            summary:     '',
            sections:    [],
            error:       e.message ?? 'Unknown error',
            agent_label: agent.label,
            agent_color: agent.color,
          }])
          updateReviewStep(stepId, 'error')
        }

        completed++
      }
    }

    setRunning(false)
    loadHistory()
    notifications.show({
      title:   t('rev.notif_complete'),
      message: t('rev.notif_complete_msg', { count: completed, s: completed !== 1 ? 's' : '', courses: toReview.length, cs: toReview.length !== 1 ? 's' : '' }),
      color:   'green',
      icon:    <IconShieldCheck size={16} />,
    })
  }

  const passed     = results.filter(r => r.overall === 'Passed').length
  const needsRev   = results.filter(r => r.overall === 'Needs Revision').length
  const incomplete = results.filter(r => r.overall === 'Incomplete' || r.error).length
  const avgScore   = results.length
    ? Math.round(results.filter(r => !r.error).reduce((s, r) => s + (r.score ?? 0), 0) / (results.length - incomplete || 1))
    : null

  const jumpToReview = (shortname: string) => {
    setSelectedSns([shortname])
    setFilterCat(null)
    topRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  return (
    <Stack gap="md" maw={1000} ref={topRef}>

      {/* Page header */}
      <Group justify="space-between" align="center">
        <Group gap="xs">
          <ThemeIcon size="md" color="violet" variant="light"><IconShieldCheck size={18} /></ThemeIcon>
          <div>
            <Title order={3}>{t('rev.title')}</Title>
            <Text size="xs" c="dimmed">{t('rev.subtitle')}</Text>
          </div>
        </Group>
        {results.length > 0 && !running && (
          <Group gap="xs">
            <Badge color="green"  variant="light">{t('rev.passed', { count: passed })}</Badge>
            <Badge color="orange" variant="light">{t('rev.need_revision', { count: needsRev })}</Badge>
            {incomplete > 0 && <Badge color="red" variant="light">{t('rev.errors', { count: incomplete })}</Badge>}
            {avgScore !== null && <Badge color={scoreColor(avgScore)} variant="filled">{t('rev.avg_score', { score: avgScore })}</Badge>}
          </Group>
        )}
      </Group>

      {/* Config toggle after first run */}
      {results.length > 0 && (
        <Button
          variant="subtle" size="xs"
          rightSection={configOpen ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}
          onClick={() => setConfigOpen(o => !o)}
          style={{ alignSelf: 'flex-start' }}
        >
          {configOpen ? t('rev.hide_config') : t('rev.show_config')}
        </Button>
      )}

      <Collapse in={configOpen}>
        <Stack gap="md">

          {/* Agent cards */}
          <SimpleGrid cols={2} spacing="md">
            {agents.map(agent => (
              <AgentCard
                key={agent.id}
                config={agent}
                onChange={patch => patchAgent(agent.id, patch)}
              />
            ))}
          </SimpleGrid>

          {/* Courses + Model */}
          <SimpleGrid cols={2} spacing="md">
            <Paper withBorder p="md" radius="md" style={{ borderLeft: '3px solid var(--mantine-color-blue-5)' }}>
              <Group justify="space-between" mb="xs">
                <Text size="sm" fw={600} c="blue">{t('rev.courses_label')}</Text>
                <Group gap={4}>
                  <Button size="xs" variant="subtle" onClick={() => setSelectedSns(filteredCourses.map(c => c.shortname))}>{t('rev.select_all')}</Button>
                  <Button size="xs" variant="subtle" color="gray" onClick={() => setSelectedSns([])}>{t('rev.select_none')}</Button>
                </Group>
              </Group>
              <Select
                placeholder={t('rev.all_categories')}
                data={allCategories}
                value={filterCat}
                onChange={v => { setFilterCat(v); setSelectedSns([]) }}
                clearable
                size="sm"
                mb="xs"
              />
              <MultiSelect
                placeholder={t('rev.select_courses')}
                data={courseOptions}
                value={selectedSns}
                onChange={setSelectedSns}
                searchable
                size="sm"
                maxDropdownHeight={220}
              />
              <Text size="xs" c="dimmed" mt="xs">
                {filterCat
                  ? t('rev.n_selected_in', { count: selectedSns.length, total: filteredCourses.length, cat: filterCat })
                  : t('rev.n_selected', { count: selectedSns.length, total: filteredCourses.length })
                }
              </Text>

              {selectedSns.length > 0 && (
                <Box mt="sm">
                  <Text size="xs" fw={500} c="dimmed" mb={6}>{t('rev.version_label')}</Text>
                  <ScrollArea mah={180} offsetScrollbars>
                    <Stack gap={4}>
                      {selectedSns.map(sn => {
                        const vers = versionMap[sn] ?? []
                        const versionOptions = vers.map((v, i) => ({
                          value: String(v.id),
                          label: i === 0 ? t('rev.latest', { n: v.version_num }) : `v${v.version_num}`,
                        }))
                        return (
                          <Group key={sn} gap="xs" wrap="nowrap">
                            <Text
                              size="xs"
                              style={{
                                width: 130,
                                flexShrink: 0,
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                              }}
                            >
                              {sn}
                            </Text>
                            <Select
                              size="xs"
                              style={{ flex: 1 }}
                              data={versionOptions}
                              value={selectedVersions[sn] != null ? String(selectedVersions[sn]) : null}
                              onChange={v => v && setSelectedVersions(prev => ({ ...prev, [sn]: Number(v) }))}
                              placeholder={vers.length === 0 ? t('rev.loading_v') : undefined}
                              disabled={vers.length === 0}
                            />
                          </Group>
                        )
                      })}
                    </Stack>
                  </ScrollArea>
                </Box>
              )}
            </Paper>

            <Paper withBorder p="md" radius="md" style={{ borderLeft: '3px solid var(--mantine-color-orange-5)' }}>
              <Text size="sm" fw={600} c="orange" mb="xs">{t('rev.model_label')}</Text>
              <Autocomplete
                placeholder={t('rev.model_placeholder')}
                data={modelOptions}
                value={modelId}
                onChange={setModelId}
                size="sm"
              />
              <Text size="xs" c="dimmed" mt="xs">{t('rev.model_desc')}</Text>
            </Paper>
          </SimpleGrid>

          {/* Start button */}
          <Button
            variant="gradient"
            gradient={{ from: 'violet', to: 'teal', deg: 135 }}
            size="lg"
            fullWidth
            leftSection={running ? <Loader size="xs" color="white" /> : <IconSparkles size={18} />}
            onClick={startReview}
            disabled={running || selectedSns.length === 0 || enabledAgents.length === 0}
          >
            {running
              ? t('rev.reviewing')
              : t('rev.begin', { courses: selectedSns.length, cs: selectedSns.length !== 1 ? 's' : '', agents: enabledAgents.length, as: enabledAgents.length !== 1 ? 's' : '' })
            }
          </Button>

        </Stack>
      </Collapse>

      {/* Review progress — step list */}
      {(running || reviewSteps.length > 0) && (
        <Paper withBorder p="md" radius="md"
          style={{ borderLeft: '3px solid var(--mantine-color-violet-5)', background: 'var(--mantine-color-body)' }}>
          <Group gap="xs" mb="sm">
            {running && <Loader size="xs" color="violet" />}
            {!running && <ThemeIcon size="xs" color="green" variant="light" radius="xl"><IconCheck size={10} /></ThemeIcon>}
            <Text size="xs" fw={600} c="violet">
              {running
                ? t('rev.progress_running', { done: reviewSteps.filter(s => s.status === 'done').length, total: reviewSteps.length })
                : t('rev.progress_done',    { done: reviewSteps.filter(s => s.status === 'done').length, total: reviewSteps.length })
              }
            </Text>
          </Group>
          <StepList steps={reviewSteps} />
        </Paper>
      )}

      {/* Results — grouped by course */}
      {results.length > 0 && (
        <>
          <Divider
            label={t('rev.results_divider', { count: results.length, us: results.length !== 1 ? 's' : '', courses: groupedResults.length, cs: groupedResults.length !== 1 ? 's' : '' })}
            labelPosition="center"
          />
          <Stack gap="lg">
            {groupedResults.map(([sn, courseResults]) => {
              const courseMeta     = courses.find(c => c.shortname === sn)
              const hasValidResult = courseResults.some(r => !r.error && r.sections?.length)
              const isRegenerating = regenerating[sn]
              const doneVer        = regenDone[sn]
              const agentLabels    = [...new Set(courseResults.map(r => r.agent_label))]
              const findings       = collectFindings(courseResults)
              const findingOptions = findings.map(f => ({ value: f.id, label: f.line }))
              const selectedIds    = selectedFindings[sn] ?? []
              const hasSelected    = selectedIds.length > 0

              return (
                <Box key={sn}>
                  {/* Course row header */}
                  <Paper
                    withBorder p="sm" radius="md" mb="xs"
                    style={{ borderLeft: '3px solid var(--mantine-color-violet-5)' }}
                  >
                    <Group justify="space-between" wrap="nowrap">
                      <Stack gap={2}>
                        <Group gap="xs">
                          <Text fw={700} size="sm">{sn}</Text>
                          {agentLabels.map(l => (
                            <Badge key={l} size="xs" variant="outline"
                              color={courseResults.find(r => r.agent_label === l)?.agent_color ?? 'gray'}>
                              {l}
                            </Badge>
                          ))}
                        </Group>
                        {courseMeta?.fullname && (
                          <Text size="xs" c="dimmed">{courseMeta.fullname}</Text>
                        )}
                      </Stack>

                      <Group gap="xs" style={{ flexShrink: 0 }}>
                        {doneVer ? (
                          <Badge color="green" variant="filled" leftSection={<IconWand size={11} />}>
                            {t('rev.regenerated', { n: doneVer.version_num })}
                          </Badge>
                        ) : (
                          <Group gap="xs">
                            <Button
                              size="xs"
                              variant="light"
                              color="violet"
                              leftSection={isRegenerating ? <Loader size={10} /> : <IconWand size={13} />}
                              disabled={!hasValidResult || isRegenerating || !hasSelected}
                              loading={isRegenerating}
                              onClick={() => applyFeedback(sn, courseResults, selectedIds)}
                            >
                              {isRegenerating ? t('rev.regenerating') : t('rev.execute_selected')}
                            </Button>
                            <Button
                              size="xs"
                              variant="gradient"
                              gradient={{ from: 'violet', to: 'teal', deg: 135 }}
                              leftSection={isRegenerating ? <Loader size={10} color="white" /> : <IconWand size={13} />}
                              disabled={!hasValidResult || isRegenerating}
                              loading={isRegenerating}
                              onClick={() => applyFeedback(sn, courseResults)}
                            >
                              {isRegenerating ? t('rev.regenerating') : t('rev.execute_all')}
                            </Button>
                          </Group>
                        )}
                      </Group>
                    </Group>

                    {!doneVer && findings.length > 0 && (
                      <Box mt="sm">
                        <Text size="xs" c="dimmed" mb={4}>{t('rev.findings_pick')}</Text>
                        <MultiSelect
                          data={findingOptions}
                          value={selectedIds}
                          onChange={vals => setSelectedFindings(prev => ({ ...prev, [sn]: vals }))}
                          placeholder={t('rev.findings_pick_ph', { count: findings.length })}
                          searchable
                          clearable
                          size="xs"
                          maxDropdownHeight={220}
                        />
                      </Box>
                    )}

                    {regenSteps[sn]?.length > 0 && (
                      <Box mt="sm">
                        <StepList steps={regenSteps[sn]} />
                      </Box>
                    )}
                  </Paper>

                  {/* Result cards for this course */}
                  <SimpleGrid cols={2} spacing="sm">
                    {courseResults.map((r, idx) => (
                      <ResultCard key={`${r.shortname}-${r.agent_label}-${idx}`} result={r} />
                    ))}
                  </SimpleGrid>
                </Box>
              )
            })}
          </Stack>
        </>
      )}

      {/* Review History */}
      {history.length > 0 && (
        <>
          <Divider />
          <Box>
            <Group
              gap="xs"
              mb="sm"
              style={{ cursor: 'pointer', userSelect: 'none' }}
              onClick={() => setHistoryOpen(o => !o)}
            >
              <ThemeIcon size="sm" color="gray" variant="light">
                <IconHistory size={14} />
              </ThemeIcon>
              <Text size="sm" fw={600} c="dimmed">{t('rev.history')}</Text>
              <Badge size="xs" variant="outline" color="gray">{history.length}</Badge>
              {historyOpen ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}
            </Group>

            <Collapse in={historyOpen}>
              <ScrollArea>
                <Table withTableBorder withColumnBorders fz="xs">
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>{t('rev.hist_course')}</Table.Th>
                      <Table.Th>{t('rev.hist_agent')}</Table.Th>
                      <Table.Th>{t('rev.hist_version')}</Table.Th>
                      <Table.Th>{t('rev.hist_verdict')}</Table.Th>
                      <Table.Th>{t('rev.hist_score')}</Table.Th>
                      <Table.Th>{t('rev.hist_date')}</Table.Th>
                      <Table.Th w={32} />
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {history.map(r => (
                      <Table.Tr key={r.id}>
                        <Table.Td fw={600}>
                          <Group gap={6} wrap="nowrap">
                            {r.shortname}
                            {onLoadCourse && (
                              <Tooltip label={t('rev.open_library')} withArrow>
                                <ActionIcon size="xs" variant="subtle" color="blue"
                                            onClick={() => onLoadCourse(r.shortname)}>
                                  <IconFolderOpen size={12} />
                                </ActionIcon>
                              </Tooltip>
                            )}
                            <Tooltip label={t('rev.set_review')} withArrow>
                              <ActionIcon size="xs" variant="subtle" color="violet"
                                          onClick={() => jumpToReview(r.shortname)}>
                                <IconReload size={12} />
                              </ActionIcon>
                            </Tooltip>
                          </Group>
                        </Table.Td>
                        <Table.Td>
                          <Badge size="xs" color={r.agent_color || 'gray'} variant="dot">
                            {r.agent_label || r.agent_id || '—'}
                          </Badge>
                        </Table.Td>
                        <Table.Td c="dimmed">{r.version_num != null ? `v${r.version_num}` : '—'}</Table.Td>
                        <Table.Td>
                          {r.error
                            ? <Badge size="xs" color="red">Error</Badge>
                            : <Badge size="xs" color={overallColor(r.overall ?? '')} variant="light">
                                {r.overall ?? '—'}
                              </Badge>
                          }
                        </Table.Td>
                        <Table.Td c={r.score != null ? scoreColor(r.score) : 'dimmed'}>
                          {r.score != null ? `${r.score}/100` : '—'}
                        </Table.Td>
                        <Table.Td c="dimmed">
                          {new Date(r.run_at).toLocaleDateString(undefined, {
                            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
                          })}
                        </Table.Td>
                        <Table.Td>
                          <ActionIcon
                            size="xs" variant="subtle" color="red"
                            onClick={async () => {
                              const course = courses.find(c => c.shortname === r.shortname)
                              await api.courses.deleteReview(r.shortname, r.id).catch(() => {})
                              setHistory(prev => prev.filter(h => h.id !== r.id))
                            }}
                          >
                            <IconTrash size={12} />
                          </ActionIcon>
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </ScrollArea>
            </Collapse>
          </Box>
        </>
      )}

    </Stack>
  )
}
