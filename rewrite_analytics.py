import re
from pathlib import Path

file_path = Path("app/src/components/Analytics.tsx")
content = file_path.read_text()

# 1. Change activeTab state
content = content.replace(
    "const [activeTab, setActiveTab] = useState<'transcripts' | 'clips'>('transcripts')",
    "const [activeTab, setActiveTab] = useState<'home' | 'videos'>('home')\n  const [videoFilter, setVideoFilter] = useState<'all' | 'source' | 'mine' | 'competitor'>('all')\n  const [showAddMediaModal, setShowAddMediaModal] = useState(false)\n  const [addMediaType, setAddMediaType] = useState<'source' | 'mine' | 'competitor'>('source')\n  const [addMediaUrl, setAddMediaUrl] = useState('')"
)

# 2. Add handleAddMedia
add_media_func = """
  async function handleAddMedia(e: React.FormEvent) {
    e.preventDefault()
    if (!addMediaUrl.trim() || !activeId) return
    
    const urls = addMediaUrl.split(/[\\s,]+/).filter(url => url.trim().length > 0)
    if (urls.length === 0) return

    try {
      setLoading(true)
      if (addMediaType === 'source') {
        await Promise.all(urls.map(url => api.addCampaignVideo(activeId, url.trim())))
      } else {
        await Promise.all(urls.map(url => api.analyzeClip(activeId, url.trim(), addMediaType)))
      }
      setAddMediaUrl('')
      setShowAddMediaModal(false)
      await loadCampaign(activeId)
    } catch (err) {
      console.error('Error adding media:', err)
    } finally {
      setLoading(false)
    }
  }
"""
content = content.replace(
    "async function handleAddVideo(e: React.FormEvent) {",
    add_media_func + "\n  async function handleAddVideo(e: React.FormEvent) {"
)

# 3. Modify Tabs UI
tabs_ui = """
        <div className="tabs" style={{ display: 'flex', gap: '16px', marginBottom: '24px', borderBottom: '1px solid var(--border)' }}>
          <button 
            style={{ padding: '8px 16px', background: 'none', border: 'none', borderBottom: activeTab === 'home' ? '2px solid var(--primary)' : '2px solid transparent', color: activeTab === 'home' ? 'var(--fg)' : 'var(--dim)', cursor: 'pointer', fontWeight: 600 }} 
            onClick={() => setActiveTab('home')}
          >
            Home
          </button>
          <button 
            style={{ padding: '8px 16px', background: 'none', border: 'none', borderBottom: activeTab === 'videos' ? '2px solid var(--primary)' : '2px solid transparent', color: activeTab === 'videos' ? 'var(--fg)' : 'var(--dim)', cursor: 'pointer', fontWeight: 600 }} 
            onClick={() => setActiveTab('videos')}
          >
            Videos
          </button>
        </div>
"""
content = re.sub(r'<div className="tabs".*?</div>', tabs_ui, content, flags=re.DOTALL)

file_path.write_text(content)
