import React, { useCallback, useEffect, useState } from 'react'
import { Button, EmptyState, ErrorState, Field, Modal, Pill, Spinner, formatDate } from './ui.jsx'
import StatusBadge from './StatusBadge.jsx'
import { IconBriefcase, IconCheck, IconEdit, IconSpark, IconX } from './icons.jsx'
import { useAuth } from '../context/AuthContext.jsx'
import { useToast } from '../context/ToastContext.jsx'
import { api } from '../api/client.js'

const OPTIONS = {
  Gender: ['Female', 'Male', 'Other'],
  Field_of_Study: ['Arts', 'Business', 'Engineering', 'Law', 'Science'],
  University_Location: ['Region A', 'Region B', 'Region C'],
  Employment_Type: ['Internship', 'Part-time', 'Full-time'],
  Career_Interests: ['Tech', 'Finance', 'Business', 'Design', 'Healthcare'],
  Entrepreneurial_Aspirations: ['Low', 'Medium', 'High']
}
const YES_NO = [['0', 'No'], ['1', 'Yes']]

const emptyProfile = (age) => ({
  Age: String(Math.max(Number(age) || 14, 14)), Gender: 'Female', Field_of_Study: 'Science', Year_of_Study: '1', University_Location: 'Region A',
  GPA: '3.0', Relevant_Coursework: '0', Prior_Employment: '0', Employment_Type: 'Internship', Entrepreneurial_Experience: '0',
  Startup_Participation: '0', Career_Interests: 'Tech', Entrepreneurial_Aspirations: 'Medium'
})

function Select({ label, k, form, set, options }) {
  return (
    <Field label={label}>
      <select className="field" value={form[k]} onChange={set(k)}>
        {options.map((o) => (Array.isArray(o) ? <option key={o[0]} value={o[0]}>{o[1]}</option> : <option key={o} value={o}>{o}</option>))}
      </select>
    </Field>
  )
}

function ProfileModal({ open, onClose, child, existing, onSaved }) {
  const toast = useToast()
  const [form, setForm] = useState(emptyProfile(child.age))
  const [saving, setSaving] = useState(false)
  useEffect(() => { if (open) setForm(existing ? Object.fromEntries(Object.entries(existing).map(([k, v]) => [k, String(v)])) : emptyProfile(child.age)) }, [open, existing, child.age])
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  const submit = async (e) => {
    e.preventDefault(); setSaving(true)
    try {
      await api.saveCareerProfile(child.id, {
        Age: Number(form.Age), Gender: form.Gender, Field_of_Study: form.Field_of_Study, Year_of_Study: Number(form.Year_of_Study),
        University_Location: form.University_Location, GPA: Number(form.GPA), Relevant_Coursework: Number(form.Relevant_Coursework),
        Prior_Employment: Number(form.Prior_Employment), Employment_Type: form.Employment_Type,
        Entrepreneurial_Experience: Number(form.Entrepreneurial_Experience), Startup_Participation: Number(form.Startup_Participation),
        Career_Interests: form.Career_Interests, Entrepreneurial_Aspirations: form.Entrepreneurial_Aspirations
      })
      toast.success('Career profile saved to the database.')
      onSaved(); onClose()
    } catch (err) { toast.error(err.message) } finally { setSaving(false) }
  }

  return (
    <Modal open={open} onClose={onClose} wide title="Career profile" subtitle="The recommender was trained on a student dataset, so these are the fields it understands.">
      <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
        <Field label="Age" hint="The model accepts ages 14 and above"><input className="field" type="number" min="14" max="100" required value={form.Age} onChange={set('Age')} /></Field>
        <Select label="Gender" k="Gender" form={form} set={set} options={OPTIONS.Gender} />
        <Select label="Field of study" k="Field_of_Study" form={form} set={set} options={OPTIONS.Field_of_Study} />
        <Field label="Year of study"><input className="field" type="number" min="0" max="20" required value={form.Year_of_Study} onChange={set('Year_of_Study')} /></Field>
        <Select label="Location" k="University_Location" form={form} set={set} options={OPTIONS.University_Location} />
        <Field label="GPA (0 – 4)"><input className="field" type="number" step="0.01" min="0" max="4" required value={form.GPA} onChange={set('GPA')} /></Field>
        <Select label="Relevant coursework" k="Relevant_Coursework" form={form} set={set} options={YES_NO} />
        <Select label="Prior employment" k="Prior_Employment" form={form} set={set} options={YES_NO} />
        <Select label="Employment type" k="Employment_Type" form={form} set={set} options={OPTIONS.Employment_Type} />
        <Select label="Entrepreneurial experience" k="Entrepreneurial_Experience" form={form} set={set} options={YES_NO} />
        <Select label="Startup participation" k="Startup_Participation" form={form} set={set} options={YES_NO} />
        <Select label="Main career interest" k="Career_Interests" form={form} set={set} options={OPTIONS.Career_Interests} />
        <Select label="Entrepreneurial aspirations" k="Entrepreneurial_Aspirations" form={form} set={set} options={OPTIONS.Entrepreneurial_Aspirations} />
        <div className="flex justify-end gap-2 sm:col-span-2"><Button type="button" variant="ghost" onClick={onClose}>Cancel</Button><Button type="submit" loading={saving}>Save profile</Button></div>
      </form>
    </Modal>
  )
}

