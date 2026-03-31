import { useState } from 'react'
import Layout from './components/Layout'
import PipelineControls from './components/PipelineControls'
import PolicyList from './components/PolicyList'
import StatusBar from './components/StatusBar'
import PolicyDetail from './components/PolicyDetail'
import { usePolicies } from './hooks/usePolicies'

export default function App() {
  const { policies, stats, search, setSearch, loading, refresh } = usePolicies()
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const handleJobStarted = () => {
    // Refresh data after a short delay to pick up new state
    refresh()
    // Also refresh again after a longer delay in case processing is still going
    setTimeout(refresh, 5000)
    setTimeout(refresh, 15000)
  }

  return (
    <Layout
      left={
        <>
          <PipelineControls onJobStarted={handleJobStarted} />
          <PolicyList
            policies={policies}
            search={search}
            onSearchChange={setSearch}
            selectedId={selectedId}
            onSelect={setSelectedId}
            loading={loading}
          />
          <StatusBar stats={stats} />
        </>
      }
      right={
        <PolicyDetail policyId={selectedId} />
      }
    />
  )
}
