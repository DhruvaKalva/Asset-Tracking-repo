/** UI-only state: theme, fleet filters, map selection, playback transport. */
import { create } from "zustand";
import { persist } from "zustand/middleware";

type Theme = "light" | "dark";

interface ThemeState {
  theme: Theme;
  toggle: () => void;
}

export const useTheme = create<ThemeState>()(
  persist(
    (set) => ({
      theme: "dark",
      toggle: () => set((s) => ({ theme: s.theme === "dark" ? "light" : "dark" })),
    }),
    { name: "srts.theme" },
  ),
);

/** Stamps the root element so CSS tokens and Tailwind's dark: variant agree. */
export function applyTheme(theme: Theme) {
  document.documentElement.setAttribute("data-theme", theme);
}

export interface FleetFilters {
  search: string;
  status: string;
  type: string;
  siteId: string;
  breachesOnly: boolean;
}

interface FilterState extends FleetFilters {
  setFilter: <K extends keyof FleetFilters>(key: K, value: FleetFilters[K]) => void;
  reset: () => void;
}

const EMPTY: FleetFilters = { search: "", status: "", type: "", siteId: "", breachesOnly: false };

/**
 * Filters live outside React Query so the map and the table share one filter bar
 * without either owning it.
 */
export const useFilters = create<FilterState>((set) => ({
  ...EMPTY,
  setFilter: (key, value) => set({ [key]: value } as Pick<FleetFilters, typeof key>),
  reset: () => set(EMPTY),
}));

interface SelectionState {
  selectedId: string | null;
  select: (id: string | null) => void;
}

export const useSelection = create<SelectionState>((set) => ({
  selectedId: null,
  select: (selectedId) => set({ selectedId }),
}));

interface PlaybackState {
  playing: boolean;
  /** Index into the loaded track's point array. */
  cursor: number;
  speed: number;
  windowHours: number;
  setPlaying: (playing: boolean) => void;
  setCursor: (cursor: number) => void;
  setSpeed: (speed: number) => void;
  setWindowHours: (h: number) => void;
  reset: () => void;
}

export const usePlayback = create<PlaybackState>((set) => ({
  playing: false,
  cursor: 0,
  speed: 4,
  windowHours: 24,
  setPlaying: (playing) => set({ playing }),
  setCursor: (cursor) => set({ cursor }),
  setSpeed: (speed) => set({ speed }),
  setWindowHours: (windowHours) => set({ windowHours, cursor: 0, playing: false }),
  reset: () => set({ playing: false, cursor: 0 }),
}));
