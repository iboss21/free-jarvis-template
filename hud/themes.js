/* Reges themes.
 *
 * A theme is not a colour swap. Each one carries an accent, a background
 * gradient pair, a grain weight and a full orb state palette, so switching
 * theme changes the whole feel of the room rather than one border.
 */

export const THEMES = {
  obsidian: {
    name: 'Obsidian',
    tag: 'cold · default',
    bg: '#05080b',
    ink: '#c9d6e0',
    accent: '#3fa8bd',
    glow: ['#0d3b44', '#071b22'],
    grain: 0.035,
    colors: {
      idle: '#2f6f7a', listening: '#dfe9ee', transcribing: '#3fa8bd',
      thinking: '#7c5cff', reasoning: '#ffab3d', working: '#3ddc84',
      speaking: '#3d9bff', error: '#ff4d4d',
    },
  },

  aurum: {
    name: 'Aurum',
    tag: 'black gold · luxury',
    bg: '#07060a',
    ink: '#e8dcc4',
    accent: '#c9a84c',
    glow: ['#3a2c0c', '#150f04'],
    grain: 0.05,
    colors: {
      idle: '#8a7331', listening: '#f4e8d0', transcribing: '#c9a84c',
      thinking: '#e0b64f', reasoning: '#ff9f45', working: '#d4bf6a',
      speaking: '#f0d98a', error: '#b8402f',
    },
  },

  ember: {
    name: 'Ember',
    tag: 'warm · volcanic',
    bg: '#0a0505',
    ink: '#e6cfc6',
    accent: '#e2603c',
    glow: ['#4a1409', '#1c0703'],
    grain: 0.045,
    colors: {
      idle: '#7a3423', listening: '#ffd9c9', transcribing: '#e2603c',
      thinking: '#ff7a45', reasoning: '#ffb03a', working: '#ff5f3d',
      speaking: '#ffcf8a', error: '#ff2d2d',
    },
  },

  nebula: {
    name: 'Nebula',
    tag: 'violet · deep space',
    bg: '#060512',
    ink: '#d5cfea',
    accent: '#8b6cff',
    glow: ['#2b1a5e', '#0e0824'],
    grain: 0.04,
    colors: {
      idle: '#4a3a8f', listening: '#e2dcff', transcribing: '#8b6cff',
      thinking: '#a97cff', reasoning: '#ff7ad9', working: '#5ce1e6',
      speaking: '#b39bff', error: '#ff4d7d',
    },
  },

  verdant: {
    name: 'Verdant',
    tag: 'green · terminal',
    bg: '#040806',
    ink: '#c3dccb',
    accent: '#3ddc84',
    glow: ['#0b3a24', '#04160e'],
    grain: 0.03,
    colors: {
      idle: '#256d4a', listening: '#d8f5e4', transcribing: '#3ddc84',
      thinking: '#5ce1a6', reasoning: '#c9e04a', working: '#3ddc84',
      speaking: '#8ff0c0', error: '#ff5a4d',
    },
  },

  glacier: {
    name: 'Glacier',
    tag: 'pale blue · clinical',
    bg: '#04070c',
    ink: '#cfdcea',
    accent: '#6aa8ff',
    glow: ['#12294d', '#050c18'],
    grain: 0.028,
    colors: {
      idle: '#2b4d80', listening: '#e6f0ff', transcribing: '#6aa8ff',
      thinking: '#7fc4ff', reasoning: '#9ad8ff', working: '#4d8fe0',
      speaking: '#b8dcff', error: '#ff5f6d',
    },
  },

  bone: {
    name: 'Bone',
    tag: 'monochrome · brutal',
    bg: '#070707',
    ink: '#d8d8d6',
    accent: '#b9b9b4',
    glow: ['#2a2a28', '#0e0e0d'],
    grain: 0.06,
    colors: {
      idle: '#5a5a58', listening: '#f0f0ee', transcribing: '#b9b9b4',
      thinking: '#d0d0cc', reasoning: '#9a9a96', working: '#e4e4e0',
      speaking: '#ffffff', error: '#c04040',
    },
  },
};

export const THEME_IDS = Object.keys(THEMES);

export function applyTheme(id) {
  const t = THEMES[id] || THEMES.obsidian;
  const r = document.documentElement.style;
  r.setProperty('--bg', t.bg);
  r.setProperty('--ink', t.ink);
  r.setProperty('--accent', t.accent);
  r.setProperty('--glow-a', t.glow[0]);
  r.setProperty('--glow-b', t.glow[1]);
  r.setProperty('--grain', String(t.grain));
  document.documentElement.dataset.theme = id;
  return t;
}
