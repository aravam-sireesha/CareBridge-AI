import { useEffect } from 'react'
import { useAuth } from '../context/AuthContext.jsx'
import { tokenStore } from '../api/client.js'
import { connectLive, disconnectLive } from '../lib/liveEvents.js'

/** Keeps ONE live-event connection open while someone is signed in, and closes it when they sign out or switch account.
 *  Renders nothing. Components listen with useLiveEvent(); without a connection they fall back to their own slower polling. */
export default function LiveConnection() {
  const { user } = useAuth()
  const userId = user?.id ?? null
  useEffect(() => {
    if (userId == null) return undefined
    connectLive(() => tokenStore.get())
    return () => disconnectLive()
  }, [userId])
  return null
}
