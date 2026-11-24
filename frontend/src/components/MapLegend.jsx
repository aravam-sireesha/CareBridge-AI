import React from 'react'
import { LEGEND_COLOURS } from '../lib/mapLayers.js'

/** A colour key under a map. items = [{ kind, label }]. The colours are explained in words too, so colour is never the only cue. */
export default function MapLegend({ items }) {
  return (
    <ul className="cbm-legend" aria-label="Map key">
      {items.map((i) => <li key={i.kind}><span className="cbm-swatch" style={{ background: LEGEND_COLOURS[i.kind] || '#0F766E' }} aria-hidden="true" />{i.label}</li>)}
    </ul>
  )
}
