import React from 'react'
import { api } from '../api/client.js'
import CodeVerification from './CodeVerification.jsx'

/** Confirms a new account's e-mail address with a one-time code. Used right after sign-up and from /verify-email. */
export default function EmailVerification({ email, onVerified }) {
  return (
    <CodeVerification identity={email} request={api.requestEmailVerification} confirm={api.confirmEmailVerification} onVerified={onVerified}
      sentLine={(length) => <>If <strong className="text-ink">{email}</strong> is waiting to be verified, a {length}-digit code is on its way. The code works once.</>}
      buttonLabel="Verify email" helpText="Not there? Check your spam folder."
      unavailableNote="You will be able to sign in as soon as an administrator has verified your account." />
  )
}
