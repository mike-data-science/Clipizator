import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { EditStyleProfile, GenerationConfig } from '../types'
import { CAPTION_PRESETS, LAYOUT_PRESETS, captionPresetForConfig, layoutPresetForConfig } from '../creativePresets'

interface Props {
  source?: string
  file?: File | null
  onBack: () => void
  onProcess: (config: GenerationConfig) => void | Promise<void>
}

const initialConfig: GenerationConfig = {
  config_version: 1,
  style_profile_id: 'publikclip-default',
  layout: { preset_id: 'vertical_9_16', target_aspect_ratio: '9:16' },
  captions: { preset_id: 'hormozi', enabled: true, fill: 'white' },
  broll: { mode: 'off', presentation: 'mixed' },
  sfx: { mode: 'off' },
  music: { mode: 'off' },
  title_hook: { mode: 'profile_default', enabled: true },
  camera: {
    speaker_change: 'cut', pan_duration_s: 0.6, deadzone_frac: 0.05,
    punch: { enabled: true, intensity: 1 }, zoom_lock_per_scene: true,
  },
  transitions: { mode: 'none' },
  user_overrides: {},
}

function choiceLabel(value: string | undefined, labels: Record<string, string>) {
  return labels[value || ''] || value || 'Default'
}

export default function CreativeSetup({ source, file, onBack, onProcess }: Props) {
  const [profiles, setProfiles] = useState<EditStyleProfile[]>([])
  const [config, setConfig] = useState<GenerationConfig>(initialConfig)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [overriddenSections, setOverriddenSections] = useState<Set<string>>(new Set())

  useEffect(() => {
    let active = true
    api.listStyleProfiles()
      .then(({ profiles: loaded }) => {
        if (!active) return
        setProfiles(loaded)
        const defaultProfile = loaded.find((profile) => profile.is_default) || loaded[0]
        if (defaultProfile) setConfig((current) => ({ ...current, style_profile_id: current.style_profile_id || defaultProfile.id, layout: { ...defaultProfile.config.layout, ...current.layout }, captions: { ...defaultProfile.config.captions, ...current.captions } }))
      })
      .catch((err) => active && setError(err instanceof Error ? err.message : 'Could not load style profiles.'))
      .finally(() => active && setLoading(false))
    return () => { active = false }
  }, [])

  const selectedProfile = useMemo(
    () => profiles.find((profile) => profile.id === config.style_profile_id),
    [profiles, config.style_profile_id],
  )

  const setSection = <K extends keyof GenerationConfig>(section: K, value: GenerationConfig[K]) => {
    setConfig((current) => ({ ...current, [section]: value }))
    if (section !== 'style_profile_id') setOverriddenSections((current) => new Set(current).add(String(section)))
  }

  const selectProfile = (profile: EditStyleProfile) => {
    setConfig((current) => ({
      ...current,
      style_profile_id: profile.id,
      layout: overriddenSections.has('layout') ? current.layout : { ...current.layout, ...profile.config.layout },
      captions: overriddenSections.has('captions') ? current.captions : { ...current.captions, ...profile.config.captions },
    }))
  }

  const selectLayout = (presetId: string) => {
    const preset = LAYOUT_PRESETS[presetId]
    if (preset) setSection('layout', { ...preset.config })
  }

  const selectCaption = (presetId: string) => {
    const preset = CAPTION_PRESETS.find((item) => item.id === presetId)
    if (!preset) return
    setSection('captions', { ...config.captions, ...preset.config, fill: config.captions?.fill || preset.config.fill })
  }

  const process = async () => {
    setSaving(true)
    setError(null)
    try {
      await onProcess(config)
    } catch (err) {
      setSaving(false)
      setError(err instanceof Error ? err.message : 'Could not save creative setup.')
    }
  }

  const summary = [
    ['Style', selectedProfile?.name || config.style_profile_id || 'Publikclip Default'],
    ['Layout', layoutPresetForConfig(config.layout?.preset_id)?.name || 'Custom'],
    ['Captions', config.captions?.enabled === false ? 'Off' : captionPresetForConfig(config.captions?.preset_id)?.name || 'Custom'],
    ['B-roll', choiceLabel(config.broll?.mode, { off: 'Off', conservative: 'Conservative', balanced: 'Balanced', aggressive: 'Aggressive' })],
    ['SFX', choiceLabel(config.sfx?.mode, { off: 'Off', minimal: 'Minimal', balanced: 'Balanced', punchy: 'Punchy' })],
    ['Music', choiceLabel(config.music?.mode, { off: 'Off', low: 'Low', medium: 'Medium' })],
    ['Title Hook', choiceLabel(config.title_hook?.mode, { profile_default: 'Profile Default', none: 'None', generated: 'Generated', manual: 'Manual' })],
  ]

  return <div className="creative-setup-page">
    <header className="creative-setup-header">
      <button className="creative-back" onClick={onBack}>← Back</button>
      <div><span className="creative-kicker">NEW PROJECT</span><h1>Creative Setup</h1></div>
      <span className="creative-step">02 / 03</span>
    </header>
    <main className="creative-setup-main">
      <div className="creative-setup-intro">
        <div><p className="new-eyebrow">MONEY ENGINE</p><h2>Shape the cut before it starts.</h2><p>Choose a style and keep the rest intentionally light. You can refine the edit later.</p></div>
        <div className="creative-source">{file ? `Upload · ${file.name}` : source || 'Source selected'}</div>
      </div>
      {error && <div className="creative-error" role="alert">{error}</div>}
      <section className="creative-section">
        <div className="creative-section-heading"><div><span className="creative-index">01</span><h3>Style Profile</h3></div><small>{loading ? 'Loading profiles…' : selectedProfile?.description || 'Your starting point for the edit.'}</small></div>
        <div className="creative-profile-grid">
          {profiles.map((profile) => <button key={profile.id} className={`creative-profile-card ${config.style_profile_id === profile.id ? 'selected' : ''}`} onClick={() => selectProfile(profile)}>
            <span className="creative-profile-mark">✦</span><span><strong>{profile.name}</strong><small>{profile.scope === 'global' ? 'System profile' : `${profile.scope} profile`}</small></span><i>{config.style_profile_id === profile.id ? '✓' : ''}</i>
          </button>)}
          {!loading && !profiles.length && <p className="creative-muted">No profiles available. The default setup will still be saved.</p>}
        </div>
      </section>

      <div className="creative-columns">
        <section className="creative-section">
          <div className="creative-section-heading"><div><span className="creative-index">02</span><h3>Layout</h3></div><small>Cards use the saved preset geometry</small></div>
          <div className="creative-preset-grid creative-layout-grid">{Object.values(LAYOUT_PRESETS).map((preset) => <button key={preset.id} className={`creative-preset-card ${config.layout?.preset_id === preset.id ? 'selected' : ''}`} onClick={() => selectLayout(preset.id)}>
            <div className={`layout-preview ${preset.preview.background === 'soft' ? 'soft' : ''}`}><span className="layout-preview-video" style={{ left: `${preset.preview.content.x * 100}%`, top: `${preset.preview.content.y * 100}%`, width: `${preset.preview.content.width * 100}%`, height: `${preset.preview.content.height * 100}%` }} />{preset.preview.title && <span className="layout-preview-title" style={{ left: `${preset.preview.title.x * 100}%`, top: `${preset.preview.title.y * 100}%`, width: `${preset.preview.title.width * 100}%`, height: `${preset.preview.title.height * 100}%` }} />}</div>
            <span className="creative-preset-copy"><strong>{preset.name}</strong><small>{preset.description}</small><em className={`support-${preset.renderer_support}`}>{preset.renderer_support === 'active' ? 'Active output' : preset.renderer_support === 'partial' ? 'Partial · current output' : 'Preparation only'}</em></span><i>{config.layout?.preset_id === preset.id ? '✓' : ''}</i>
          </button>)}</div>
        </section>
        <section className="creative-section">
          <div className="creative-section-heading"><div><span className="creative-index">03</span><h3>Captions</h3></div><small>Real renderer presets</small></div>
          <div className="creative-preset-grid caption-preset-grid">{CAPTION_PRESETS.map((preset) => <button key={preset.id} className={`creative-preset-card caption-preset-card ${config.captions?.preset_id === preset.config.preset_id ? 'selected' : ''}`} onClick={() => selectCaption(preset.id)}>
            <div className="caption-preview" style={{ color: String(preset.preview.fill) === 'yellow' ? '#b08c00' : String(preset.preview.fill) === 'cyan' ? '#038da0' : '#292936' }}><span>THIS</span> <span className={preset.preview.highlight ? 'caption-preview-highlight' : ''}>{preset.preview.highlight || 'CHANGES'}</span> <span>EVERYTHING</span></div>
            <span className="creative-preset-copy"><strong>{preset.name}</strong><small>{preset.description}</small><em className="support-active">Active output</em></span><i>{config.captions?.preset_id === preset.config.preset_id ? '✓' : ''}</i>
          </button>)}</div>
          <div className="creative-control-row creative-caption-controls"><label className="creative-toggle"><input type="checkbox" checked={config.captions?.enabled !== false} onChange={(event) => setSection('captions', { ...config.captions, enabled: event.target.checked })} /><span />Enabled</label><span className="creative-color-label">Fill</span>{(['white', 'yellow', 'cyan'] as const).map((color) => <button key={color} className={`creative-color ${config.captions?.fill === color ? 'selected' : ''} ${color}`} onClick={() => setSection('captions', { ...config.captions, fill: color })}>{color}</button>)}</div>
        </section>
      </div>

      <div className="creative-columns">
        <section className="creative-section"><div className="creative-section-heading"><div><span className="creative-index">04</span><h3>Visuals / B-roll</h3></div><small>Policy only · no automatic insertion yet</small></div><div className="creative-segmented">{(['off', 'conservative', 'balanced', 'aggressive'] as const).map((mode) => <button key={mode} className={config.broll?.mode === mode ? 'selected' : ''} onClick={() => setSection('broll', { ...config.broll, mode })}>{mode[0].toUpperCase() + mode.slice(1)}</button>)}</div><div className="creative-subcontrol"><span>Presentation</span><select value={config.broll?.presentation || 'mixed'} onChange={(event) => setSection('broll', { ...config.broll, presentation: event.target.value as 'replace' | 'overlay' | 'mixed' })}><option value="mixed">Mixed</option><option value="replace">Replace</option><option value="overlay">Overlay</option></select></div></section>
        <section className="creative-section"><div className="creative-section-heading"><div><span className="creative-index">05</span><h3>Sound</h3></div><small>SFX and music policies are saved for future passes</small></div><div className="creative-sound-grid"><label>SFX<select value={config.sfx?.mode || 'off'} onChange={(event) => setSection('sfx', { ...config.sfx, mode: event.target.value as 'off' | 'minimal' | 'balanced' | 'punchy' })}><option value="off">Off</option><option value="minimal">Minimal</option><option value="balanced">Balanced</option><option value="punchy">Punchy</option></select></label><label>Music<select value={config.music?.mode || 'off'} onChange={(event) => setSection('music', { ...config.music, mode: event.target.value as 'off' | 'low' | 'medium' })}><option value="off">Off</option><option value="low">Low</option><option value="medium">Medium</option></select></label></div></section>
      </div>

      <section className="creative-section"><div className="creative-section-heading"><div><span className="creative-index">06</span><h3>Title Hook</h3></div><small>Mode is saved; text generation is not enabled yet</small></div><div className="creative-segmented creative-hook-options">{(['profile_default', 'none', 'generated', 'manual'] as const).map((mode) => <button key={mode} className={config.title_hook?.mode === mode ? 'selected' : ''} onClick={() => setSection('title_hook', { ...config.title_hook, mode, enabled: mode !== 'none' })}>{choiceLabel(mode, { profile_default: 'Profile Default', none: 'None', generated: 'Generated', manual: 'Manual' })}</button>)}</div>{config.title_hook?.mode === 'manual' && <input className="creative-text-input" value={config.title_hook.manual_text || ''} onChange={(event) => setSection('title_hook', { ...config.title_hook, manual_text: event.target.value })} placeholder="Write the opening title hook…" />}</section>

      <details className="creative-section creative-advanced"><summary><span><span className="creative-index">07</span><strong>Advanced</strong></span><small>Camera / punch controls</small></summary><div className="creative-advanced-grid"><label>Speaker change<select value={config.camera?.speaker_change || 'cut'} onChange={(event) => setSection('camera', { ...config.camera, speaker_change: event.target.value as 'cut' | 'pan' | 'locked' })}><option value="cut">Cut</option><option value="pan">Pan</option><option value="locked">Locked</option></select></label><label>Pan duration <input type="number" min="0" max="3" step="0.1" value={config.camera?.pan_duration_s ?? 0.6} onChange={(event) => setSection('camera', { ...config.camera, pan_duration_s: Number(event.target.value) })} /></label><label>Deadzone <input type="number" min="0" max="0.5" step="0.01" value={config.camera?.deadzone_frac ?? 0.05} onChange={(event) => setSection('camera', { ...config.camera, deadzone_frac: Number(event.target.value) })} /></label><label className="creative-toggle"><input type="checkbox" checked={config.camera?.punch?.enabled !== false} onChange={(event) => setSection('camera', { ...config.camera, punch: { ...config.camera?.punch, enabled: event.target.checked } })} /><span />Punch in</label><label className="creative-toggle"><input type="checkbox" checked={config.camera?.zoom_lock_per_scene !== false} onChange={(event) => setSection('camera', { ...config.camera, zoom_lock_per_scene: event.target.checked })} /><span />Zoom lock per scene</label></div></details>

      <aside className="creative-summary"><div><p className="new-eyebrow">SETUP SUMMARY</p><h3>Ready to create</h3></div><div className="creative-summary-list">{summary.map(([label, value]) => <span key={label}><small>{label}</small><strong>{value}</strong></span>)}</div></aside>
      <footer className="creative-actions"><button className="creative-back" onClick={onBack}>Back</button><button className="new-primary creative-process" onClick={process} disabled={saving || loading}>{saving ? 'Saving setup…' : 'Create clips'}</button></footer>
    </main>
  </div>
}
