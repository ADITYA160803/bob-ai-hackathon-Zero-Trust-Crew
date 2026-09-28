/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        bg: '#0B0F1A',
        surface: '#121826',
        'surface-2': '#1B2436',
        border: '#2A3550',
        primary: '#22D3EE',
        kingpin: '#EF4444',
        handler: '#A78BFA',
        mule: '#F59E0B',
        operator: '#F472B6',
        victim: '#60A5FA',
        unknown: '#64748B',
        success: '#22C55E',
        warning: '#FACC15',
        text: '#E6EAF2',
        'text-muted': '#8B97B1',
      },
      fontFamily: {
        heading: ['"Space Grotesk"', 'system-ui', 'sans-serif'],
        body: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
      },
      spacing: {
        '4.5': '1.125rem',
      },
      borderRadius: {
        card: '12px',
        input: '8px',
      },
    },
  },
  plugins: [],
}
