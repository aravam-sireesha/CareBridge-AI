import React from 'react'
import Layout from '../components/Layout.jsx'
import ResourceInventory from '../components/ResourceInventory.jsx'
import { PageHeader } from '../components/ui.jsx'
import { IconDatabase } from '../components/icons.jsx'

export default function Resources() {
  return (
    <Layout title="Resources">
      <PageHeader icon={IconDatabase} tone="green" title="Our resources" subtitle="Materials, services and funds your organization can give. Administrators match them to children's needs." />
      <ResourceInventory />
    </Layout>
  )
}
