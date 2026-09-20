import type { GenerationConfig } from './types'

export type RendererSupport = 'active' | 'partial' | 'preparation_only'

export interface LayoutPreset {
  id: string
  name: string
  description: string
  config: NonNullable<GenerationConfig['layout']>
  preview: { content: { x: number; y: number; width: number; height: number }; title?: { x: number; y: number; width: number; height: number }; background: 'none' | 'soft' }
  renderer_support: RendererSupport
}

export const LAYOUT_PRESETS: Record<string, LayoutPreset> = {
  vertical_9_16: {
    id: 'vertical_9_16', name: 'Current / Default',
    description: 'The current full-frame vertical output.',
    config: { preset_id: 'vertical_9_16', target_aspect_ratio: '9:16', background_mode: 'none' },
    preview: { content: { x: 0, y: 0, width: 1, height: 1 }, background: 'none' },
    renderer_support: 'active',
  },
  full_9_16: {
    id: 'full_9_16', name: 'Full 9:16',
    description: 'Full-frame 9:16; equivalent to the current renderer today.',
    config: { preset_id: 'full_9_16', target_aspect_ratio: '9:16', background_mode: 'none' },
    preview: { content: { x: 0, y: 0, width: 1, height: 1 }, background: 'none' },
    renderer_support: 'partial',
  },
  square_title: {
    id: 'square_title', name: 'Square + Title',
    description: 'Square content with title space above; preparation only for now.',
    config: { preset_id: 'square_title', target_aspect_ratio: '9:16', content_aspect_ratio: '1:1', background_mode: 'soft', title_placement_relation: 'above' },
    preview: { content: { x: 0.08, y: 0.28, width: 0.84, height: 0.47 }, title: { x: 0.1, y: 0.12, width: 0.8, height: 0.1 }, background: 'soft' },
    renderer_support: 'preparation_only',
  },
  inset_portrait: {
    id: 'inset_portrait', name: 'Inset Portrait',
    description: 'Portrait video inset on a soft canvas; preparation only for now.',
    config: { preset_id: 'inset_portrait', target_aspect_ratio: '9:16', content_aspect_ratio: '9:16', content_bbox: { x: 0.13, y: 0.14, width: 0.74, height: 0.72 }, background_mode: 'soft' },
    preview: { content: { x: 0.13, y: 0.14, width: 0.74, height: 0.72 }, background: 'soft' },
    renderer_support: 'preparation_only',
  },
}

export const CAPTION_PRESETS = [
  {
    id: 'clean', name: 'Clean', description: 'Balanced existing caption treatment.',
    config: { preset_id: 'classic', fill: 'white' as const }, preview: { fill: 'white', highlight: null }, renderer_support: 'active' as RendererSupport,
  },
  {
    id: 'bold', name: 'Bold', description: 'Current high-impact default treatment.',
    config: { preset_id: 'hormozi', fill: 'white' as const }, preview: { fill: 'white', highlight: 'CHANGES' }, renderer_support: 'active' as RendererSupport,
  },
  {
    id: 'highlight', name: 'Highlight', description: 'Uses the existing emphasis-capable preset.',
    config: { preset_id: 'karaoke-pop', fill: 'white' as const }, preview: { fill: 'white', highlight: 'EVERYTHING' }, renderer_support: 'active' as RendererSupport,
  },
  {
    id: 'minimal', name: 'Minimal', description: 'A quieter existing preset with the same supported renderer controls.',
    config: { preset_id: 'minimal', fill: 'white' as const }, preview: { fill: 'white', highlight: null }, renderer_support: 'active' as RendererSupport,
  },
] as const

export function layoutPresetForConfig(presetId?: string | null): LayoutPreset | undefined {
  return LAYOUT_PRESETS[presetId || '']
}

export function captionPresetForConfig(presetId?: string | null) {
  return CAPTION_PRESETS.find((preset) => preset.config.preset_id === presetId)
}
