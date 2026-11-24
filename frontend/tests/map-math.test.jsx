import { describe, it, expect } from 'vitest'
import { ageText, bearingLabel, fitZoom, formatDistance, haversineKm, navLinks, project, tileUrl, unproject, visibleTiles } from '../src/lib/mapMath.js'

const near = (a, b, eps) => Math.abs(a - b) <= eps

describe('projection', () => {
  it('round-trips latitude and longitude at every zoom', () => {
    for (const z of [3, 10, 16]) { const p = project(17.385, 78.4867, z); const q = unproject(p.x, p.y, z); expect(near(q.lat, 17.385, 1e-6) && near(q.lon, 78.4867, 1e-6)).toBe(true) }
  })
  it('puts the equator and the prime meridian at the middle of the world', () => { const p = project(0, 0, 2); expect(p.x).toBe(512); expect(near(p.y, 512, 1e-6)).toBe(true) })
  it('matches the standard OpenStreetMap tile numbers at zoom 10 (values from the OSM wiki formula, computed independently)', () => {
    for (const [lat, lon, tile] of [[17.385, 78.4867, [735, 461]], [51.5074, -0.1278, [511, 340]], [-33.8688, 151.2093, [942, 614]]]) {
      const p = project(lat, lon, 10); expect([Math.floor(p.x / 256), Math.floor(p.y / 256)]).toEqual(tile)
    }
  })
})
describe('fitting and tiles', () => {
  it('uses a street-level zoom for one point and zooms out until several points fit', () => {
    expect(fitZoom([{ lat: 17.38, lon: 78.48 }], 600, 300)).toBe(15)
    const far = fitZoom([{ lat: 17.38, lon: 78.48 }, { lat: 18.9, lon: 79.9 }], 600, 300)
    expect(far < 15 && far >= 3).toBe(true)
    expect(fitZoom([], 600, 300)).toBe(4)
  })
  it('covers the whole viewport with tiles and wraps around the date line', () => {
    const tiles = visibleTiles({ x: 1000, y: 1000 }, 5, 600, 300)
    expect(tiles.length >= 6).toBe(true)
    expect(tiles.every((t) => t.x >= 0 && t.x < 32 && t.y >= 0 && t.y < 32)).toBe(true)
    const wrap = visibleTiles({ x: 10, y: 4096 }, 5, 600, 300)
    expect(wrap.some((t) => t.x === 31)).toBe(true)
  })
  it('never asks for tiles above or below the world', () => {
    expect(visibleTiles({ x: 100, y: 5 }, 3, 600, 600).every((t) => t.y >= 0)).toBe(true)
  })
  it('fills the URL template', () => { expect(tileUrl('https://t.example/{z}/{x}/{y}.png', { z: 4, x: 5, y: 6 })).toBe('https://t.example/4/5/6.png') })
})
describe('distance, bearing and wording', () => {
  it('measures a known distance', () => { expect(near(haversineKm(51.5074, -0.1278, 48.8566, 2.3522), 343.5, 3.5)).toBe(true) })
  it('formats distance in plain words', () => {
    expect(formatDistance(0.004)).toBe('10 m'); expect(formatDistance(0.347)).toBe('350 m'); expect(formatDistance(2.46)).toBe('2.5 km'); expect(formatDistance(24.6)).toBe('25 km'); expect(formatDistance(NaN)).toBe('')
  })
  it('gives compass words', () => {
    expect(bearingLabel(17, 78, 18, 78)).toBe('north'); expect(bearingLabel(17, 78, 17, 79)).toBe('east'); expect(bearingLabel(17, 78, 16, 78)).toBe('south'); expect(bearingLabel(17, 78, 16, 77)).toBe('south-west')
  })
  it('describes how old a position is', () => {
    expect(ageText(null)).toBe('unknown'); expect(ageText(3)).toBe('just now'); expect(ageText(45)).toBe('45 s ago'); expect(ageText(300)).toBe('5 min ago'); expect(ageText(7300)).toBe('2 h ago')
  })
})
describe('navigation links', () => {
  it('hands the destination to real maps apps with exact coordinates', () => {
    const l = navLinks(17.4, 78.45, 'Pickup: Banjara Hills')
    expect(l.google).toBe('https://www.google.com/maps/dir/?api=1&destination=17.400000,78.450000&travelmode=driving')
    expect(l.geo.startsWith('geo:17.400000,78.450000?q=')).toBe(true); expect(l.geo).toContain('Pickup%3A%20Banjara%20Hills')
    expect(l.osm).toContain('mlat=17.400000'); expect(l.osm).toContain('#map=16/17.40000/78.45000')
  })
})