function FeedbackForm({ rec, onDone }) {
  const toast = useToast()
  const [chosen, setChosen] = useState(rec.candidates[0])
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState('')
  const send = async (decision) => {
    setBusy(decision)
    try {
      await api.careerFeedback(rec.recommendation_id, { decision, chosen_career: decision === 'rejected' ? undefined : chosen, comment: comment || undefined })
      toast.success('Decision stored. It will inform future evaluation.')
      onDone()
    } catch (err) { toast.error(err.message) } finally { setBusy('') }
  }
  return (
    <div className="mt-4 rounded-xl bg-teal-50/60 p-4">
      <p className="text-[13px] font-semibold text-ink">Your decision</p>
      <div className="mt-2 grid gap-3 sm:grid-cols-2">
        <Field label="Career to record"><select className="field" value={chosen} onChange={(e) => setChosen(e.target.value)}>{[...rec.candidates, 'Other'].map((c) => <option key={c}>{c}</option>)}</select></Field>
        <Field label="Comment (optional)"><input className="field" value={comment} maxLength={2000} onChange={(e) => setComment(e.target.value)} placeholder="Why?" /></Field>
      </div>
      <div className="mt-3 flex flex-wrap justify-end gap-2">
        <Button variant="danger" loading={busy === 'rejected'} disabled={!!busy} onClick={() => send('rejected')}><IconX className="h-4 w-4" />Reject</Button>
        <Button variant="ghost" loading={busy === 'modified'} disabled={!!busy} onClick={() => send('modified')}>Modify</Button>
        <Button loading={busy === 'accepted'} disabled={!!busy} onClick={() => send('accepted')}><IconCheck className="h-4 w-4" />Accept</Button>
      </div>
    </div>
  )
}

