# API & Service Configuration

Put all secrets in `backend/.env` (never commit it; start from `.env.example`). The frontend must hold no private keys.

| Purpose | Variables | Needed for |
|---|---|---|
| Core | `DATABASE_URL`, `SECRET_KEY` | Required |
| E-mail / OTP delivery | `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_STARTTLS` | Password reset, e-mail verification |
| OTP rules | `OTP_LENGTH`, `OTP_TTL_MINUTES`, `OTP_MAX_ATTEMPTS`, `OTP_RESEND_COOLDOWN_SECONDS`, `OTP_MAX_PER_HOUR` | Optional tuning |
| LLM | `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_FAST_MODEL` | Optional; assistant works from retrieval without it |
| SMS, worldwide | `SMS_PROVIDER=twilio`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM` | Phone verification |
| SMS, India (DLT) | `SMS_PROVIDER=msg91`, `MSG91_AUTH_KEY`, `MSG91_TEMPLATE_ID`, `SMS_SENDER_ID`, `DLT_ENTITY_ID`, `DLT_TEMPLATE_ID` | Phone verification for +91 numbers |
| Phone verification switch | `REQUIRE_PHONE_VERIFICATION=true` | Ignored (so nobody is locked out) unless SMS can really be delivered |
| Local testing | `APP_ENV=development`, `SMS_DELIVERY=console` | Prints the SMS code in the server window; refused in production |
| Maps | none today | OpenStreetMap tiles need no key; MapTiler/Google need a restricted browser key |

No key is bundled or assumed valid; nothing here has been tested against a live provider.

## India SMS setup (DLT) - what you must obtain
1. Register your organization as a principal entity on a DLT portal of a telecom operator (Jio, Airtel, Vi or BSNL). You receive the **entity ID** (`DLT_ENTITY_ID`).
2. Register a **sender/header** (6 letters) -> `SMS_SENDER_ID`.
3. Register an OTP **content template** with two variables, e.g. "Your CareBridge code is {#var#}. It expires in {#var#} minutes. Do not share it." -> **template ID** (`DLT_TEMPLATE_ID`). Operators must approve it.
4. Create an MSG91 account, add that template there using its variable syntax, link the sender, and copy the MSG91 template/flow id -> `MSG91_TEMPLATE_ID`, and your account key -> `MSG91_AUTH_KEY`.
5. Put all six values in `backend/.env` and set `REQUIRE_PHONE_VERIFICATION=true`.
The server sends `VAR1` = the code and `VAR2` = minutes to the MSG91 flow API (`https://control.msg91.com/api/v5/flow/`, header `authkey`), following MSG91's published flow API. The payload was checked against their documentation but never sent to a live account: test with your own number first. Nothing is sent to a +91 number until the sender and both DLT ids are set.
