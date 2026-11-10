import { RotateCcw, X } from 'lucide-react';
import type { Dispatch, SetStateAction } from 'react';

export type MindMapTheme = 'Original' | 'Midnight' | 'Graphite' | 'Plum' | 'Ember';
export type MindMapPalette = 'Natural' | 'Default' | 'Lava' | 'Ocean' | 'Forest' | 'Aurora' | 'Mono' | 'Sunset';
export type MindMapLayout = 'Spheres' | 'Folder tree' | 'Cloud';
export type MindMapGroupBy = 'Function' | 'Runtime status' | 'Recorded issues';

export type MindMapSettings = {
  theme: MindMapTheme;
  palette: MindMapPalette;
  anatomy: number;
  layout: MindMapLayout;
  groupBy: MindMapGroupBy;
  showLinks: boolean;
  showBrainstem: boolean;
  showLabels: boolean;
  hideUnverified: boolean;
  turning: boolean;
  speed: number;
  limitRotation: boolean;
  pointSize: number;
};

export const DEFAULT_MIND_MAP_SETTINGS: MindMapSettings = {
  theme: 'Original',
  palette: 'Natural',
  anatomy: 100,
  layout: 'Spheres',
  groupBy: 'Function',
  showLinks: true,
  showBrainstem: true,
  showLabels: false,
  hideUnverified: false,
  turning: true,
  speed: 35,
  limitRotation: false,
  pointSize: 100,
};

type MapGroup = { id: string; label: string; color: string };

type Props = {
  open: boolean;
  settings: MindMapSettings;
  setSettings: Dispatch<SetStateAction<MindMapSettings>>;
  groups: readonly MapGroup[];
  activeGroups: Set<string>;
  onToggleGroup: (id: string) => void;
  onClose: () => void;
  onWalkthrough: () => void;
  onRestoreBrain: () => void;
  onFocusBrain: () => void;
  onReset: () => void;
};

function SettingToggle({
  label,
  checked,
  onChange,
  help,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  help?: string;
}) {
  return (
    <label className="omh-setting-toggle">
      <span>
        <strong>{label}</strong>
        {help && <small>{help}</small>}
      </span>
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
    </label>
  );
}

export function MindMapSettingsPanel({
  open,
  settings,
  setSettings,
  groups,
  activeGroups,
  onToggleGroup,
  onClose,
  onWalkthrough,
  onRestoreBrain,
  onFocusBrain,
  onReset,
}: Props) {
  if (!open) return null;
  const update = <K extends keyof MindMapSettings>(key: K, value: MindMapSettings[K]) => {
    setSettings((current) => ({ ...current, [key]: value }));
  };

  return (
    <aside id="omh-map-settings" className="omh-settings-panel" aria-label="Mind map settings" data-testid="mindmap-settings-panel">
      <div className="omh-settings-heading">
        <div>
          <span>MAP CONTROLS</span>
          <strong>Personalise the view</strong>
        </div>
        <button type="button" onClick={onClose} aria-label="Close settings"><X size={15} /></button>
      </div>

      <section className="omh-settings-section">
        <h3>Appearance</h3>
        <label className="omh-setting-select"><span>Theme</span>
          <select value={settings.theme} onChange={(event) => update('theme', event.target.value as MindMapTheme)}>
            {(['Original', 'Midnight', 'Graphite', 'Plum', 'Ember'] as const).map((theme) => <option key={theme}>{theme}</option>)}
          </select>
        </label>
        <label className="omh-setting-select"><span>Data colours</span>
          <select value={settings.palette} onChange={(event) => update('palette', event.target.value as MindMapPalette)}>
            {(['Natural', 'Default', 'Lava', 'Ocean', 'Forest', 'Aurora', 'Mono', 'Sunset'] as const).map((palette) => <option key={palette}>{palette}</option>)}
          </select>
        </label>
      </section>

      <section className="omh-settings-section">
        <h3>Brain form</h3>
        <label className="omh-setting-select"><span>Layout</span>
          <select value={settings.layout} onChange={(event) => update('layout', event.target.value as MindMapLayout)}>
            {(['Spheres', 'Folder tree', 'Cloud'] as const).map((layout) => <option key={layout}>{layout}</option>)}
          </select>
        </label>
        <label className="omh-setting-range">
          <span><strong>Anatomy</strong><output>{settings.anatomy}%</output></span>
          <input type="range" min="0" max="100" value={settings.anatomy} onChange={(event) => update('anatomy', Number(event.target.value))} />
        </label>
        <SettingToggle label="Links" checked={settings.showLinks} onChange={(value) => update('showLinks', value)} />
        <SettingToggle label="Brainstem" checked={settings.showBrainstem} onChange={(value) => update('showBrainstem', value)} />
      </section>

      <section className="omh-settings-section">
        <h3>Organisation</h3>
        <label className="omh-setting-select"><span>Group by</span>
          <select value={settings.groupBy} onChange={(event) => update('groupBy', event.target.value as MindMapGroupBy)}>
            {(['Function', 'Runtime status', 'Recorded issues'] as const).map((value) => <option key={value}>{value}</option>)}
          </select>
        </label>
        <SettingToggle label="Show all labels" help="Search and selected-node labels still work when off." checked={settings.showLabels} onChange={(value) => update('showLabels', value)} />
        <SettingToggle label="Hide unverified runtime" help="Only nodes with a process-status source remain visible." checked={settings.hideUnverified} onChange={(value) => update('hideUnverified', value)} />
      </section>

      <section className="omh-settings-section">
        <h3>Show systems</h3>
        {groups.map((group) => (
          <SettingToggle key={group.id} label={group.label} checked={activeGroups.has(group.id)} onChange={() => onToggleGroup(group.id)} />
        ))}
      </section>

      <section className="omh-settings-section">
        <h3>Motion</h3>
        <SettingToggle label="Turning" checked={settings.turning} onChange={(value) => update('turning', value)} />
        <label className="omh-setting-range">
          <span><strong>Speed</strong><output>{settings.speed}%</output></span>
          <input type="range" min="0" max="100" value={settings.speed} onChange={(event) => update('speed', Number(event.target.value))} />
        </label>
        <SettingToggle label="Limit rotation" checked={settings.limitRotation} onChange={(value) => update('limitRotation', value)} />
      </section>

      <section className="omh-settings-section">
        <h3>Points</h3>
        <label className="omh-setting-range">
          <span><strong>Size</strong><output>{settings.pointSize}%</output></span>
          <input type="range" min="40" max="220" value={settings.pointSize} onChange={(event) => update('pointSize', Number(event.target.value))} />
        </label>
      </section>

      <div className="omh-settings-actions">
        <button type="button" onClick={onWalkthrough}>Walkthrough</button>
        <button type="button" onClick={onRestoreBrain}>Show reference brain</button>
        <button type="button" onClick={onFocusBrain}>Focus brain</button>
        <button type="button" onClick={onReset}><RotateCcw size={12} /> Reset all</button>
      </div>
    </aside>
  );
}
