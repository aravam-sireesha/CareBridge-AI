import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

afterEach(() => { cleanup(); localStorage.clear() })
window.scrollTo = () => {}
Element.prototype.scrollIntoView = () => {}
class IO { observe() {} unobserve() {} disconnect() {} }
window.IntersectionObserver = window.IntersectionObserver || IO
