import React from 'react'
import { useSearchParams } from 'react-router-dom'
import Layout, { EmbeddedContext } from '../components/Layout.jsx'
import AdminDonors from './AdminDonors.jsx'
import AdminVolunteers from './AdminVolunteers.jsx'
import { PageHeader, Tabs } from '../components/ui.jsx'
import { IconDonations, IconPeople } from '../components/icons.jsx'

/** One Admin page, two clearly separate tabs. Each tab is the existing donor / volunteer manager, so columns,
 *  permissions and actions stay role-specific and nothing is duplicated. */
export default function AdminPeople() {
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') === 'volunteers' ? 'volunteers' : 'donors'
  return (
    <Layout title="Volunteers & Donors">
      <PageHeader icon={IconPeople} title="Volunteers & Donors" subtitle="Manage the people who give and the people who serve, in one place." />
      <Tabs tabs={[{ key: 'donors', label: 'Donors', icon: IconDonations }, { key: 'volunteers', label: 'Volunteers', icon: IconPeople }]} value={tab} onChange={(k) => setParams({ tab: k }, { replace: true })} />
      <EmbeddedContext.Provider value>
        {tab === 'donors' ? <AdminDonors key="d" /> : <AdminVolunteers key="v" />}
      </EmbeddedContext.Provider>
    </Layout>
  )
}
