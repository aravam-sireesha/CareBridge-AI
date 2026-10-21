import React, { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api/client.js'
import { useAuth } from '../context/AuthContext.jsx'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import Layout from '../components/Layout.jsx'
import { Button, CardSkeleton, EmptyState, ErrorState, Field, Modal, PageHeader, Pill, formatDate } from '../components/ui.jsx'
import StatusBadge from '../components/StatusBadge.jsx'
import { IconBriefcase, IconCheck, IconEdit, IconSpark, IconX } from '../components/icons.jsx'

const CAREERS = ['Tech', 'Finance', 'Business', 'Design', 'Healthcare']
const BLANK = { Age: 18, Gender: 'Female', Field_of_Study: 'Science', Year_of_Study: 1, University_Location: 'Region A', GPA: 3, Relevant_Coursework: 0, Prior_Employment: 0, Employment_Type: 'Internship', Entrepreneurial_Experience: 0, Startup_Participation: 0, Career_Interests: 'Tech', Entrepreneurial_Aspirations: 'Medium' }
const YESNO = ['Relevant_Coursework', 'Prior_Employment', 'Entrepreneurial_Experience', 'Startup_Participation']
const LABELS = { Relevant_Coursework: 'Relevant coursework', Prior_Employment: 'Prior employment', Entrepreneurial_Experience: 'Entrepreneurial experience', Startup_Participation: 'Startup participation' }

function RecommendationCard({ rec, canDecide, onSaved }) {
  const toast = useToast()
  const [chosen, setChosen] = useState(rec.candidates[0])
  const [busy, setBusy] = useState(null)
  const fb = rec.feedback
  const send = async (decision) => {
    setBusy(decision)
    try {
      await api.careerFeedback(rec.recommendation_id, { decision, chosen_career: decision === 'rejected' ? undefined : chosen })
      toast.success('Decision saved to the database.'); onSaved()
    } catch (e) { toast.error(e.message) } finally { setBusy(null) }
  }
  return (
    <div className="card animate-rise-in p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-medium text-ink-muted">Generated {formatDate(rec.created_at)} · model {rec.model_version}</p>
        {fb ? <StatusBadge status={fb.decision} /> : <StatusBadge status="suggested" />}
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        {rec.candidates.map((c, i) => {
          const selected = fb ? fb.chosen_career === c : chosen === c
          return (
            <button key={c} type="button" disabled={!canDecide || !!fb} onClick={() => setChosen(c)} aria-pressed={selected}
              className={`rounded-2xl border-2 p-4 text-left transition ${selected ? 'border-teal-500 bg-teal-50/60' : 'border-line bg-white'} ${canDecide && !fb ? 'hover:border-teal-300' : ''}`}>
              <span className="text-[11px] font-semibold text-ink-muted">Suggestion {i + 1}</span>
              <span className="mt-1 flex items-center justify-between font-display text-lg font-semibold text-ink">{c}{selected && <IconCheck className="h-5 w-5 text-teal-600" />}</span>
            </button>
          )
        })}
      </div>
      {fb?.comment && <p className="mt-3 rounded-xl bg-bg p-3 text-sm text-ink-muted">“{fb.comment}”</p>}
      {canDecide && !fb && (
        <div className="mt-4 flex flex-wrap justify-end gap-2">
          <Button variant="danger" loading={busy === 'rejected'} disabled={!!busy} onClick={() => send('rejected')}><IconX className="h-4 w-4" /> Reject all</Button>
          <Button variant="soft" loading={busy === 'modified'} disabled={!!busy} onClick={() => send('modified')}>Choose “{chosen}” instead</Button>
          <Button loading={busy === 'accepted'} disabled={!!busy} onClick={() => send('accepted')}><IconCheck className="h-4 w-4" /> Accept “{chosen}”</Button>
        </div>
      )}
    </div>
  )
}

export default function CareerGuidance() {
  const { user } = useAuth()
  const toast = useToast()
  const isAdmin = user.role === 'admin'
  const [params, setParams] = useSearchParams()
  const children = useAsync(() => api.listChildren(), [])
  const [childId, setChildId] = useState(params.get('child') || '')
  const [profileOpen, setProfileOpen] = useState(false)
  const [form, setForm] = useState(BLANK)
  const [saving, setSaving] = useState(false)
  const [generating, setGenerating] = useState(false)
  const profile = useAsync(async () => { if (!childId) return null; try { return await api.getCareerProfile(childId) } catch (e) { if (e.status === 404) return null; throw e } }, [childId])
  const recs = useAsync(() => (childId ? api.listRecommendations(childId) : Promise.resolve([])), [childId])

  useEffect(() => { if (!childId && children.data?.length) setChildId(String(children.data[0].id)) }, [children.data, childId])
  useEffect(() => { if (childId) setParams({ child: childId }, { replace: true }) }, [childId, setParams])
  useEffect(() => { if (profile.data?.profile_data) setForm({ ...BLANK, ...profile.data.profile_data }) }, [profile.data])

  const set = (k, numeric) => (e) => setForm((f) => ({ ...f, [k]: numeric ? Number(e.target.value) : e.target.value }))
  const saveProfile = async (e) => {
    e.preventDefault(); setSaving(true)
    try { await api.saveCareerProfile(childId, form); toast.success('Career profile saved.'); setProfileOpen(false); profile.reload({ silent: true }) }
    catch (err) { toast.error(err.message) } finally { setSaving(false) }
  }
  const generate = async () => {
    setGenerating(true)
    try { await api.recommendCareer(childId); toast.success('Three career paths suggested.'); recs.reload({ silent: true }) }
    catch (err) { toast.error(err.message) } finally { setGenerating(false) }
  }

  const hasProfile = !!profile.data
  return (
    <Layout title="Career guidance">
      <PageHeader icon={IconBriefcase} tone="violet" title="Career guidance" subtitle="Three suggested career paths per child. They are a starting point for discussion, never a verdict." />
      {children.error ? <ErrorState message={children.error} onRetry={children.reload} /> : children.loading ? <CardSkeleton rows={2} /> : !children.data?.length ? (
        <EmptyState icon={IconBriefcase} title="Add a child first" text="Career guidance works from a child's profile." action={<Link to="/children" className="btn-primary">Go to children</Link>} />
      ) : (
        <>
          <div className="card mb-5 flex flex-wrap items-end gap-3 p-4">
            <Field label="Child" className="min-w-[14rem] flex-1">
              <select className="field" value={childId} onChange={(e) => setChildId(e.target.value)}>{children.data.map((c) => <option key={c.id} value={c.id}>#{c.id} · {c.age ?? '?'} yrs · {c.interests || 'no interests recorded'}</option>)}</select>
            </Field>
            {isAdmin && <Button variant="ghost" onClick={() => setProfileOpen(true)}><IconEdit className="h-4 w-4" /> {hasProfile ? 'Edit' : 'Create'} career profile</Button>}
            {isAdmin && <Button loading={generating} disabled={!hasProfile} onClick={generate}><IconSpark className="h-4 w-4" /> Generate recommendations</Button>}
          </div>

          {!hasProfile && !profile.loading && <div className="mb-5 rounded-2xl bg-amber-50 p-4 text-sm text-amber-800 ring-1 ring-amber-100">This child has no career profile yet. {isAdmin ? 'Create one to generate recommendations.' : 'An administrator needs to create it.'}</div>}
          {hasProfile && <div className="mb-5 flex flex-wrap gap-2"><Pill tone="violet">Interest: {profile.data.profile_data.Career_Interests}</Pill><Pill tone="sky">Field: {profile.data.profile_data.Field_of_Study}</Pill><Pill tone="teal">Aspirations: {profile.data.profile_data.Entrepreneurial_Aspirations}</Pill></div>}

          {recs.error ? <ErrorState message={recs.error} onRetry={recs.reload} /> : recs.loading ? <CardSkeleton rows={2} /> : !recs.data?.length ? (
            <EmptyState icon={IconSpark} title="No recommendations yet" text={isAdmin ? 'Create the profile, then press “Generate recommendations”.' : 'An administrator can generate recommendations for this child.'} />
          ) : <div className="space-y-4">{recs.data.map((r) => <RecommendationCard key={r.recommendation_id} rec={r} canDecide={isAdmin} onSaved={() => recs.reload({ silent: true })} />)}</div>}
          <p className="mt-6 text-xs text-ink-muted">The model was trained on a synthetic proxy dataset, so its suggestions are not validated predictions. Administrator decisions are stored and will be used to evaluate it properly.</p>
        </>
      )}

      <Modal open={profileOpen} onClose={() => setProfileOpen(false)} wide title="Career profile" subtitle="Model inputs stored with the child's record.">
        <form onSubmit={saveProfile} className="grid gap-4 sm:grid-cols-2">
          <Field label="Age"><input className="field" type="number" min="14" max="100" required value={form.Age} onChange={set('Age', true)} /></Field>
          <Field label="Gender"><select className="field" value={form.Gender} onChange={set('Gender')}>{['Female', 'Male', 'Other'].map((o) => <option key={o}>{o}</option>)}</select></Field>
          <Field label="Field of study"><select className="field" value={form.Field_of_Study} onChange={set('Field_of_Study')}>{['Arts', 'Business', 'Engineering', 'Law', 'Science'].map((o) => <option key={o}>{o}</option>)}</select></Field>
          <Field label="Year of study"><input className="field" type="number" min="0" max="20" required value={form.Year_of_Study} onChange={set('Year_of_Study', true)} /></Field>
          <Field label="Location"><select className="field" value={form.University_Location} onChange={set('University_Location')}>{['Region A', 'Region B', 'Region C'].map((o) => <option key={o}>{o}</option>)}</select></Field>
          <Field label="GPA (0–4)"><input className="field" type="number" step="0.01" min="0" max="4" required value={form.GPA} onChange={set('GPA', true)} /></Field>
          <Field label="Employment type"><select className="field" value={form.Employment_Type} onChange={set('Employment_Type')}>{['Internship', 'Part-time', 'Full-time'].map((o) => <option key={o}>{o}</option>)}</select></Field>
          <Field label="Stated career interest"><select className="field" value={form.Career_Interests} onChange={set('Career_Interests')}>{CAREERS.map((o) => <option key={o}>{o}</option>)}</select></Field>
          <Field label="Entrepreneurial aspirations"><select className="field" value={form.Entrepreneurial_Aspirations} onChange={set('Entrepreneurial_Aspirations')}>{['Low', 'Medium', 'High'].map((o) => <option key={o}>{o}</option>)}</select></Field>
          <div />
          {YESNO.map((k) => <Field key={k} label={LABELS[k]}><select className="field" value={form[k]} onChange={set(k, true)}><option value={0}>No</option><option value={1}>Yes</option></select></Field>)}
          <div className="flex justify-end gap-2 pt-2 sm:col-span-2"><Button type="button" variant="ghost" onClick={() => setProfileOpen(false)}>Cancel</Button><Button type="submit" loading={saving}>Save profile</Button></div>
        </form>
      </Modal>
    </Layout>
  )
}