export default function CareerPanel({ child }) {
  const { user } = useAuth()
  const toast = useToast()
  const isAdmin = user.role === 'admin'
  const [profile, setProfile] = useState(undefined) // undefined = loading, null = none
  const [recs, setRecs] = useState([])
  const [error, setError] = useState('')
  const [edit, setEdit] = useState(false)
  const [running, setRunning] = useState(false)

  const load = useCallback(async () => {
    setError('')
    try {
      const [p, r] = await Promise.all([
        api.getCareerProfile(child.id).then((x) => x.profile_data).catch((e) => { if (e.status === 404) return null; throw e }),
        api.listRecommendations(child.id)
      ])
      setProfile(p); setRecs(r)
    } catch (e) { setError(e.message) }
  }, [child.id])
  useEffect(() => { setProfile(undefined); load() }, [load])

  const generate = async () => {
    setRunning(true)
    try { await api.recommendCareer(child.id); toast.success('Three career suggestions generated.'); await load() }
    catch (e) { toast.error(e.message) } finally { setRunning(false) }
  }

  if (error) return <ErrorState message={error} onRetry={load} />
  if (profile === undefined) return <div className="flex justify-center py-12 text-teal-600"><Spinner className="h-7 w-7" /></div>

  return (
    <div className="space-y-5">
      <div className="card p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3"><span className="grid h-11 w-11 place-items-center rounded-xl bg-violet-50 text-violet-600"><IconBriefcase /></span><div><p className="font-display font-semibold text-ink">Career profile</p><p className="text-[13px] text-ink-muted">{profile ? 'Saved. This is what the recommender reads.' : 'No career profile yet.'}</p></div></div>
          {isAdmin && <Button variant={profile ? 'ghost' : 'primary'} onClick={() => setEdit(true)}><IconEdit className="h-4 w-4" />{profile ? 'Edit profile' : 'Create profile'}</Button>}
        </div>
        {profile && <div className="mt-4 flex flex-wrap gap-2">{['Career_Interests', 'Field_of_Study', 'GPA', 'Entrepreneurial_Aspirations'].map((k) => <Pill key={k} tone="violet">{k.replace(/_/g, ' ')}: {String(profile[k])}</Pill>)}</div>}
        {!profile && !isAdmin && <p className="mt-3 text-sm text-ink-muted">An administrator needs to create the career profile before suggestions can be generated.</p>}
      </div>

      <div className="card p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div><p className="font-display font-semibold text-ink">AI career suggestions</p><p className="text-[13px] text-ink-muted">Starting points for a conversation — not validated predictions.</p></div>
          {isAdmin && <Button onClick={generate} loading={running} disabled={!profile}><IconSpark className="h-4 w-4" />Get recommendations</Button>}
        </div>
        {recs.length === 0 ? <div className="mt-4"><EmptyState icon={IconBriefcase} title="No suggestions yet" text={profile ? (isAdmin ? 'Press “Get recommendations” to generate three suggestions.' : 'An administrator can generate suggestions for this child.') : 'Create the career profile first.'} /></div> : (
          <ul className="mt-4 space-y-4">
            {recs.map((r) => (
              <li key={r.recommendation_id} className="rounded-2xl border border-line p-4">
                <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-xs text-ink-muted">{formatDate(r.created_at)} · model {r.model_version}</p>{r.feedback ? <StatusBadge status={r.feedback.decision} /> : <StatusBadge status="suggested" />}</div>
                <div className="mt-3 grid gap-3 sm:grid-cols-3">
                  {r.candidates.map((c, i) => (
                    <div key={c} className={`rounded-xl p-4 ${r.feedback?.chosen_career === c ? 'bg-green-50 ring-2 ring-green-400' : 'bg-gradient-to-br from-teal-50 to-sky-50'}`}>
                      <p className="text-xs font-semibold text-ink-muted">Suggestion {i + 1}</p><p className="mt-1 font-display text-lg font-semibold text-teal-800">{c}</p>
                    </div>
                  ))}
                </div>
                {r.feedback ? <p className="mt-3 text-sm text-ink-muted">Decision: <strong className="text-ink">{r.feedback.decision}</strong>{r.feedback.chosen_career ? ` → ${r.feedback.chosen_career}` : ''}{r.feedback.comment ? ` — “${r.feedback.comment}”` : ''}</p>
                  : isAdmin ? <FeedbackForm rec={r} onDone={load} /> : <p className="mt-3 text-xs text-ink-muted">Waiting for an administrator to review this suggestion.</p>}
              </li>
            ))}
          </ul>
        )}
      </div>
      {isAdmin && <ProfileModal open={edit} onClose={() => setEdit(false)} child={child} existing={profile} onSaved={load} />}
    </div>
  )
}
