import React, { useState } from 'react'
import { api } from '../api/client.js'
import { useToast } from '../context/ToastContext.jsx'
import { Button, Field, Modal } from './ui.jsx'

/** Add an entry to the RAG knowledge base. It is embedded on save so the assistant can find it. */
export default function KnowledgeModal({ open, onClose, onSaved }) {
  const toast = useToast()
  const [f, setF] = useState({ title: '', content: '', source: '' })
  const [saving, setSaving] = useState(false)
  const submit = async (e) => {
    e.preventDefault(); setSaving(true)
    try {
      await api.addKnowledge({ title: f.title.trim(), content: f.content.trim(), source: f.source.trim() || null })
      toast.success('Knowledge saved and indexed for the assistant.')
      setF({ title: '', content: '', source: '' }); onSaved?.(); onClose()
    } catch (err) { toast.error(err.message) } finally { setSaving(false) }
  }
  return (
    <Modal open={open} onClose={onClose} wide title="Add knowledge" subtitle="Saved to the knowledge_base table and embedded so the assistant can retrieve it.">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Title"><input className="field" required maxLength={300} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} placeholder="Volunteer background checks" /></Field>
        <Field label="Content"><textarea className="field min-h-[140px]" required maxLength={20000} value={f.content} onChange={(e) => setF({ ...f, content: e.target.value })} placeholder="Write the policy or guidance the assistant should know…" /></Field>
        <Field label="Source"><input className="field" maxLength={500} value={f.source} onChange={(e) => setF({ ...f, source: e.target.value })} placeholder="Policy manual, section 4" /></Field>
        <div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={onClose}>Cancel</Button><Button type="submit" loading={saving}>Save knowledge</Button></div>
      </form>
    </Modal>
  )
}
