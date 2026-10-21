/** @type {import('tailwindcss').Config} */
const scale = (c) => c
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#F8FAFC',
        surface: '#FFFFFF',
        line: '#E2E8F0',
        ink: '#0F172A',
        'ink-muted': '#475569',
        // Primary #0F766E = teal-700, hover #115E59 = teal-800 (the Tailwind teal scale)
        teal: {
          50: '#F0FDFA', 100: '#CCFBF1', 200: '#99F6E4', 300: '#5EEAD4', 400: '#2DD4BF', 500: '#14B8A6',
          600: '#0D9488', 700: '#0F766E', 800: '#115E59', 900: '#134E4A'
        },
        // Informational blue #2563EB = sky-600
        sky: {
          50: '#EFF6FF', 100: '#DBEAFE', 200: '#BFDBFE', 300: '#93C5FD', 400: '#60A5FA',
          500: '#3B82F6', 600: '#2563EB', 700: '#1D4ED8', 800: '#1E40AF', 900: '#1E3A8A'
        },
        // Warning amber #D97706 = amber-600 (use amber-700 for TEXT: amber-600 on white is only 3.2:1)
        amber: { 50: '#FFFBEB', 100: '#FEF3C7', 400: '#FBBF24', 500: '#F59E0B', 600: '#D97706', 700: '#B45309' },
        // Success emerald #059669 = green-600 (use green-700 for TEXT)
        green: { 50: '#ECFDF5', 100: '#D1FAE5', 400: '#34D399', 500: '#10B981', 600: '#059669', 700: '#047857' },
        // Error #DC2626 = red-600
        red: { 50: '#FEF2F2', 100: '#FEE2E2', 400: '#F87171', 500: '#EF4444', 600: '#DC2626', 700: '#B91C1C' },
        violet: { 50: '#F3EFFC', 100: '#E4DCF8', 400: '#9A7FE0', 500: '#7C5CC8', 600: '#6445AD', 700: '#4D3586' },
        rose: { 50: '#FDEFF3', 100: '#FBD9E3', 400: '#EC7C9B', 500: '#DC567D', 600: '#BF3E64' }
      },
      fontFamily: {
        display: ['Lexend', 'system-ui', 'sans-serif'],
        body: ['Inter', 'system-ui', 'sans-serif'],
        script: ['Caveat', 'cursive']
      },
      boxShadow: {
        card: '0 1px 2px rgba(15,23,42,0.05), 0 1px 3px rgba(15,23,42,0.04)',
        lift: '0 12px 32px -8px rgba(15,23,42,0.18)',
        glow: '0 8px 20px -6px rgba(15,118,110,0.35)'
      },
      keyframes: {
        float: { '0%,100%': { transform: 'translateY(0)' }, '50%': { transform: 'translateY(-10px)' } },
        blob: { '0%,100%': { borderRadius: '42% 58% 60% 40% / 45% 45% 55% 55%' }, '50%': { borderRadius: '58% 42% 40% 60% / 55% 60% 40% 45%' } },
        shimmer: { '100%': { transform: 'translateX(100%)' } },
        riseIn: { from: { opacity: 0, transform: 'translateY(14px)' }, to: { opacity: 1, transform: 'translateY(0)' } },
        pop: { '0%': { transform: 'scale(.92)', opacity: 0 }, '100%': { transform: 'scale(1)', opacity: 1 } },
        gradientX: { '0%,100%': { backgroundPosition: '0% 50%' }, '50%': { backgroundPosition: '100% 50%' } },
        dots: { '0%,80%,100%': { transform: 'scale(.6)', opacity: .4 }, '40%': { transform: 'scale(1)', opacity: 1 } }
      },
      animation: {
        float: 'float 6s ease-in-out infinite',
        'float-slow': 'float 9s ease-in-out infinite',
        blob: 'blob 12s ease-in-out infinite',
        'rise-in': 'riseIn .5s ease-out both',
        pop: 'pop .25s ease-out both',
        gradient: 'gradientX 10s ease infinite',
        dots: 'dots 1.2s ease-in-out infinite'
      }
    }
  },
  plugins: []
}
