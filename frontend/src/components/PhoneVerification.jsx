import React from 'react'
import { api } from '../api/client.js'
import CodeVerification from './CodeVerification.jsx'

/** Confirms a new account's mobile number with a code sent by SMS. The account is identified by its e-mail address, never by phone. */
export default function PhoneVerification({ email, onVerified }) {
  return (
    <CodeVerification identity={email} request={api.requestPhoneVerification} confirm={api.confirmPhoneVerification} onVerified={onVerified}
      sentLine={(length) => <>If this account is waiting for mobile verification, a {length}-digit code is on its way by text message. The code works once.</>}
      buttonLabel="Verify mobile number" helpText="Text messages can take a minute to arrive."
      unavailableNote="Text-message verification is not available right now. Please try again later or contact a CareBridge administrator." />
  )
}
