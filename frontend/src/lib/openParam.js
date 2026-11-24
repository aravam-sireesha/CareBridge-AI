/** The `?open=ID` parameter of the current address (a link from an alert opens that record). Read straight from the address bar, so it works
 *  with BrowserRouter and without any router context. */
export function openParam() {
  try { return new URLSearchParams(window.location.search).get('open') } catch { return null }
}
